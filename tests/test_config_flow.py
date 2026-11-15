"""Discovery, connection validation and errors in real HA config flow classes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.yeelight_curtain_ble.client import CurtainError
from custom_components.yeelight_curtain_ble.config_flow import CurtainConfigFlow


@pytest.fixture
async def flow(tmp_path):
    flow = CurtainConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow.context = {"source": "user"}
    flow._async_current_ids = MagicMock(return_value=set())
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


def discovery():
    return SimpleNamespace(address="AA:BB:CC:DD:EE:01", name="YLBT_CURT_TEST", connectable=True)


async def test_manual_flow_lists_discovered_connectable_device(flow):
    with patch(
        "custom_components.yeelight_curtain_ble.config_flow.bluetooth.async_discovered_service_info",
        return_value=[discovery()],
    ):
        result = await flow.async_step_user()
    assert result["type"] == "form" and result["step_id"] == "user"
    assert discovery().address in flow._devices


async def test_discovery_requires_confirm_and_read(flow):
    result = await flow.async_step_bluetooth(discovery())
    assert result["type"] == "form" and result["step_id"] == "confirm"
    flow._validate = AsyncMock()
    result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    assert result["data"]["address"] == discovery().address
    flow._validate.assert_awaited_once_with(discovery().address)


async def test_failed_read_keeps_flow_open(flow):
    await flow.async_step_bluetooth(discovery())
    flow._validate = AsyncMock(side_effect=CurtainError("unreachable"))
    result = await flow.async_step_confirm({})
    assert result["type"] == "form" and result["errors"] == {"base": "cannot_connect"}


async def test_no_device_shows_explanation(flow):
    with patch(
        "custom_components.yeelight_curtain_ble.config_flow.bluetooth.async_discovered_service_info",
        return_value=[],
    ):
        result = await flow.async_step_user()
    assert result["type"] == "abort" and result["reason"] == "no_devices_found"


async def test_non_connectable_device_rejected(flow):
    info = discovery()
    info.connectable = False
    result = await flow.async_step_bluetooth(info)
    assert result["type"] == "abort" and result["reason"] == "not_supported"
