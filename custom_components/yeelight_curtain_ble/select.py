"""Separate regular presets from music effects and desired palettes."""

from homeassistant.components.select import SelectEntity

from .const import OPT_MUSIC_EFFECT, OPT_MUSIC_PALETTE
from .custom_gif import GIF_EFFECT, OPT_CUSTOM_GIFS, OPT_CUSTOM_SLOT, OPT_LAST_CUSTOM_GIF
from .entity import CurtainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [
        PresetSelect(coordinator),
        MusicSelect(coordinator, OPT_MUSIC_EFFECT, list(coordinator.catalog["music_effects"])),
        MusicSelect(coordinator, OPT_MUSIC_PALETTE, list(coordinator.catalog["palettes"])),
    ]
    if coordinator.entry.options.get(OPT_CUSTOM_GIFS):
        entities.append(CustomGIFSelect(coordinator))
    async_add_entities(entities)


class PresetSelect(CurtainEntity, SelectEntity):
    """Choose a regular animation independently of music preferences."""

    _attr_translation_key = "preset"

    def __init__(self, coordinator):
        super().__init__(coordinator, "preset")
        self._attr_options = list(coordinator.presets)

    @property
    def current_option(self):
        return self.coordinator.preset

    @property
    def icon(self):
        preset = self.coordinator.presets.get(self.current_option)
        return preset["icon"] if preset is not None else "mdi:animation-play-outline"

    async def async_select_option(self, option):
        await self.coordinator.async_light_on(None, option)


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


class CustomGIFSelect(CurtainEntity, SelectEntity):
    """Play a private GIF; the value is explicitly the last requested file."""

    _attr_translation_key = "custom_gif"
    _attr_icon = "mdi:image-multiple-outline"
    _attr_assumed_state = True

    def __init__(self, coordinator):
        super().__init__(coordinator, "custom_gif")
        self._attr_options = list(coordinator.entry.options.get(OPT_CUSTOM_GIFS, {}))

    @property
    def current_option(self):
        state = self.coordinator.data
        if (
            not state
            or state["music"].get("on")
            or state["effect"][:2] != GIF_EFFECT
            or not self.coordinator.entry.options.get(OPT_CUSTOM_SLOT)
        ):
            return None
        return self.coordinator.entry.options.get(OPT_LAST_CUSTOM_GIF)

    @property
    def extra_state_attributes(self):
        return {
            "file_identity_readable": False,
            "state_is_last_request": True,
            "last_requested": self.coordinator.entry.options.get(OPT_LAST_CUSTOM_GIF),
        }

    async def async_select_option(self, option):
        await self.coordinator.async_custom_gif(option)
