"""Exercise HA entities with a simulated Bluetooth peripheral."""

import json
from pathlib import Path
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
    preset, music_effect, music_palette, mounting = add_entities.call_args.args[0]
    assert isinstance(preset, PresetSelect)
    assert len(preset.options) == 19 and "Christmas Tree" in preset.options
    assert "Sound Wave" not in preset.options
    assert music_effect.options == list(coordinator.catalog["music_effects"])
    assert music_palette.options == list(coordinator.catalog["palettes"])
    assert preset.unique_id != music_effect.unique_id != music_palette.unique_id
    assert mounting.current_option == "right"


async def test_select_regular_preset_exits_music_without_changing_music_preferences(
    coordinator, peripheral
):
    preset = PresetSelect(coordinator)
    light = CurtainLight(coordinator)
    await coordinator.async_music_preference(OPT_MUSIC_EFFECT, "Shine")
    await coordinator.async_music(True)
    assert preset.current_option is None and light.effect == "Music mode"
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


async def test_custom_gif_upload_activation_and_identity_are_separate(coordinator, peripheral):
    from custom_components.yeelight_curtain_ble.custom_gif import (
        OPT_CUSTOM_GIFS,
        OPT_LAST_CUSTOM_GIF,
        gif_path,
        validate_gif,
    )
    from custom_components.yeelight_curtain_ble.select import CustomGIFSelect

    data = (Path(__file__).parents[1] / 'custom_components/yeelight_curtain_ble/presets/christmasTree.gif').read_bytes()
    metadata = {"name": "My animation", **validate_gif(data)}
    path = gif_path(coordinator.hass, coordinator.entry.entry_id, metadata["sha256"])
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    object.__setattr__(coordinator.entry, "options", MappingProxyType({OPT_CUSTOM_GIFS: {"My animation": metadata}}))
    coordinator.persistent_connection = False
    await coordinator.async_music(True)
    entity = CustomGIFSelect(coordinator)
    assert entity.options == ["My animation"] and entity.current_option is None
    await entity.async_select_option("My animation")
    assert entity.current_option == "My animation"
    assert entity.assumed_state and entity.extra_state_attributes["file_identity_readable"] is False
    assert coordinator.data["power"] == "on" and coordinator.data["music"]["on"] == 0
    assert coordinator.preset is None  # Never mislabel a custom upload as Christmas Tree.
    assert not peripheral.is_connected
    assert peripheral.file_packets[-1] == b"\x04"
    assert coordinator.entry.options[OPT_LAST_CUSTOM_GIF] == "My animation"
    light = CurtainLight(coordinator)
    assert light.effect == "Custom GIF" and light.state_attributes["brightness"] is not None
    await light.async_turn_on(hs_color=(202, 100))
    assert light.hs_color == (202, 100) and entity.current_option is None
    await coordinator.async_light_on(None, "Christmas Tree")
    assert coordinator.preset == "Christmas Tree"
    assert entity.current_option is None  # Allow selecting the same GIF again after a preset.
    assert entity.extra_state_attributes["last_requested"] == "My animation"
    path.write_bytes(data[:-1])
    before = len(peripheral.requests)
    with pytest.raises(HomeAssistantError, match="Cannot read custom GIF"):
        await entity.async_select_option("My animation")
    assert len(peripheral.requests) == before  # Validation precedes every BLE command.


async def test_failed_custom_transfer_never_activates_or_updates_last_request(coordinator, peripheral):
    from custom_components.yeelight_curtain_ble.custom_gif import (
        OPT_CUSTOM_GIFS,
        OPT_LAST_CUSTOM_GIF,
    )

    object.__setattr__(coordinator.entry, "options", MappingProxyType({OPT_CUSTOM_GIFS: {"New": {"sha256": "a" * 64}}, OPT_LAST_CUSTOM_GIF: "Old"}))
    coordinator.client.upload = AsyncMock(side_effect=TimeoutError())
    with patch("custom_components.yeelight_curtain_ble.coordinator.read_custom_gif", return_value=b"GIF89a;"):
        with pytest.raises(HomeAssistantError):
            await coordinator.async_custom_gif("New")
    assert not any(r["method"] == "set_fx_effect" for r in peripheral.requests)
    assert coordinator.entry.options[OPT_LAST_CUSTOM_GIF] == "Old"
    assert not peripheral.is_connected


async def test_native_color_picker_and_brightness_between_modes(coordinator, peripheral):
    from homeassistant.components.light import ColorMode

    light = CurtainLight(coordinator)
    assert light.supported_color_modes == {ColorMode.HS}
    assert light.color_mode == ColorMode.BRIGHTNESS
    await light.async_turn_on()
    assert light.state_attributes["brightness"] is not None
    await coordinator.async_music(True)
    await light.async_turn_on(hs_color=(120, 100), brightness=128)
    assert light.color_mode == ColorMode.HS
    assert light.hs_color == (120, 100) and light.effect is None
    assert coordinator.data["bright"] == 50 and coordinator.data["music"]["on"] == 0
    assert light.state_attributes["hs_color"] == (120, 100)
    assert light.state_attributes["rgb_color"] == (0, 255, 0)
    assert not peripheral.file_packets
    hsv_writes = len([r for r in peripheral.requests if r["method"] == "set_hsv"])
    await light.async_turn_on(brightness=64)
    assert coordinator.data["bright"] == 25 and light.hs_color == (120, 100)
    assert len([r for r in peripheral.requests if r["method"] == "set_hsv"]) == hsv_writes
    await light.async_turn_on(effect="Rainbow")
    assert light.effect == "Rainbow" and light.hs_color is None
    assert light.color_mode == ColorMode.BRIGHTNESS
    assert light.state_attributes["brightness"] is not None
    await coordinator.async_music(True)
    assert light.effect == "Music mode"
    assert light.state_attributes["brightness"] is not None
    assert "Music mode" not in light.effect_list and len(light.effect_list) == 19
    coordinator.persistent_connection = False
    await light.async_turn_on(hs_color=(360, 0))
    assert light.hs_color == (0, 0) and not peripheral.is_connected


async def test_external_color_notifications_and_malformed_values(coordinator):
    light = CurtainLight(coordinator)
    coordinator._props({"color_mode": 3, "hue": 296, "sat": 100, "fx_effect": '{"effect_id":0,"custom_id":0}', "mic_music_mode": '{"on":0}'})
    assert light.hs_color == (296, 100)
    coordinator._props({"hue": "233"})
    assert light.hs_color == (233, 100)
    coordinator._props({"hue": "999"})
    assert light.hs_color == (233, 100)
    coordinator._props({"hue": True})
    assert light.hs_color == (233, 100)
    coordinator._props({"color_mode": 14, "fx_effect": '{"effect_id":39,"custom_id":0}'})
    assert light.hs_color is None and "hs_color" not in coordinator.data


async def test_color_ack_requires_matching_readback(coordinator):
    coordinator.client.set = AsyncMock()
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await CurtainLight(coordinator).async_turn_on(hs_color=(120, 100))
    assert "hs_color" not in coordinator.data


@pytest.mark.parametrize("color,effect", [((float('nan'), 50), None), ((0, 101), None), ((-1, 100), None), ((True, 50), None), ((0, 50), "Rainbow")])
async def test_bad_color_requests_send_no_commands(coordinator, peripheral, color, effect):
    before = len(peripheral.requests)
    with pytest.raises(HomeAssistantError):
        await coordinator.async_light_on(None, effect, color)
    assert len(peripheral.requests) == before


async def test_mounting_entity_repairs_reset_entry_and_preserves_preferences(coordinator, peripheral):
    from homeassistant.const import EntityCategory

    from custom_components.yeelight_curtain_ble.select import MountingSideSelect

    mounting = MountingSideSelect(coordinator)
    assert mounting.entity_category == EntityCategory.CONFIG
    assert mounting.current_option == "right"
    await coordinator.async_music_preference(OPT_MUSIC_PALETTE, "Tranquil")
    peripheral.adapter_set, peripheral.adapter_side = 0, 0
    await coordinator.async_refresh()
    assert mounting.current_option is None
    coordinator.persistent_connection = False
    await mounting.async_select_option("left")
    assert mounting.current_option == "left" and not peripheral.is_connected
    assert coordinator.entry.options[OPT_MUSIC_PALETTE] == "Tranquil"
    assert peripheral.power == "off" and peripheral.bright == 9
    coordinator._props({"adapter_set": 1, "adapter_side": 1})
    assert mounting.current_option == "right"
    coordinator._props({"adapter_set": 0, "adapter_side": 0})
    assert mounting.current_option is None
    before = len(peripheral.requests)
    with pytest.raises(HomeAssistantError, match="Unknown mounting"):
        await mounting.async_select_option("middle")
    assert len(peripheral.requests) == before
