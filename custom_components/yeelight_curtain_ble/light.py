"""Power, brightness and recorded regular effects."""

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from .entity import CurtainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CurtainLight(entry.runtime_data)])


class CurtainLight(CurtainEntity, LightEntity):
    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
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
        return self.coordinator.preset

    async def async_turn_on(self, **kwargs):
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness == 0:
            await self.coordinator.async_power(False)
            return
        percent = None if brightness is None else max(1, min(100, round(brightness * 100 / 255)))
        await self.coordinator.async_light_on(percent, kwargs.get(ATTR_EFFECT))

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_power(False)
