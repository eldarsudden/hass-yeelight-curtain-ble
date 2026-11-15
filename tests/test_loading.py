"""Load the actual custom component through HA's loader and test proxy routing."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import loader
from homeassistant.core import HomeAssistant

from custom_components.yeelight_curtain_ble.const import DOMAIN
from custom_components.yeelight_curtain_ble.coordinator import connect


def test_hacs_installation_metadata_and_brand():
    root = Path(__file__).parents[1]
    component = root / "custom_components" / DOMAIN
    manifest = json.loads((component / "manifest.json").read_text())
    assert manifest["iot_class"] in {"local_polling", "local_push"}
    assert manifest["documentation"].startswith("https://github.com/")
    assert manifest["issue_tracker"] == manifest["documentation"] + "/issues"
    assert manifest["codeowners"]
    assert manifest["bluetooth"] == [{"local_name": "YLBT_CURT_*", "connectable": True}]
    hacs = json.loads((root / "hacs.json").read_text())
    assert hacs["name"] == manifest["name"] and not hacs["content_in_root"]
    assert (component / "brand/icon.png").is_file()


async def test_home_assistant_loads_manifest_and_platforms():
    hass = HomeAssistant(str(Path(__file__).parents[1]))
    loader.async_setup(hass)
    integration = await loader.async_get_integration(hass, DOMAIN)
    assert integration.version == "0.1.0"
    assert integration.dependencies == ["bluetooth"]
    assert await integration.async_get_component()
    for platform in ("config_flow", "light", "switch", "select"):
        assert await integration.async_get_platform(platform)


async def test_connection_uses_ha_selected_connectable_device():
    hass = object()
    device = SimpleNamespace(name="YLBT_CURT_TEST")
    established = AsyncMock(return_value="connected")

    def disconnected(_client):
        return None

    with (
        patch(
            "custom_components.yeelight_curtain_ble.coordinator.bluetooth.async_ble_device_from_address",
            return_value=device,
        ) as lookup,
        patch(
            "custom_components.yeelight_curtain_ble.coordinator.establish_connection", established
        ),
    ):
        assert await connect(hass, "AA:BB:CC:DD:EE:01", disconnected) == "connected"
        lookup.assert_called_once_with(hass, "AA:BB:CC:DD:EE:01", connectable=True)
        assert established.call_args.args[1] is device
        assert established.call_args.kwargs["disconnected_callback"] is disconnected
        assert established.call_args.kwargs["ble_device_callback"]() is device
