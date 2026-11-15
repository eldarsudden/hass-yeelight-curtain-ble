"""Power, brightness and recorded regular effects."""

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from .custom_gif import GIF_EFFECT, OPT_CUSTOM_SLOT
from .entity import CurtainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CurtainLight(entry.runtime_data)])


class CurtainLight(CurtainEntity, LightEntity):
    _attr_name = None
    _attr_entity_picture = "/yeelight_curtain_ble/curtain.png"
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, coordinator):
        super().__init__(coordinator, "light")
        self._attr_effect_list = list(coordinator.presets)

    @property
    def is_on(self):
        return self.coordinator.data["power"] == "on"

    @property
    def brightness(self):
        return round(self.coordinator.data["bright"] * 255 / 100)

    @property
    def effect(self):
        if preset := self.coordinator.preset:
            return preset
        state = self.coordinator.data
        if state["music"].get("on"):
            return "Music mode"
        if state.get("color_mode") == 3 and state["effect"][:2] == [0, 0]:
            return None
        # These are observed mode labels, never additional selectable regular presets.
        if self.coordinator.entry.options.get(OPT_CUSTOM_SLOT) and state["effect"][:2] == GIF_EFFECT:
            return "Custom GIF"
        return "Unknown effect"

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS if self.effect is not None else ColorMode.HS

    @property
    def hs_color(self):
        if self.color_mode == ColorMode.HS:
            return self.coordinator.data.get("hs_color")
        return None

    async def async_turn_on(self, **kwargs):
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness == 0:
            await self.coordinator.async_power(False)
            return
        percent = None if brightness is None else max(1, min(100, round(brightness * 100 / 255)))
        await self.coordinator.async_light_on(percent, kwargs.get(ATTR_EFFECT), kwargs.get(ATTR_HS_COLOR))

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_power(False)
