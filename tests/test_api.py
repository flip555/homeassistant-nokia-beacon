"""Unit tests for the Nokia Beacon client (no Home Assistant required).

Run from the repository root:
    python3 -m unittest discover -s tests -v
or
    python3 -m pytest tests -q
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "nokia_wifi_beacon"

# Load const.py and api.py as a synthetic package so the integration's
# __init__.py is not executed — it imports Home Assistant and voluptuous,
# neither of which the unit tests need.
_pkg = types.ModuleType("nokia_beacon_test")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["nokia_beacon_test"] = _pkg
for _name in ("const", "api"):
    _spec = importlib.util.spec_from_file_location(
        f"nokia_beacon_test.{_name}", PKG_DIR / f"{_name}.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"nokia_beacon_test.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

from nokia_beacon_test.api import NokiaBeaconApi, NokiaError  # noqa: E402


def _api() -> NokiaBeaconApi:
    return NokiaBeaconApi(MagicMock(), "gateway", "admin", "pw")


class TestNormaliseMac(unittest.TestCase):
    def test_uppercase_colons(self):
        self.assertEqual(
            NokiaBeaconApi.normalise_mac("AA:BB:CC:DD:EE:01"), "aa:bb:cc:dd:ee:01"
        )

    def test_dashes_and_whitespace(self):
        self.assertEqual(
            NokiaBeaconApi.normalise_mac("  aa-bb-cc-dd-ee-01 "), "aa:bb:cc:dd:ee:01"
        )

    def test_already_normal(self):
        self.assertEqual(
            NokiaBeaconApi.normalise_mac("aa:bb:cc:dd:ee:01"), "aa:bb:cc:dd:ee:01"
        )


class TestReservationPayloads(unittest.IsolatedAsyncioTestCase):
    async def test_add_sends_bootp_names(self):
        api = _api()
        api.post = AsyncMock(return_value={"result": 0, "reason": 0})

        await api.async_add_reservation("AA:BB:CC:DD:EE:01", "192.168.1.127")

        api.post.assert_awaited_once_with(
            "lan_ipv4_app.cgi",
            {
                "act": "Add",
                "bindmac": "aa:bb:cc:dd:ee:01",
                "bindip": "192.168.1.127",
                "oid": "0",
            },
        )

    async def test_delete_sends_oid(self):
        api = _api()
        api.post = AsyncMock(return_value={"result": 0, "reason": 0})

        await api.async_delete_reservation("29")

        api.post.assert_awaited_once_with(
            "lan_ipv4_app.cgi", {"act": "Del", "oid": "29"}
        )

    async def test_add_rejection_raises(self):
        api = _api()
        api.post = AsyncMock(return_value={"result": 1, "reason": 1})

        with self.assertRaises(NokiaError):
            await api.async_add_reservation("aa:bb:cc:dd:ee:ff", "192.168.1.9")

    async def test_delete_rejection_raises(self):
        api = _api()
        api.post = AsyncMock(return_value={"result": -1, "reason": 403})

        with self.assertRaises(NokiaError):
            await api.async_delete_reservation("1")


class TestReservationParsing(unittest.IsolatedAsyncioTestCase):
    async def test_reservations_extracted(self):
        api = _api()
        api.get = AsyncMock(
            return_value={
                "dhcp_status": {"MinAddress": "192.168.1.2"},
                "bind_mac": [
                    {"oid": "1", "Chaddr": "aa:bb:cc:dd:ee:ff", "Yiaddr": "192.168.1.30"}
                ],
            }
        )

        rows = await api.async_reservations()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Yiaddr"], "192.168.1.30")

    async def test_missing_bind_mac_is_empty(self):
        api = _api()
        api.get = AsyncMock(return_value={"dhcp_status": {}})

        self.assertEqual(await api.async_reservations(), [])


class TestWebsocketCredentials(unittest.TestCase):
    def test_base64_frame_matches_app(self):
        import base64

        api = _api()
        expected = base64.b64encode(f"{api.username}:{api.password}".encode()).decode()
        self.assertEqual(expected, base64.b64encode(b"admin:pw").decode())


if __name__ == "__main__":
    unittest.main()
