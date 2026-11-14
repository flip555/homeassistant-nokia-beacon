"""Nokia Beacon client: legacy CGI over HTTP plus the :8099 websocket."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Awaitable, Callable

import aiohttp

from .const import (
    EP_DEVICE_STATUS,
    EP_DHCP_STATUS,
    EP_LAN_IPV4,
    EP_LOGIN,
    EP_WS_SESSION,
    REQUEST_TIMEOUT,
    WS_PORT,
    WS_SESSION_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class NokiaError(Exception):
    """Generic transport/protocol error."""


class NokiaAuthError(NokiaError):
    """Credentials rejected or session could not be established."""


class NokiaBeaconApi:
    """Minimal client for the CGI family and the telemetry websocket."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self.host = host
        self.username = username
        self.password = password
        self.sid: str | None = None
        self.lsid: str | None = None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ auth

    async def login(self) -> None:
        """Authenticate and store the session ids. Raises NokiaAuthError."""
        async with self._login_lock:
            url = f"http://{self.host}/{EP_LOGIN}"
            data = {"name": self.username, "pswd": self.password, "srip": ""}
            try:
                async with self._session.post(
                    url, data=data, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                ) as resp:
                    text = await resp.text()
            except aiohttp.ClientError as err:
                raise NokiaError(f"login request failed: {err}") from err

            try:
                payload = json.loads(text)
            except ValueError as err:
                raise NokiaAuthError("login returned non-JSON (wrong host?)") from err

            if payload.get("result") != 0:
                raise NokiaAuthError(
                    f"login rejected: result={payload.get('result')} reason={payload.get('reason')}"
                )

            cookie = payload.get("cookie") or {}
            sid = cookie.get("sid") or ""
            lsid = cookie.get("lsid") or ""
            if not sid:
                raise NokiaAuthError("login succeeded but no session id was returned")

            self.sid = sid.split("=", 1)[-1]
            self.lsid = lsid.split("=", 1)[-1]
            _LOGGER.debug("authenticated with %s", self.host)

    def _cookie_header(self) -> dict[str, str]:
        return {"Cookie": f"lang=eng; sid={self.sid}; lsid={self.lsid}"}

    # --------------------------------------------------------------- request

    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        if self.sid is None:
            await self.login()

        url = f"http://{self.host}/{path}"
        headers = self._cookie_header()
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308) or resp.status == 403:
                    # 302 usually means the session expired; 403 shows up when another
                    # admin login (the router UI, or a stray curl) evicted ours.
                    # Both are recoverable exactly once by re-authenticating.
                    if retry:
                        _LOGGER.debug(
                            "%s returned %s, re-authenticating", path, resp.status
                        )
                        self.sid = None
                        await self.login()
                        return await self._request(method, path, data, retry=False)
                    raise NokiaAuthError(
                        f"{path} returned {resp.status} after re-login"
                    )
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise NokiaError(f"{method} {path} failed: {err}") from err

        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise NokiaError(f"{path} returned non-JSON: {text[:80]!r}") from None

    async def get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, data)

    # ------------------------------------------------------------ typed reads

    async def async_device_info(self) -> dict[str, Any]:
        return await self.get(EP_DEVICE_STATUS)

    async def async_dhcp(self) -> dict[str, Any]:
        return await self.get(EP_DHCP_STATUS)

    async def async_capabilities(self) -> dict[str, Any]:
        from .const import EP_CAPABILITIES

        return await self.get(EP_CAPABILITIES)

    # ----------------------------------------------------- reservations CRUD

    @staticmethod
    def normalise_mac(mac: str) -> str:
        return mac.strip().lower().replace("-", ":")

    async def async_add_reservation(self, mac: str, ip: str) -> None:
        result = await self.post(
            EP_LAN_IPV4,
            {"act": "Add", "bindmac": self.normalise_mac(mac), "bindip": ip, "oid": "0"},
        )
        if result.get("result") != 0:
            raise NokiaError(f"add_reservation failed: {result}")

    async def async_delete_reservation(self, oid: str) -> None:
        result = await self.post(EP_LAN_IPV4, {"act": "Del", "oid": str(oid)})
        if result.get("result") != 0:
            raise NokiaError(f"delete_reservation failed: {result}")

    async def async_reservations(self) -> list[dict[str, Any]]:
        data = await self.async_dhcp()
        return (data or {}).get("bind_mac") or []

    # ------------------------------------------------------------- websocket

    async def ws_run(
        self,
        on_event: Callable[[dict[str, Any]], Awaitable[None] | None],
    ) -> None:
        """Connect, authenticate and pump events until the socket closes."""
        if self.sid is None:
            await self.login()

        url = f"ws://{self.host}:{WS_PORT}"
        headers = {
            **self._cookie_header(),
            "Origin": f"http://{self.host}",
        }
        async with self._session.ws_connect(
            url, headers=headers, heartbeat=30, timeout=REQUEST_TIMEOUT
        ) as ws:
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            await ws.send_str(creds)

            first = await ws.receive(timeout=REQUEST_TIMEOUT)
            if first.type is not aiohttp.WSMsgType.TEXT or first.data != "200 OK":
                raise NokiaAuthError(
                    f"websocket auth rejected: {getattr(first, 'data', first.type)!r}"
                )

            await self.post(
                EP_WS_SESSION,
                {"command": "Session_START{Mobile}", "timeout": WS_SESSION_TIMEOUT},
            )
            _LOGGER.debug("websocket session started on %s", self.host)

            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except ValueError:
                        continue
                    result = on_event(payload)
                    if asyncio.iscoroutine(result):
                        await result
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
