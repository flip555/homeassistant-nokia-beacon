"""WAN link state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import NokiaCoordinator
from .entity import NokiaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: NokiaCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([WanSensor(coordinator, entry)])


class WanSensor(NokiaEntity, BinarySensorEntity):
    _attr_name = "WAN"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: NokiaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "wan")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("wan_up"))
