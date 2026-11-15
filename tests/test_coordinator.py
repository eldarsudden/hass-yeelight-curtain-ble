"""Exercise HA entities with a simulated Bluetooth peripheral."""

import json
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.yeelight_curtain_ble.const import DOMAIN, OPT_MUSIC_EFFECT, OPT_MUSIC_PALETTE
from custom_components.yeelight_curtain_ble.coordinator import CurtainCoordinator, load_catalog
from custom_components.yeelight_curtain_ble.light import CurtainLight
from custom_components.yeelight_curtain_ble.select import (
    MusicSelect,
    PresetSelect,
    async_setup_entry,
)


@pytest.fixture
async def coordinator(tmp_path, peripheral):
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Curtain",
        data={"address": "AA:BB:CC:DD:EE:01"},
        source="user",
        options={},
        unique_id="AA:BB:CC:DD:EE:01",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )
    hass.config_entries = MagicMock()

    def update_entry(entry, **kwargs):
        # ConfigEntry mutation normally goes through the manager.
        object.__setattr__(entry, "options", MappingProxyType(kwargs["options"]))

    hass.config_entries.async_update_entry.side_effect = update_entry

    async def connect(_hass, _address, disconnected):
        peripheral.is_connected = True
        peripheral.disconnected_callback = disconnected
        return peripheral

    with patch("custom_components.yeelight_curtain_ble.coordinator.connect", connect):
        coordinator = CurtainCoordinator(hass, entry, load_catalog())
        await coordinator.async_refresh()
        yield coordinator
        await coordinator.async_shutdown()


async def test_power_and_brightness_confirmed_by_readback(coordinator, peripheral):
    light = CurtainLight(coordinator)
    assert not light.is_on
    await light.async_turn_on(brightness=128)
    assert light.is_on and coordinator.data["bright"] == 50
    assert light.brightness == 128
    await light.async_turn_off()
    assert not light.is_on and peripheral.power == "off"
    await light.async_turn_on(brightness=0)
    assert not light.is_on


async def test_builtin_effect_requires_no_file(coordinator, peripheral):
    light = CurtainLight(coordinator)
    await light.async_turn_on(effect="Rainbow")
    assert light.effect == "Rainbow"
    assert not peripheral.file_packets


async def test_gif_effect_upload_before_activation(coordinator, peripheral):
    await coordinator.async_light_on(None, "Christmas Tree")
    assert peripheral.file_packets[-1] == b"\x04"
    assert coordinator.data["effect"][:2] == [71, 1007]


async def test_palette_is_preference_until_music_is_enabled(coordinator, peripheral):
    select = MusicSelect(coordinator, OPT_MUSIC_PALETTE, list(coordinator.catalog["palettes"]))
    before = len(peripheral.requests)
    await select.async_select_option("Tranquil")
    assert len(peripheral.requests) == before
    assert select.current_option == "Tranquil"
    await coordinator.async_music(True)
    request = next(r for r in peripheral.requests if r["method"] == "set_ps")
    params = json.loads(request["params"][1])
    assert params["on"] == 1 and params["effect_id"] == 88
    assert params["palatte"] == coordinator.catalog["palettes"]["Tranquil"]
    await coordinator.async_music(True, effect="Shine")
    assert coordinator.music_effect == "Shine"
    await coordinator.async_music(False)
    assert coordinator.data["music"]["on"] == 0


async def test_external_props_update_actual_state(coordinator):
    coordinator._props({"power": "on", "bright": "51", "mic_music_mode": '{"on":1,"effect_id":87}'})
    assert coordinator.data["power"] == "on"
    assert coordinator.data["bright"] == 51
    assert coordinator.music_effect == "Sound Wave"


async def test_failed_command_not_reported_as_success(coordinator, peripheral):
    coordinator.client.set = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(HomeAssistantError):
        await coordinator.async_power(True)
    assert not coordinator.last_update_success
    assert coordinator.data["power"] == "off"
    assert peripheral.disconnects == 1


async def test_ack_without_changed_state_reports_failure(coordinator):
    coordinator.client.set = AsyncMock()
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await coordinator.async_power(True)
    assert coordinator.data["power"] == "off"
    assert coordinator.last_update_success  # The read succeeded and is still truthful.


async def test_unknown_effect_rejected_without_writes(coordinator, peripheral):
    before = len(peripheral.requests)
    with pytest.raises(HomeAssistantError, match="Unknown effect"):
        await coordinator.async_light_on(None, "Not a real effect")
    assert len(peripheral.requests) == before


async def test_regular_effect_exits_music(coordinator, peripheral):
    await coordinator.async_music(True)
    await coordinator.async_light_on(None, "Bonfire")
    assert coordinator.data["music"]["on"] == 0
    assert coordinator.data["effect"][:2] == [34, 0]


async def test_regular_and_music_selects_have_separate_options(coordinator):
    add_entities = MagicMock()
    object.__setattr__(coordinator.entry, "runtime_data", coordinator)
    await async_setup_entry(coordinator.hass, coordinator.entry, add_entities)
    preset, music_effect, music_palette = add_entities.call_args.args[0]
    assert isinstance(preset, PresetSelect)
    assert len(preset.options) == 19 and "Christmas Tree" in preset.options
    assert "Sound Wave" not in preset.options
    assert music_effect.options == list(coordinator.catalog["music_effects"])
    assert music_palette.options == list(coordinator.catalog["palettes"])
    assert preset.unique_id != music_effect.unique_id != music_palette.unique_id


async def test_select_regular_preset_exits_music_without_changing_music_preferences(
    coordinator, peripheral
):
    preset = PresetSelect(coordinator)
    light = CurtainLight(coordinator)
    await coordinator.async_music_preference(OPT_MUSIC_EFFECT, "Shine")
    await coordinator.async_music(True)
    assert preset.current_option is None and light.effect is None
    before = len(peripheral.requests)
    await preset.async_select_option("Christmas Tree")
    assert preset.current_option == light.effect == "Christmas Tree"
    assert coordinator.data["music"]["on"] == 0
    assert light.is_on
    assert peripheral.file_packets[-1] == b"\x04"
    music_requests = [r for r in peripheral.requests[before:] if r["method"] == "set_ps"]
    assert [json.loads(r["params"][1]) for r in music_requests] == [{"on": 0}]
    assert coordinator.entry.options[OPT_MUSIC_EFFECT] == "Shine"


async def test_preset_selection_follows_readback_and_external_changes(coordinator):
    preset = PresetSelect(coordinator)
    assert preset.current_option == "UFO"
    coordinator._props({"fx_effect": '{"effect_id":39,"custom_id":0}'})
    assert preset.current_option == "Rainbow"
    coordinator._props({"fx_effect": '{"effect_id":999,"custom_id":0}'})
    assert preset.current_option is None
    coordinator.client.set = AsyncMock()
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await preset.async_select_option("Bonfire")
    # The readback replaces stale notifications, never the unconfirmed request.
    assert preset.current_option == "UFO"


async def test_persistent_default_keeps_connection_between_reads_and_commands(coordinator, peripheral):
    assert coordinator.persistent_connection is True
    assert peripheral.is_connected and peripheral.disconnects == 0
    await coordinator.async_power(True)
    await coordinator.async_refresh()
    assert peripheral.is_connected and peripheral.disconnects == 0


async def test_on_demand_reconnects_and_releases_after_whole_gif_operation(coordinator, peripheral):
    coordinator.persistent_connection = False
    await coordinator.async_refresh()
    assert not peripheral.is_connected and peripheral.disconnects == 1
    writes = peripheral.write_gatt_char

    async def connected_write(*args, **kwargs):
        assert peripheral.is_connected
        # No disconnect between power, upload, activation and readback.
        assert peripheral.disconnects == 1
        await writes(*args, **kwargs)

    peripheral.write_gatt_char = connected_write
    await coordinator.async_light_on(50, "Christmas Tree")
    assert not peripheral.is_connected and peripheral.disconnects == 2
    assert coordinator.data["bright"] == 50 and coordinator.preset == "Christmas Tree"
    assert peripheral.file_packets[-1] == b"\x04"
    peripheral.write_gatt_char = writes
    peripheral.bright = 75
    await coordinator.async_refresh()
    assert coordinator.data["bright"] == 75 and coordinator.last_update_success
    assert not peripheral.is_connected and peripheral.disconnects == 3


async def test_on_demand_error_and_cancellation_release_connection(coordinator, peripheral):
    import asyncio

    coordinator.persistent_connection = False
    coordinator.client.set = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(HomeAssistantError):
        await coordinator.async_power(True)
    assert not peripheral.is_connected
    await coordinator.async_refresh()
    started = asyncio.Event()

    async def cancelled_operation():
        await coordinator.client.request("get_prop", ["power"])
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(coordinator._execute(cancelled_operation, lambda state: True))
    await started.wait()
    assert peripheral.is_connected
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not peripheral.is_connected
    assert not coordinator._operation_lock.locked()


async def test_connection_setting_loaded_and_music_preferences_preserve_it(coordinator):
    from custom_components.yeelight_curtain_ble.const import OPT_PERSISTENT_CONNECTION

    object.__setattr__(coordinator.entry, "options", MappingProxyType({OPT_PERSISTENT_CONNECTION: False}))
    reloaded = CurtainCoordinator(coordinator.hass, coordinator.entry, coordinator.catalog)
    assert reloaded.persistent_connection is False
    await coordinator.async_music_preference(OPT_MUSIC_PALETTE, "Tranquil")
    assert coordinator.entry.options[OPT_PERSISTENT_CONNECTION] is False
    await reloaded.async_shutdown()
