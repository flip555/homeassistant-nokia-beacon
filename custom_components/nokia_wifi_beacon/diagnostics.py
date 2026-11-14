"""Diagnostics: safe dump with credential redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return coordinator data, device map and capabilities.

    The gateway returns the Wi-Fi PSK and the WAN/PPPoE password in clear text. They are
    redacted unless the entry explicitly opts in via the ``include_credentials`` option,
    so a diagnostics download cannot leak them by default.
    """
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = runtime.get("coordinator")
    data = dict(getattr(coordinator, "data", {}) or {})
    include = bool(entry.options.get("include_credentials", False))

    wan = dict(data.get("wan") or {})
    if not include:
        if wan.get("password"):
            wan["password"] = REDACTED
    data["wan"] = wan

    reservations = data.get("reservations") or []
    devices = runtime.get("devices") or {}

    return {
        "entry": {
            "host": entry.data.get("host"),
            "username": entry.data.get("username"),
            "unique_id": entry.unique_id,
            "options": dict(entry.options),
        },
        "device": data.get("device"),
        "dhcp": data.get("dhcp"),
        "wan": wan,
        "congestion": data.get("congestion"),
        "reservation_count": len(reservations),
        "reservations": reservations,
        "tracker_count": len(devices),
        "trackers": devices,
        "credentials_included": include,
    }
