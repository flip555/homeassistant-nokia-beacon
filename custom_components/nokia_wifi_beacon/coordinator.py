"""Coordinator: the HTTP snapshot (config, leases, WAN, congestion)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NokiaBeaconApi, NokiaAuthError, NokiaError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, EP_CONGESTION, EP_DHCP_STATUS, EP_DEVICE_STATUS, EP_WAN_LIST, EP_WAN_STATUS

_LOGGER = logging.getLogger(__name__)


class NokiaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the handful of CGIs that carry static/periodic state."""

    def __init__(
        self, hass: HomeAssistant, api: NokiaBeaconApi, interval: int | None = None
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval or DEFAULT_SCAN_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            device = await self.api.get(EP_DEVICE_STATUS)
            dhcp = await self.api.get(EP_DHCP_STATUS)
            wan = await self.api.get(EP_WAN_STATUS)
            wan_cfg = await self.api.get(EP_WAN_LIST)
            congestion = await self.api.get(EP_CONGESTION)
        except NokiaAuthError as err:
            raise UpdateFailed(f"authentication lost: {err}") from err
        except NokiaError as err:
            raise UpdateFailed(str(err)) from err

        status = (dhcp or {}).get("dhcp_status") or {}
        reservations = (dhcp or {}).get("bind_mac") or []

        creds = _parse_wan(wan_cfg)
        if creds.get("username") or creds.get("password"):
            await self.hass.async_add_executor_job(self._persist_credentials, creds)

        return {
            "device": device or {},
            "dhcp": status,
            "reservations": reservations,
            "wan_up": (wan or {}).get("gwwanup") == 1,
            "wan_config": creds,
            "congestion": _parse_congestion(congestion),
        }

    def _persist_credentials(self, creds: dict[str, str]) -> None:
        """Keep a durable copy of the PPPoE identity under .storage.

        Recorder state is purged on a schedule and only written when a value changes, so
        an attribute is not a backup. Home Assistant backups include .storage, which makes
        this file the reliable copy if the gateway is ever lost.
        """
        path = self.hass.config.path(
            ".storage", "nokia_wifi_beacon_wan_credentials.json"
        )
        payload = {
            "host": self.api.host,
            "username": creds.get("username", ""),
            "password": creds.get("password", ""),
            "wan_type": creds.get("type", ""),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(path) as fh:
                existing = json.load(fh)
        except (OSError, ValueError):
            existing = {}

        if existing.get("username") == payload["username"] and existing.get(
            "password"
        ) == payload["password"]:
            return

        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(payload, fh, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            _LOGGER.info("stored WAN credentials for %s in .storage", self.api.host)
        except OSError as err:
            _LOGGER.warning("could not persist WAN credentials: %s", err)


def _parse_wan(payload: Any) -> dict[str, str]:
    """Pull the PPPoE identity out of wan_list_app.cgi.

    The gateway returns the ISP password in clear text. It is only surfaced by the
    opt-in credential sensor and by diagnostics with an explicit option.
    """
    entries = (payload or {}).get("wan_list") or []
    if not entries:
        return {}
    first = entries[0] or {}
    return {
        "username": str(first.get("Username") or ""),
        "password": str(first.get("Password") or ""),
        "type": str(first.get("type") or ""),
        "status": str(first.get("ConnectionStatus") or ""),
    }


def _parse_congestion(payload: Any) -> dict[str, int]:
    """Extract per-radio congestion levels.

    Observed shape: {"OptimizationResult": {"RadioList": [{"oid": 1, "CongestionLevel": 68}, ...]}}
    The exact wrapper varies by firmware, so search for any dict carrying both keys.
    """
    found: dict[str, int] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "CongestionLevel" in node and "oid" in node:
                oid = str(node["oid"])
                try:
                    found[oid] = int(node["CongestionLevel"])
                except (TypeError, ValueError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found
