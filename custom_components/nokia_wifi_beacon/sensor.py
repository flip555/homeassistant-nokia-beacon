"""Sensors: firmware, uptime, lease pool, congestion."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import NokiaCoordinator
from .entity import NokiaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: NokiaCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            FirmwareSensor(coordinator, entry),
            UptimeSensor(coordinator, entry),
            ReservationsSensor(coordinator, entry),
            PoolUtilisationSensor(coordinator, entry),
            CongestionSensor(coordinator, entry, "1", "Congestion 2.4 GHz"),
            CongestionSensor(coordinator, entry, "2", "Congestion 5 GHz"),
            WanCredentialSensor(coordinator, entry),
        ]
    )


class FirmwareSensor(NokiaEntity, SensorEntity):
    _attr_name = "Firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "firmware")

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data.get("device") or {}).get("SoftwareVersion")


class UptimeSensor(NokiaEntity, SensorEntity):
    _attr_name = "Uptime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "uptime")

    @property
    def native_value(self) -> int | None:
        value = (self.coordinator.data.get("device") or {}).get("UpTime")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class ReservationsSensor(NokiaEntity, SensorEntity):
    _attr_name = "Reservations"
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "reservations")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("reservations") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rows = self.coordinator.data.get("reservations") or []
        return {
            "reservations": [
                {
                    "oid": row.get("oid"),
                    "mac": row.get("Chaddr"),
                    "ip": row.get("Yiaddr"),
                }
                for row in rows[:50]
            ]
        }


def _pool_size(dhcp: dict[str, Any]) -> int | None:
    def last_octet(addr: str) -> int | None:
        try:
            return int(str(addr).split(".")[-1])
        except (ValueError, IndexError):
            return None

    start = last_octet(dhcp.get("MinAddress", ""))
    end = last_octet(dhcp.get("MaxAddress", ""))
    if start is None or end is None or end < start:
        return None
    return end - start + 1


class PoolUtilisationSensor(NokiaEntity, SensorEntity):
    _attr_name = "DHCP pool utilisation"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pool_utilisation")

    @property
    def native_value(self) -> float | None:
        dhcp = self.coordinator.data.get("dhcp") or {}
        size = _pool_size(dhcp)
        used = len(self.coordinator.data.get("reservations") or [])
        if not size:
            return None
        return round(used / size * 100, 1)


class CongestionSensor(NokiaEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wifi-alert"

    def __init__(
        self,
        coordinator: NokiaCoordinator,
        entry: ConfigEntry,
        radio_oid: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry, f"congestion_{radio_oid}")
        self._oid = radio_oid
        self._attr_name = name

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data.get("congestion") or {}).get(self._oid)


class WanCredentialSensor(NokiaEntity, SensorEntity):
    """PPPoE identity, for backup purposes.

    Disabled by default: enabling it stores the ISP password in the recorder database,
    every database backup and any dashboard that exposes the attribute. Turn it on only
    if you want HA to hold that credential.
    """

    _attr_name = "WAN PPPoE credentials"
    _attr_icon = "mdi:key-chain"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "wan_credentials")

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data.get("wan_config") or {}).get("username") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self.coordinator.data.get("wan_config") or {}
        return {
            "password": cfg.get("password"),
            "has_password": bool(cfg.get("password")),
            "wan_type": cfg.get("type"),
            "connection": cfg.get("status"),
        }
