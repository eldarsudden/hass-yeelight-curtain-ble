"""Common identity and availability for curtain entities."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CurtainCoordinator


class CurtainEntity(CoordinatorEntity[CurtainCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CurtainCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="Yeelight",
            model="YLYDD-0053",
            name=coordinator.entry.title,
        )
