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
    with (
        patch("custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_current_scanners", return_value=[]),
        patch("custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_scanner_devices_by_address", return_value=[]),
    ):
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


@pytest.mark.parametrize("release_fails", [False, True])
async def test_real_ha_wrapper_recovers_discarded_backend(tmp_path, monkeypatch, caplog, peripheral, release_fails):
    """Use real HA connect/failure/disconnect code, with a leaking proxy backend."""
    from bleak.backends.device import BLEDevice
    from habluetooth.wrappers import HaBleakClientWrapper

    from custom_components.yeelight_curtain_ble import coordinator as module

    address = "AA:BB:CC:DD:EE:01"
    other_address = "AA:BB:CC:DD:EE:02"
    allocated = [other_address]
    attempts = []
    low_level_disconnects = []
    instances = []
    release_blocked = [release_fails]
    device = BLEDevice(address, "YLBT_CURT_TEST", {"source": "proxy"})
    scanner = SimpleNamespace(
        name="test proxy", source="proxy", adapter_idx=None, _clients=set(),
        _add_connecting=lambda _address: None,
        _finished_connecting=lambda *_args: None,
        get_allocations=lambda: SimpleNamespace(allocated=allocated, free=1, slots=3),
    )

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.is_connected = False
            self.callback = kwargs["disconnected_callback"]
            self.services = SimpleNamespace(get_characteristic=lambda uuid: SimpleNamespace(
                uuid=uuid, max_write_without_response_size=509,
            ))
            instances.append(self)

        async def start_notify(self, characteristic, callback, **_kwargs):
            self.callbacks[characteristic.uuid] = lambda _char, data: callback(data)

        async def stop_notify(self, characteristic):
            self.callbacks.pop(getattr(characteristic, "uuid", characteristic), None)

        async def write_gatt_char(self, characteristic, data, response):
            await super().write_gatt_char(characteristic.uuid, data, response)

        async def connect(self, *_args, **_kwargs):
            attempts.append("connect")
            allocated.append(address.lower())
            if len(attempts) == 1:
                raise BleakError("failure after reserving proxy slot")
            self.is_connected = True

        async def disconnect(self):
            low_level_disconnects.append(self)
            was_connected = self.is_connected
            self.is_connected = False
            if was_connected:
                self.callback()
            if release_blocked[0]:
                raise BleakError("proxy did not acknowledge targeted release")
            allocated[:] = [item for item in allocated if item.upper() != address]

    manager = SimpleNamespace(shutdown=False, async_scanner_by_source=lambda _source: scanner)
    selected = SimpleNamespace(device=device, scanner=scanner, client=Backend,
                               backend_name="ESPHome", source="proxy")
    monkeypatch.setattr("habluetooth.wrappers.get_manager", lambda: manager)
    monkeypatch.setattr(HaBleakClientWrapper, "_async_get_best_available_backend_and_device", lambda *_: selected)
    monkeypatch.setattr(module, "BleakClientWithServiceCache", HaBleakClientWrapper)
    monkeypatch.setattr(module, "SLOT_RELEASE_TIMEOUT", 0.005)
    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda _hass: [scanner])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: device)
    client = create_client(HomeAssistant(str(tmp_path)), address)
    if release_fails:
        with pytest.raises(CurtainError, match="cleanup is unconfirmed"):
            await client.read_state()
        with pytest.raises(CurtainError):
            await client.read_state()
        assert attempts == ["connect"]
        assert client._client._backend is None  # HA discarded its pointer
        assert client._client._curtain_retained_backend is instances[0]
        assert low_level_disconnects  # real release attempts still reach backend
        release_blocked[0] = False
    state = await client.read_state()
    assert state["power"] == "off"
    assert attempts == ["connect", "connect"]
    assert low_level_disconnects[0] is instances[0]
    assert "failure after reserving proxy slot" in caplog.text
    assert "connect failed before cleanup" in caplog.text
    assert allocated == [other_address, address.lower()]
    await client.close()
    assert low_level_disconnects[-1] is instances[1]
    assert allocated == [other_address] and not scanner._clients
    assert client._client is None


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


async def test_busy_proxy_defers_without_allocating_then_connects(tmp_path, monkeypatch, peripheral):
    from custom_components.yeelight_curtain_ble import coordinator as module

    busy = [1]
    started = asyncio.Event()
    attempts = []
    path = SimpleNamespace(scanner=SimpleNamespace(connections_in_progress=lambda: busy[0]))
    monkeypatch.setattr(module.bluetooth, "async_scanner_devices_by_address", lambda *_: [path])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: SimpleNamespace(name="test"))

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.is_connected = False
            self.disconnected_callback = kwargs["disconnected_callback"]
            started.set()

        async def connect(self, **_kwargs):
            attempts.append("connect")
            self.is_connected = True

    monkeypatch.setattr(module, "BleakClientWithServiceCache", Backend)
    client = create_client(HomeAssistant(str(tmp_path)), "AA:BB:CC:DD:EE:01")
    read = asyncio.create_task(client.read_state())
    await started.wait()
    await asyncio.sleep(0)
    assert not attempts and not read.done()
    busy[0] = 0
    await read
    assert attempts == ["connect"]
    await client.close()


async def test_busy_proxy_timeout_does_not_start_backend_connect(tmp_path, monkeypatch, peripheral):
    from custom_components.yeelight_curtain_ble import coordinator as module

    attempts = []
    path = SimpleNamespace(scanner=SimpleNamespace(connections_in_progress=lambda: 1))
    monkeypatch.setattr(module.bluetooth, "async_scanner_devices_by_address", lambda *_: [path])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: SimpleNamespace(name="test"))
    monkeypatch.setattr(module, "ADAPTER_IDLE_TIMEOUT", 0.005)

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.is_connected = False
            self.disconnected_callback = kwargs["disconnected_callback"]

        async def connect(self, **_kwargs):
            attempts.append("connect")

    monkeypatch.setattr(module, "BleakClientWithServiceCache", Backend)
    client = create_client(HomeAssistant(str(tmp_path)), "AA:BB:CC:DD:EE:01")
    with pytest.raises(CurtainError, match="deferred without allocating"):
        await client.read_state()
    assert not attempts and client._client is None
    await client.close()


async def test_idle_path_is_usable_with_persistent_slots_and_another_busy_proxy(monkeypatch):
    from custom_components.yeelight_curtain_ble import coordinator as module

    paths = [SimpleNamespace(scanner=SimpleNamespace(connections_in_progress=lambda n=n: n))
             for n in (1, 0)]
    monkeypatch.setattr(module.bluetooth, "async_scanner_devices_by_address", lambda *_: paths)
    # Existing connected devices do not count as in-progress connection attempts.
    await module.wait_for_idle_adapter(object(), "AA:BB:CC:DD:EE:01")


async def test_cancel_while_waiting_for_busy_proxy_does_not_connect(tmp_path, monkeypatch, peripheral):
    from custom_components.yeelight_curtain_ble import coordinator as module

    started = asyncio.Event()
    attempts = []
    path = SimpleNamespace(scanner=SimpleNamespace(connections_in_progress=lambda: 1))
    monkeypatch.setattr(module.bluetooth, "async_scanner_devices_by_address", lambda *_: [path])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: SimpleNamespace(name="test"))

    class Backend(type(peripheral)):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            self.is_connected = False
            self.disconnected_callback = kwargs["disconnected_callback"]
            started.set()

        async def connect(self, **_kwargs):
            attempts.append("connect")

    monkeypatch.setattr(module, "BleakClientWithServiceCache", Backend)
    client = create_client(HomeAssistant(str(tmp_path)), "AA:BB:CC:DD:EE:01")
    read = asyncio.create_task(client.read_state())
    await started.wait()
    await client.close()
    with pytest.raises(asyncio.CancelledError):
        await read
    assert not attempts and client._client is None


@pytest.mark.parametrize("cancel_connect", [False, True])
async def test_real_esphome_backend_sends_targeted_disconnect_after_ha_drops_it(tmp_path, monkeypatch, cancel_connect):
    """Real ESPHome connect/abandon/disconnect and HA wrapper, mocked API peer."""
    from contextlib import nullcontext
    from unittest.mock import MagicMock

    from bleak.backends.device import BLEDevice
    from bleak_esphome.backend.client import ESPHomeClient, ESPHomeClientData
    from habluetooth.wrappers import HaBleakClientWrapper

    from custom_components.yeelight_curtain_ble import coordinator as module

    address = "AA:BB:CC:DD:EE:01"
    address_int = int(address.replace(":", ""), 16)
    other_address = "AA:BB:CC:DD:EE:02"
    allocated = [other_address]
    releases = []
    entered = asyncio.Event()
    device = BLEDevice(address, "YLBT_CURT_TEST", {"source": "proxy", "address_type": 0})
    scanner = SimpleNamespace(
        name="test proxy", adapter_idx=None,
        _add_connecting=lambda _address: None,
        _finished_connecting=lambda *_args: None,
        get_allocations=lambda: SimpleNamespace(allocated=allocated),
        connecting=nullcontext,
    )

    class ProxyAPI:
        async def bluetooth_device_connect(self, target, *_args, **_kwargs):
            assert target == address_int
            allocated.append(address)
            entered.set()
            if cancel_connect:
                await asyncio.Event().wait()
            raise TimeoutError("proxy connect timed out without connection-state response")

        async def bluetooth_device_disconnect(self, target):
            releases.append(target)
            allocated[:] = [item for item in allocated if item != address]

    cache = SimpleNamespace(get_gatt_mtu_cache=lambda _address: None)
    bluetooth_device = SimpleNamespace(cache=cache, ble_connections_free=1,
                                       async_untrack_client=MagicMock())
    data = ESPHomeClientData(
        bluetooth_device=bluetooth_device, client=ProxyAPI(),
        device_info=SimpleNamespace(bluetooth_proxy_feature_flags_compat=lambda _: 0),
        api_version=None, title="test proxy", scanner=scanner,
    )
    from functools import partial

    selected = SimpleNamespace(device=device, scanner=scanner,
                               client=partial(ESPHomeClient, client_data=data),
                               backend_name="ESPHome", source="proxy")
    monkeypatch.setattr("habluetooth.wrappers.get_manager", lambda: SimpleNamespace(shutdown=False))
    monkeypatch.setattr(HaBleakClientWrapper, "_async_get_best_available_backend_and_device", lambda *_: selected)
    monkeypatch.setattr(module, "BleakClientWithServiceCache", HaBleakClientWrapper)
    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda _hass: [scanner])
    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: device)
    wrappers = []

    async def one_attempt(client_class, ble_device, _name, **kwargs):
        wrapper = client_class(ble_device, disconnected_callback=kwargs["disconnected_callback"], _is_retry_client=True)
        wrappers.append(wrapper)
        await wrapper.connect()
        return wrapper

    monkeypatch.setattr(module, "establish_connection", one_attempt)
    client = create_client(HomeAssistant(str(tmp_path)), address)
    read = asyncio.create_task(client.read_state())
    await entered.wait()
    if cancel_connect:
        await client.close()
        with pytest.raises(asyncio.CancelledError):
            await read
    else:
        with pytest.raises(TimeoutError):
            await read
        await client.close()
    assert wrappers[0]._backend is None  # HA's normal failed-connect cleanup ran
    assert wrappers[0]._curtain_retained_backend is None  # release was confirmed
    assert releases == [address_int]  # actual ESPHome.disconnect called its API
    assert allocated == [other_address]  # no proxy reboot or unrelated disconnect
    assert client._client is None
