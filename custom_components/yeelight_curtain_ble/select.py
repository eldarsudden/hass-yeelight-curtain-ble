"""Rhythm effect and desired palette selection."""

from homeassistant.components.select import SelectEntity

from .const import OPT_MUSIC_EFFECT, OPT_MUSIC_PALETTE
from .entity import CurtainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MusicSelect(coordinator, OPT_MUSIC_EFFECT, list(coordinator.catalog["music_effects"])),
            MusicSelect(coordinator, OPT_MUSIC_PALETTE, list(coordinator.catalog["palettes"])),
        ]
    )


class MusicSelect(CurtainEntity, SelectEntity):
    def __init__(self, coordinator, key, options):
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key
        self._attr_options = options

    @property
    def current_option(self):
        if self._key == OPT_MUSIC_EFFECT:
            return self.coordinator.music_effect
        return self.coordinator.music_palette

    async def async_select_option(self, option):
        await self.coordinator.async_music_preference(self._key, option)
