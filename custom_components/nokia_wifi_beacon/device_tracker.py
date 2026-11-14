"""Device trackers fed by the :8099 websocket.

The gateway pushes AllDeviceInfo / DeviceStatusUpdate; each client MAC becomes a tracker.
Presence is the device's ``active`` flag.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import gateway_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: dict[str, Any] = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    created: dict[str, NokiaTracker] = {}

    def add(devices: dict[str, dict[str, Any]]) -> None:
        new_entities: list[NokiaTracker] = []
        for mac, info in devices.items():
            entity = created.get(mac)
            if entity is None:
                entity = NokiaTracker(entry, coordinator, mac, info)
                created[mac] = entity
                new_entities.append(entity)
            else:
                entity.update_info(info)
                entity.async_write_ha_state()
        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

    runtime["listeners"].append(add)

    # seed with whatever the socket already delivered before this platform loaded
    if runtime["devices"]:
        add(dict(runtime["devices"]))


class NokiaTracker(TrackerEntity):
    """One client, as seen by the gateway."""

    _attr_has_entity_name = False
    _attr_source_type = SourceType.ROUTER

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator,
        mac: str,
        info: dict[str, Any],
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._mac = mac
        self._info = info
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{mac.lower()}"
        self._attr_name = self._display_name(info, mac)

    @staticmethod
    def _display_name(info: dict[str, Any], mac: str) -> str:
        for key in ("friendlyname", "host", "name"):
            value = str(info.get(key) or "").strip()
            if value and value.upper() != mac:
                return value
        return mac

    @callback
    def update_info(self, info: dict[str, Any]) -> None:
        self._info = info
        new_name = self._display_name(info, self._mac)
        if new_name != self._attr_name:
            self._attr_name = new_name

    @property
    def device_info(self) -> DeviceInfo:
        return gateway_device_info(
            self._entry, (self._coordinator.data or {}).get("device", {})
        )

    @property
    def is_connected(self) -> bool:
        return str(self._info.get("active", "0")) == "1"

    @property
    def state(self) -> str:
        """Presence, straight from the gateway's ``active`` flag.

        TrackerEntity does not derive state from ``is_connected`` on current HA
        releases — it treats the entity as a position tracker and returns unknown
        without lat/lon. Overriding ``state`` is the supported way for router-type
        trackers.
        """
        return STATE_HOME if self.is_connected else STATE_NOT_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        def rate(key: str) -> int | None:
            try:
                return int(self._info.get(key))
            except (TypeError, ValueError):
                return None

        return {
            "nokia": True,
            "mac": self._mac,
            "ip": self._info.get("ip"),
            "interface": self._info.get("interface"),
            "tx_rate": rate("txPhyRate"),
            "rx_rate": rate("rxPhyRate"),
            "is_beacon": self._info.get("isBeacon"),
        }
