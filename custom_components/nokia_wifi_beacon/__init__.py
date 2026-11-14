"""Setup, websocket loop and services."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NokiaAuthError, NokiaBeaconApi, NokiaError
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EV_ALL_DEVICES,
    EV_DEVICE_UPDATE,
    EV_NEW_DEVICE,
    WS_RECONNECT_DELAY,
)
from .coordinator import NokiaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
]

SERVICE_ADD = "add_reservation"
SERVICE_DELETE = "delete_reservation"

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("mac"): cv.string,
        vol.Required("ip"): cv.string,
        vol.Optional("entry_id"): cv.string,
    }
)
DELETE_SCHEMA = vol.Schema(
    {
        vol.Optional("mac"): cv.string,
        vol.Optional("oid"): cv.string,
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api = NokiaBeaconApi(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    try:
        await api.login()
    except NokiaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except NokiaError as err:
        raise ConfigEntryNotReady(str(err)) from err

    interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    coordinator = NokiaCoordinator(hass, api, interval)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info(
        "Nokia gateway %s connected, polling every %ss", entry.data[CONF_HOST], interval
    )

    runtime: dict[str, Any] = {
        "api": api,
        "coordinator": coordinator,
        "devices": {},
        "listeners": [],
        "task": None,
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    runtime["task"] = entry.async_create_background_task(
        hass, _ws_loop(hass, runtime), name=f"{DOMAIN}_ws_{entry.entry_id}"
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if runtime and runtime.get("task"):
            runtime["task"].cancel()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _ws_loop(hass: HomeAssistant, runtime: dict[str, Any]) -> None:
    """Keep the telemetry socket alive; it is the source of device presence."""
    api: NokiaBeaconApi = runtime["api"]
    while True:
        try:
            await api.ws_run(lambda payload: _handle_event(runtime, payload))
        except asyncio.CancelledError:
            raise
        except NokiaAuthError as err:
            _LOGGER.warning("websocket auth failed: %s", err)
        except Exception as err:  # noqa: BLE001 - keep the loop alive
            _LOGGER.debug("websocket error: %s", err)
        await asyncio.sleep(WS_RECONNECT_DELAY)


def _handle_event(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    event = payload.get("event")
    if event not in (EV_ALL_DEVICES, EV_DEVICE_UPDATE, EV_NEW_DEVICE):
        return
    devices = payload.get("payload")
    if not isinstance(devices, list):
        return

    store: dict[str, dict[str, Any]] = runtime["devices"]
    for dev in devices:
        mac = (dev.get("mac") or "").upper()
        if mac:
            store[mac] = dev

    for listener in list(runtime["listeners"]):
        try:
            listener(store)
        except Exception:  # noqa: BLE001 - a bad listener must not kill the socket
            _LOGGER.exception("device listener failed")


def _runtime_for(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    entries: dict[str, Any] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get("entry_id")
    if entry_id:
        if entry_id not in entries:
            raise ServiceValidationError(f"unknown entry_id {entry_id}")
        return entries[entry_id]
    if len(entries) == 1:
        return next(iter(entries.values()))
    if not entries:
        raise ServiceValidationError("no Nokia gateway is configured")
    raise ServiceValidationError("multiple gateways configured; pass entry_id")


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_ADD):
        return

    async def _add(call: ServiceCall) -> None:
        runtime = _runtime_for(hass, call)
        try:
            await runtime["api"].async_add_reservation(call.data["mac"], call.data["ip"])
        except NokiaError as err:
            raise ServiceValidationError(str(err)) from err
        await runtime["coordinator"].async_request_refresh()

    async def _delete(call: ServiceCall) -> None:
        runtime = _runtime_for(hass, call)
        oid = call.data.get("oid")
        if oid is None and call.data.get("mac"):
            wanted = NokiaBeaconApi.normalise_mac(call.data["mac"])
            for row in runtime["coordinator"].data.get("reservations", []):
                if str(row.get("Chaddr", "")).lower() == wanted:
                    oid = row.get("oid")
                    break
            if oid is None:
                raise ServiceValidationError(f"no reservation for {wanted}")
        if oid is None:
            raise ServiceValidationError("pass either mac or oid")
        try:
            await runtime["api"].async_delete_reservation(str(oid))
        except NokiaError as err:
            raise ServiceValidationError(str(err)) from err
        await runtime["coordinator"].async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ADD, _add, schema=ADD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DELETE, _delete, schema=DELETE_SCHEMA)
