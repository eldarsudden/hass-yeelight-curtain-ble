"""Serve the optional presets card and its public assets locally."""

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_ROOT = Path(__file__).parent
URL_BASE = f"/{DOMAIN}"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Expose only the public files used by the presets card and light picture."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"{URL_BASE}/yeelight-curtain-presets.js",
                str(_ROOT / "www/yeelight-curtain-presets.js"),
                cache_headers=True,
            ),
            StaticPathConfig(
                f"{URL_BASE}/catalog.json", str(_ROOT / "catalog.json"), cache_headers=True
            ),
            StaticPathConfig(
                f"{URL_BASE}/curtain.png", str(_ROOT / "www/curtain.png"), cache_headers=True
            ),
        ]
    )
