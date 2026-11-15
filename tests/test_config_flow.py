"""Discovery, connection validation and errors in real HA config flow classes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.yeelight_curtain_ble.client import CurtainError
from custom_components.yeelight_curtain_ble.config_flow import CurtainConfigFlow


@pytest.fixture
async def flow(tmp_path):
    flow = CurtainConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow.context = {"source": "user"}
    flow._async_current_ids = MagicMock(return_value=set())
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


def discovery():
    return SimpleNamespace(address="AA:BB:CC:DD:EE:01", name="YLBT_CURT_TEST", connectable=True)


async def test_manual_flow_lists_discovered_connectable_device(flow):
    with patch(
        "custom_components.yeelight_curtain_ble.config_flow.bluetooth.async_discovered_service_info",
        return_value=[discovery()],
    ):
        result = await flow.async_step_user()
    assert result["type"] == "form" and result["step_id"] == "user"
    assert discovery().address in flow._devices


async def test_discovery_requires_confirm_and_read(flow):
    result = await flow.async_step_bluetooth(discovery())
    assert result["type"] == "form" and result["step_id"] == "confirm"
    flow._validate = AsyncMock(return_value={"adapter_set": 1, "adapter_side": 1})
    result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    assert result["data"]["address"] == discovery().address
    flow._validate.assert_awaited_once_with(discovery().address)


async def test_failed_read_keeps_flow_open(flow):
    await flow.async_step_bluetooth(discovery())
    flow._validate = AsyncMock(side_effect=CurtainError("unreachable"))
    result = await flow.async_step_confirm({})
    assert result["type"] == "form" and result["errors"] == {"base": "cannot_connect"}


async def test_no_device_shows_explanation(flow):
    with patch(
        "custom_components.yeelight_curtain_ble.config_flow.bluetooth.async_discovered_service_info",
        return_value=[],
    ):
        result = await flow.async_step_user()
    assert result["type"] == "abort" and result["reason"] == "no_devices_found"


async def test_non_connectable_device_rejected(flow):
    info = discovery()
    info.connectable = False
    result = await flow.async_step_bluetooth(info)
    assert result["type"] == "abort" and result["reason"] == "not_supported"


@pytest.mark.parametrize("saved", [{}, {"persistent_connection": False}])
async def test_options_default_and_preserve_music_preferences(tmp_path, saved):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(options={"music_effect": "Shine", "music_palette": "Tranquil", **saved})
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    options = CurtainConfigFlow.async_get_options_flow(entry)
    options.hass = hass
    options.handler = "test-entry"
    result = await options.async_step_init()
    assert result["type"] == "form"
    assert result["data_schema"]({}) == {
        "persistent_connection": saved.get("persistent_connection", True)
    }
    # A music preference may change while the form is open.
    entry.options["music_effect"] = "Spectrum"
    result = await options.async_step_init({"persistent_connection": False})
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "persistent_connection": False, "music_effect": "Spectrum", "music_palette": "Tranquil"
    }
    assert options.automatic_reload is True


async def test_options_import_remove_and_preserve_settings(tmp_path):
    from custom_components.yeelight_curtain_ble.custom_gif import OPT_CUSTOM_GIFS

    hass = HomeAssistant(str(tmp_path))
    old = {"name": "Old", "sha256": "a" * 64}
    entry = SimpleNamespace(entry_id="entry", options={OPT_CUSTOM_GIFS: {"Old": old}, "music_effect": "Shine", "last_custom_gif": "Old"})
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    options = CurtainConfigFlow.async_get_options_flow(entry)
    options.hass, options.handler = hass, "entry"
    missing = await options.async_step_init({"persistent_connection": False, "gif_name": "New"})
    assert missing["errors"] == {"base": "gif_name_and_file"}
    metadata = {"name": "New", "sha256": "b" * 64}
    with patch("custom_components.yeelight_curtain_ble.config_flow.import_uploaded_gif", return_value=metadata) as importer:
        result = await options.async_step_init({"persistent_connection": False, "gif_name": "New", "gif_file": "upload", "remove_gifs": ["Old"]})
    importer.assert_called_once_with(hass, "entry", "upload", "New")
    assert result["data"] == {OPT_CUSTOM_GIFS: {"New": metadata}, "music_effect": "Shine", "persistent_connection": False}
    replacement = {"name": "Old", "sha256": "b" * 64}
    with patch("custom_components.yeelight_curtain_ble.config_flow.import_uploaded_gif", return_value=replacement):
        result = await options.async_step_init({"persistent_connection": True, "gif_name": "Old", "gif_file": "upload"})
    assert "last_custom_gif" not in result["data"]
    assert result["data"][OPT_CUSTOM_GIFS]["Old"] == replacement
    with patch("custom_components.yeelight_curtain_ble.config_flow.import_uploaded_gif", side_effect=ValueError()):
        result = await options.async_step_init({"persistent_connection": True, "gif_name": "New", "gif_file": "upload"})
    assert result["type"] == "form" and result["errors"] == {"base": "invalid_gif"}
    assert entry.options[OPT_CUSTOM_GIFS] == {"Old": old}


@pytest.mark.parametrize("source,side", [("bluetooth", "right"), ("user", "left")])
async def test_unconfigured_curtain_requires_explicit_placement(flow, peripheral, source, side):
    peripheral.adapter_set = 0
    peripheral.adapter_side = 0

    async def connect(_hass, _address, callback, *, client_created=None, client_cleanup=None):
        peripheral.is_connected = True
        peripheral.disconnected_callback = callback
        if client_created is not None:
            client_created(peripheral)
        return peripheral

    with (
        patch("custom_components.yeelight_curtain_ble.coordinator.connect", connect),
        patch("custom_components.yeelight_curtain_ble.config_flow.bluetooth.async_discovered_service_info", return_value=[discovery()]),
    ):
        if source == "bluetooth":
            await flow.async_step_bluetooth(discovery())
            result = await flow.async_step_confirm({})
        else:
            result = await flow.async_step_user({"address": discovery().address})
        assert result["type"] == "form" and result["step_id"] == "placement"
        assert not any(r["method"].startswith("set_") for r in peripheral.requests)
        assert not peripheral.is_connected
        result = await flow.async_step_placement({"mounting_side": side})
    assert result["type"] == "create_entry" and result["data"] == {"address": discovery().address}
    assert peripheral.adapter_set == 1 and peripheral.adapter_side == int(side == "right")
    assert not peripheral.is_connected
    assert peripheral.power == "off" and peripheral.bright == 9


async def test_failed_placement_keeps_form_open_and_retry_uses_readback(flow, peripheral):
    from custom_components.yeelight_curtain_ble.client import CurtainClient

    peripheral.adapter_set = 0
    async def connect(_hass, _address, callback, *, client_created=None, client_cleanup=None):
        peripheral.is_connected = True
        peripheral.disconnected_callback = callback
        if client_created is not None:
            client_created(peripheral)
        return peripheral

    with patch("custom_components.yeelight_curtain_ble.coordinator.connect", connect):
        await flow.async_step_bluetooth(discovery())
        result = await flow.async_step_confirm({})
        assert result["step_id"] == "placement"
        with patch.object(CurtainClient, "set", AsyncMock()):
            result = await flow.async_step_placement({"mounting_side": "right"})
        assert result["type"] == "form" and result["errors"] == {"base": "setup_failed"}
        assert not peripheral.is_connected
        # A previous write can have succeeded even if its acknowledgement was lost.
        peripheral.adapter_set, peripheral.adapter_side = 1, 1
        before = len(peripheral.requests)
        result = await flow.async_step_placement({"mounting_side": "right"})
    assert result["type"] == "create_entry"
    assert not any(r["method"].startswith("set_") for r in peripheral.requests[before:])
    assert not peripheral.is_connected


async def test_configured_curtain_preserves_existing_side(flow, peripheral):
    peripheral.adapter_side = 0
    async def connect(_hass, _address, callback, *, client_created=None, client_cleanup=None):
        peripheral.is_connected = True
        peripheral.disconnected_callback = callback
        if client_created is not None:
            client_created(peripheral)
        return peripheral

    with patch("custom_components.yeelight_curtain_ble.coordinator.connect", connect):
        await flow.async_step_bluetooth(discovery())
        result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    assert not any(r["method"].startswith("set_") for r in peripheral.requests)
    assert peripheral.adapter_side == 0 and not peripheral.is_connected
