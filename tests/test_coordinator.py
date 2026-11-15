"""Exercise HA entities with a simulated Bluetooth peripheral."""

import json
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.yeelight_curtain_ble.const import DOMAIN, OPT_MUSIC_PALETTE
from custom_components.yeelight_curtain_ble.coordinator import CurtainCoordinator, load_catalog
from custom_components.yeelight_curtain_ble.light import CurtainLight
from custom_components.yeelight_curtain_ble.select import MusicSelect


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
