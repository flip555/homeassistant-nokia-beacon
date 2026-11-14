"""Shared base entity: one HA device for the gateway."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NokiaCoordinator


def gateway_device_info(entry: ConfigEntry, device: dict) -> DeviceInfo:
    serial = str(device.get("SerialNumber") or entry.unique_id or entry.entry_id)
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer=str(device.get("Vendor") or "Nokia"),
        model=str(device.get("ModelName") or device.get("ProductClass") or "WiFi Beacon"),
        name="Nokia WiFi",
        sw_version=str(device.get("SoftwareVersion") or ""),
        hw_version=str(device.get("HardwareVersion") or ""),
        configuration_url=f"http://{entry.data.get('host')}",
    )


class NokiaEntity(CoordinatorEntity[NokiaCoordinator]):
    """Base for coordinator-backed entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: NokiaCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return gateway_device_info(
            self._entry, (self.coordinator.data or {}).get("device", {})
        )
