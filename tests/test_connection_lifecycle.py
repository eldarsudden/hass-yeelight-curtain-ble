"""Reproduce slot leaks at the backend boundary, including false local link state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant

from custom_components.yeelight_curtain_ble.client import CurtainClient, CurtainError
from custom_components.yeelight_curtain_ble.const import FILE_NOTIFY, JSON_NOTIFY
from custom_components.yeelight_curtain_ble.coordinator import create_client


@pytest.fixture(autouse=True)
def no_reported_slots():
    with patch("custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_current_scanners", return_value=[]):
        yield


def direct_client(peripheral, **kwargs):
    calls = []

    async def connector(callback):
        calls.append(peripheral)
        peripheral.is_connected = True
        peripheral.disconnected_callback = callback
        return peripheral

    return CurtainClient(connector, **kwargs), calls


async def test_link_down_still_cleans_backend_before_reconnect(peripheral):
    client, calls = direct_client(peripheral)
    await client.read_state()
    await peripheral.disconnect()  # unsolicited loss, not transport cleanup
    assert client._client is peripheral
    assert not peripheral.is_connected
    await client.read_state()
    assert len(calls) == 2 and peripheral.disconnects == 2
    await client.close()


async def test_failed_disconnect_with_false_connected_blocks_new_client(peripheral):
    client, calls = direct_client(peripheral)
    await client.read_state()
    original_disconnect = peripheral.disconnect

    async def unconfirmed_release():
        # ESPHome backend clears local state in finally even if the API fails.
        peripheral.is_connected = False
        peripheral.disconnected_callback(peripheral)
        raise BleakError("proxy did not acknowledge release")

    peripheral.disconnect = AsyncMock(side_effect=unconfirmed_release)
    with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
        await client.disconnect()
    for _ in range(3):
        with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
            await client.read_state()
    assert len(calls) == 1
    assert client._client is peripheral
    peripheral.disconnect = original_disconnect
    await client.read_state()
    assert len(calls) == 2
    await client.close()


async def test_disconnect_timeout_does_not_cancel_release_or_open_another_slot(peripheral):
    client, calls = direct_client(peripheral, timeout=0.001, disconnect_timeout=0.01)
    await client.read_state()
    release = asyncio.Event()
    entered = asyncio.Event()
    original_disconnect = peripheral.disconnect

    async def slow_release():
        entered.set()
        await release.wait()
        await original_disconnect()

    peripheral.disconnect = AsyncMock(side_effect=slow_release)
    with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
        await client.disconnect()
    assert entered.is_set() and not client._cleanup_task.done()
    with pytest.raises(CurtainError):
        await client.read_state()
    assert len(calls) == 1 and peripheral.disconnect.await_count == 1
    release.set()
    await client._cleanup_task
    peripheral.disconnect = original_disconnect
    await client.read_state()
    assert len(calls) == 2
    await client.close()


async def test_cancelling_disconnect_keeps_cleanup_owned(peripheral):
    client, calls = direct_client(peripheral)
    await client.read_state()
    entered, release = asyncio.Event(), asyncio.Event()
    original_disconnect = peripheral.disconnect

    async def slow_release():
        entered.set()
        await release.wait()
        await original_disconnect()

    peripheral.disconnect = slow_release
    task = asyncio.create_task(client.disconnect())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._client is peripheral and not client._cleanup_task.cancelled()
    next_read = asyncio.create_task(client.read_state())
    await asyncio.sleep(0)
    assert len(calls) == 1 and not next_read.done()
    release.set()
    await next_read
    assert len(calls) == 2
    await client.close()


async def test_live_backend_after_disconnect_is_not_reused_as_ready(peripheral):
    client, calls = direct_client(peripheral)
    await client.read_state()
    original_disconnect = peripheral.disconnect
    peripheral.disconnect = AsyncMock()  # returns success without closing link
    for _ in range(2):
        with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
            await client.disconnect()
    assert len(calls) == 1
    peripheral.disconnect = original_disconnect
    await client.close()


async def test_all_subscriptions_stop_before_disconnect(peripheral):
    client, _calls = direct_client(peripheral)
    await client.read_state()
    await client.upload(b"GIF89a" + b"x" * 50)
    order = []
    stop = peripheral.stop_notify
    disconnect = peripheral.disconnect

    async def record_stop(uuid):
        order.append(uuid)
        await stop(uuid)

    async def record_disconnect():
        order.append("disconnect")
        await disconnect()

    peripheral.stop_notify, peripheral.disconnect = record_stop, record_disconnect
    await client.close()
    assert set(order[:-1]) == {JSON_NOTIFY, FILE_NOTIFY}
    assert order[-1] == "disconnect"


async def test_notify_failure_still_releases_partial_session(peripheral):
    client, calls = direct_client(peripheral)
    peripheral.start_notify = AsyncMock(side_effect=BleakError("subscription failed"))
    with pytest.raises(BleakError):
        await client.read_state()
    assert not peripheral.is_connected and peripheral.disconnects == 1
    assert client._client is None and len(calls) == 1
    await client.close()


async def test_old_notifications_and_callbacks_do_not_touch_new_session(peripheral):
    replacement = type(peripheral)()
    backends = iter([peripheral, replacement])
    observed = []

    async def connector(callback):
        backend = next(backends)
        backend.disconnected_callback = callback
        return backend

    client = CurtainClient(connector, observed.append)
    await client.read_state()
    old_notification = peripheral.callbacks[JSON_NOTIFY]
    old_disconnect = peripheral.disconnected_callback
    await client.disconnect()
    await client.read_state()
    old_notification(None, b'{"method":"props","params":{"power":"on"}}\r\n')
    old_disconnect(peripheral)
    assert not observed and client._client is replacement and client._ready
    await client.close()


async def test_closed_client_rejects_late_commands(peripheral):
    client, calls = direct_client(peripheral)
    await client.read_state()
    await client.close()
    for _ in range(3):
        with pytest.raises(CurtainError, match="stopping"):
            await client.request("set_power", ["on", "smooth", 500])
    assert len(calls) == 1 and peripheral.power == "off"


async def test_close_cancels_connect_and_cleans_created_backend(peripheral):
    entered = asyncio.Event()
    client = None

    async def connector(callback):
        client.track_client(peripheral)
        peripheral.disconnected_callback = callback
        entered.set()
        await asyncio.Event().wait()

    client = CurtainClient(connector)
    reading = asyncio.create_task(client.read_state())
    await entered.wait()
    await client.close()
    with pytest.raises(asyncio.CancelledError):
        await reading
    assert not peripheral.is_connected and peripheral.disconnects == 1
    assert client.closed and client._client is None


async def test_failed_reload_cleanup_blocks_next_owner_even_when_locally_down(tmp_path, peripheral):
    hass = HomeAssistant(str(tmp_path))
    opened = []

    async def connector(_hass, _address, callback, *, client_created, client_cleanup):
        opened.append(peripheral)
        peripheral.is_connected = True
        peripheral.disconnected_callback = callback
        client_created(peripheral)
        return peripheral

    with patch("custom_components.yeelight_curtain_ble.coordinator.connect", connector):
        old = create_client(hass, "AA:BB:CC:DD:EE:01")
        await old.read_state()
        original_disconnect = peripheral.disconnect

        async def failed_release():
            peripheral.is_connected = False
            peripheral.disconnected_callback(peripheral)
            raise BleakError("no acknowledgment")

        peripheral.disconnect = failed_release
        with pytest.raises(CurtainError):
            await old.close()
        new = create_client(hass, "AA:BB:CC:DD:EE:01")
        with pytest.raises(CurtainError):
            await new.read_state()
        assert len(opened) == 1
        peripheral.disconnect = original_disconnect
        await new.read_state()
        assert len(opened) == 2
        with pytest.raises(CurtainError, match="stopping"):
            await old.read_state()
        await new.close()


async def test_two_owners_cannot_connect_to_same_address(tmp_path, peripheral):
    hass = HomeAssistant(str(tmp_path))
    opened = []

    async def connector(_hass, _address, callback, *, client_created, client_cleanup):
        opened.append(peripheral)
        peripheral.disconnected_callback = callback
        client_created(peripheral)
        return peripheral

    with patch("custom_components.yeelight_curtain_ble.coordinator.connect", connector):
        first = create_client(hass, "AA:BB:CC:DD:EE:01")
        second = create_client(hass, "aa:bb:cc:dd:ee:01")
        await first.read_state()
        with pytest.raises(CurtainError, match="already owns"):
            await second.read_state()
        assert len(opened) == 1 and peripheral.is_connected
        await second.close()
        await first.close()


async def test_connector_retries_only_after_failed_backend_is_cleaned(tmp_path, peripheral):
    order = []

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.disconnected_callback = kwargs["disconnected_callback"]

        async def connect(self, **_kwargs):
            order.append("connect")
            self.is_connected = True
            raise BleakError("failure after link up")

        async def disconnect(self):
            order.append("disconnect")
            await super().disconnect()

    # Model the retry connector's actual reuse of the same client object.
    async def establish(client_class, device, name, **kwargs):
        backend = client_class(device, disconnected_callback=kwargs["disconnected_callback"])
        for _ in range(2):
            try:
                await backend.connect()
            except BleakError:
                continue
        raise BleakError("attempts exhausted")

    hass = HomeAssistant(str(tmp_path))
    with (
        patch("custom_components.yeelight_curtain_ble.coordinator.BleakClientWithServiceCache", Backend),
        patch("custom_components.yeelight_curtain_ble.coordinator.establish_connection", establish),
        patch("custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_ble_device_from_address", return_value=SimpleNamespace(name="YLBT_CURT_TEST")),
    ):
        # Use the real production connector and ownership/tracking wrapper.
        client = create_client(hass, "AA:BB:CC:DD:EE:01")
        with pytest.raises(BleakError):
            await client.read_state()
        assert order == ["connect", "disconnect", "connect", "disconnect"]
        await client.close()


async def test_failed_connect_cleanup_aborts_internal_retry_and_retains_owner(tmp_path, peripheral):
    order = []

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.disconnected_callback = kwargs["disconnected_callback"]

        async def connect(self, **_kwargs):
            order.append("connect")
            raise BleakError("failed after allocating proxy slot")

        async def disconnect(self):
            order.append("disconnect")
            self.is_connected = False
            self.disconnected_callback(self)
            raise BleakError("release unconfirmed")

    async def establish(client_class, device, name, **kwargs):
        backend = client_class(device, disconnected_callback=kwargs["disconnected_callback"])
        for _ in range(3):
            try:
                await backend.connect()
            except BleakError:
                continue

    hass = HomeAssistant(str(tmp_path))
    with (
        patch("custom_components.yeelight_curtain_ble.coordinator.BleakClientWithServiceCache", Backend),
        patch("custom_components.yeelight_curtain_ble.coordinator.establish_connection", establish),
        patch("custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_ble_device_from_address", return_value=SimpleNamespace(name="YLBT_CURT_TEST")),
    ):
        client = create_client(hass, "AA:BB:CC:DD:EE:01")
        with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
            await client.read_state()
        assert order.count("connect") == 1
        assert client._client is not None and not client._client.is_connected
        with pytest.raises(CurtainError):
            await client.close()


async def test_json_timeout_does_not_shorten_backend_disconnect(peripheral):
    client, _calls = direct_client(peripheral, timeout=0.001)
    await client.read_state()
    original_disconnect = peripheral.disconnect

    async def longer_than_json_request():
        await asyncio.sleep(0.01)
        await original_disconnect()

    peripheral.disconnect = longer_than_json_request
    await client.disconnect()
    assert client._client is None and not peripheral.is_connected
    await client.close()


async def test_real_ha_wrapper_cannot_retry_after_losing_allocated_backend(tmp_path, monkeypatch):
    """HA drops _backend on connect failure; wrapper.disconnect then does nothing."""
    from bleak.backends.device import BLEDevice
    from habluetooth.wrappers import HaBleakClientWrapper

    from custom_components.yeelight_curtain_ble import coordinator as module

    address = "AA:BB:CC:DD:EE:01"
    allocated = []
    attempts = []
    low_level_disconnects = []
    device = BLEDevice(address, "YLBT_CURT_TEST", {"source": "proxy"})
    scanner = SimpleNamespace(
        name="test proxy", adapter_idx=None,
        _add_connecting=lambda _address: None,
        _finished_connecting=lambda *_args: None,
        get_allocations=lambda: SimpleNamespace(allocated=allocated, free=1, slots=3),
    )

    class LeakingBackend:
        is_connected = False

        def __init__(self, *_args, **_kwargs):
            pass

        async def connect(self, *_args, **_kwargs):
            attempts.append("connect")
            allocated.append(address.lower())
            raise BleakError("failure after reserving proxy slot")

        async def disconnect(self):
            low_level_disconnects.append("disconnect")
            allocated.clear()

    manager = SimpleNamespace(shutdown=False)
    selected = SimpleNamespace(device=device, scanner=scanner, client=LeakingBackend,
                               backend_name="ESPHome", source="proxy")
    monkeypatch.setattr("habluetooth.wrappers.get_manager", lambda: manager)
    monkeypatch.setattr(HaBleakClientWrapper, "_async_get_best_available_backend_and_device", lambda *_: selected)
    monkeypatch.setattr(module, "BleakClientWithServiceCache", HaBleakClientWrapper)
    monkeypatch.setattr(module, "SLOT_RELEASE_TIMEOUT", 0.005)
    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda _hass: [scanner])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: device)
    client = create_client(HomeAssistant(str(tmp_path)), address)
    with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
        await client.read_state()
    with pytest.raises(CurtainError):
        await client.read_state()
    assert attempts == ["connect"]
    assert not low_level_disconnects  # the real HA wrapper has lost the backend
    assert client._client._backend is None and client._client is not None
    allocated.clear()  # model proxy recovery; release ownership without reconnect
    await client.close()


async def test_existing_duplicate_allocations_block_connection_before_backend_attempt(tmp_path, monkeypatch):
    from custom_components.yeelight_curtain_ble import coordinator as module

    address = "AA:BB:CC:DD:EE:01"
    allocated = [address, address]
    scanner = SimpleNamespace(name="test proxy", get_allocations=lambda: SimpleNamespace(allocated=allocated))

    class Backend:
        is_connected = False
        attempts = 0

        def __init__(self, *_args, **_kwargs):
            pass

        async def connect(self, **_kwargs):
            type(self).attempts += 1

        async def disconnect(self):
            pass

    monkeypatch.setattr(module, "BleakClientWithServiceCache", Backend)
    monkeypatch.setattr(module, "SLOT_RELEASE_TIMEOUT", 0.005)
    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda _hass: [scanner])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: SimpleNamespace(name="test"))
    client = create_client(HomeAssistant(str(tmp_path)), address)
    with pytest.raises(CurtainError, match="reconnect blocked"):
        await client.read_state()
    assert Backend.attempts == 0
    allocated.clear()
    await client.close()


async def test_release_waits_for_own_address_even_when_another_slot_is_free(monkeypatch):
    from custom_components.yeelight_curtain_ble import coordinator as module

    address = "AA:BB:CC:DD:EE:01"
    allocated = [address, "AA:BB:CC:DD:EE:02"]
    scanner = SimpleNamespace(name="test proxy", get_allocations=lambda: SimpleNamespace(allocated=allocated, free=1))
    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda _hass: [scanner])
    task = asyncio.create_task(module.wait_for_slot_release(object(), address))
    await asyncio.sleep(0)
    assert not task.done()
    allocated.remove(address)
    await task
    assert allocated == ["AA:BB:CC:DD:EE:02"]
