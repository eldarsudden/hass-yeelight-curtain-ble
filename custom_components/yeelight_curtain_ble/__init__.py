"""Local Yeelight Curtain BLE integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import CurtainCoordinator, load_catalog
from .custom_gif import OPT_CUSTOM_GIFS, cleanup_library
from .frontend import async_setup_frontend

PLATFORMS = [Platform.LIGHT, Platform.SWITCH, Platform.SELECT]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the local optional card and curtain entity picture once."""
    await async_setup_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.async_add_executor_job(
        cleanup_library, hass, entry.entry_id, entry.options.get(OPT_CUSTOM_GIFS, {})
    )
    catalog = await hass.async_add_executor_job(load_catalog)
    coordinator = CurtainCoordinator(hass, entry, catalog)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unload_ok
