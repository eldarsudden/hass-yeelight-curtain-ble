"""Device microphone music mode."""

from homeassistant.components.switch import SwitchEntity

from .entity import CurtainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MusicSwitch(entry.runtime_data)])


class MusicSwitch(CurtainEntity, SwitchEntity):
    _attr_translation_key = "music_mode"
    _attr_icon = "mdi:music"

    def __init__(self, coordinator):
        super().__init__(coordinator, "music_mode")

    @property
    def is_on(self):
        return bool(self.coordinator.data["music"].get("on"))

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_music(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_music(False)
