"""Check the optional card assets through HA's actual static route registration."""

from pathlib import Path

from aiohttp.test_utils import make_mocked_request
from homeassistant.components.http.server import (
    KEY_ALLOW_CONFIGURED_CORS,
    HomeAssistantHTTP,
    SSLProfile,
)
from homeassistant.core import HomeAssistant

from custom_components.yeelight_curtain_ble import async_setup


async def test_only_public_card_assets_are_served(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.http = HomeAssistantHTTP(
        hass, None, None, None, ["127.0.0.1"], 0, [], SSLProfile.MODERN_V4
    )
    hass.http.app[KEY_ALLOW_CONFIGURED_CORS] = lambda route: None
    assert await async_setup(hass, {})
    component = Path(__file__).parents[1] / "custom_components/yeelight_curtain_ble"
    for name, source in (
        ("yeelight-curtain-presets.js", "www/yeelight-curtain-presets.js"),
        ("catalog.json", "catalog.json"),
        ("curtain.png", "www/curtain.png"),
    ):
        request = make_mocked_request("GET", f"/yeelight_curtain_ble/{name}")
        match = await hass.http.app.router.resolve(request)
        response = await match.handler(request)
        assert response.status == 200
        assert response._path.read_bytes() == (component / source).read_bytes()
    for path in ("/yeelight_curtain_ble/client.py", "/yeelight_curtain_ble/", "/yeelight_curtain_ble/../secrets.yaml"):
        request = make_mocked_request("GET", path)
        match = await hass.http.app.router.resolve(request)
        assert match.http_exception.status == 404
