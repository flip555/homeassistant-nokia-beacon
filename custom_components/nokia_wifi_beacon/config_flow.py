"""Config, reconfigure and reauth flows."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NokiaAuthError, NokiaBeaconApi, NokiaError
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DEFAULT_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Try a login and a device read. Returns (info, error_key)."""
    session = async_get_clientsession(hass)
    api = NokiaBeaconApi(
        session, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    try:
        await api.login()
        info = await api.async_device_info()
    except NokiaAuthError:
        return None, "invalid_auth"
    except NokiaError:
        return None, "cannot_connect"
    except Exception:  # noqa: BLE001 - surfaced to the user as a generic failure
        _LOGGER.exception("unexpected error validating Nokia gateway")
        return None, "unknown"

    if not info or not info.get("SerialNumber"):
        return None, "not_nokia"
    return info, None


def _schema(host: str, username: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_USERNAME, default=username): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


class NokiaBeaconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a gateway, then re-point or re-credential it later."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await _validate(self.hass, user_input)
            if info:
                await self.async_set_unique_id(str(info["SerialNumber"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Nokia {info.get('ModelName', 'WiFi')}", data=user_input
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(DEFAULT_HOST, "admin"),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, admin username or admin password."""
        entry: ConfigEntry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await _validate(self.hass, user_input)
            if info:
                await self.async_set_unique_id(str(info["SerialNumber"]))
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(
                entry.data.get(CONF_HOST, DEFAULT_HOST),
                entry.data.get(CONF_USERNAME, "admin"),
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry: ConfigEntry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            info, error = await _validate(self.hass, data)
            if info:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"host": entry.data.get(CONF_HOST, "")},
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NokiaOptionsFlow()


class NokiaOptionsFlow(OptionsFlow):
    """Scan interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        from .const import DEFAULT_SCAN_INTERVAL, MIN_SCAN_INTERVAL

        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("scan_interval", default=current): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=600)
                    ),
                    vol.Optional(
                        "include_credentials",
                        default=self.config_entry.options.get(
                            "include_credentials", False
                        ),
                    ): bool,
                }
            ),
        )
