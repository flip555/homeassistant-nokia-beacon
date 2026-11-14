#!/usr/bin/env python3
"""nokia-spa — one-shot administrative actions for Nokia WiFi gateways.

The gateway allows a single admin session. While this tool is logged in, the Home
Assistant integration is logged out; it re-authenticates on its next poll. Use it
for one-off actions, not in a loop.

Writes are dry-run by default. Add --commit to actually send them.

    nokia-spa status
    nokia-spa optimize --commit
    nokia-spa raw --path "wlan_config_web_app.cgi?setwifi" --data "..."

Requires: cryptography  (pip install cryptography)

Credentials come from --host/--user/--password, or the NOKIA_HOST, NOKIA_USER and
NOKIA_PASSWORD environment variables, or a prompt.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

try:
    from cryptography.hazmat.primitives import padding, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    sys.exit("this tool needs 'cryptography': pip install cryptography")

HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "text/html",
    "Accept": "application/json, text/plain, */*",
}
HEADERS_FORM = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/plain, */*",
}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def _escape(value: str) -> str:
    """The gateway uses '.' instead of '=' as base64 padding."""
    return value.replace("+", "-").replace("/", "_").replace("=", ".")


def _request(opener, url, *, data=None, headers=None):
    headers = dict(headers or {})
    parts = urllib.parse.urlsplit(url)
    headers.setdefault("Referer", f"{parts.scheme}://{parts.netloc}/")
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    return opener.open(req, timeout=20)


def login(base: str, user: str, password: str) -> tuple[object, str]:
    """Complete the nonce + AES/RSA handshake. Returns (opener, csrf_token)."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )

    nonce_body = urllib.parse.urlencode({"userName": user}).encode()
    with _request(opener, f"{base}/login_web_app.cgi?nonce", data=nonce_body,
                  headers=HEADERS_HTML) as resp:
        challenge = json.load(resp)

    pubkey_der = base64.b64decode(challenge["pubkey"].split("-----")[2])
    public_key = serialization.load_der_public_key(pubkey_der)

    key, iv = os.urandom(16), os.urandom(16)
    enckey, enciv = _escape(_b64url(key)), _escape(_b64url(iv))

    payload = (
        f"userhash={user}"
        f"&RandomKeyhash={challenge['randomKey']}"
        f"&response={urllib.parse.quote(password)}"
        f"&nonce={_escape(challenge['nonce'])}"
        f"&enckey={enckey}&enciv={enciv}&nohash=1&hPassword=undefined"
    )

    padder = padding.PKCS7(128).padder()
    padded = padder.update(payload.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = _escape(
        base64.urlsafe_b64encode(encryptor.update(padded) + encryptor.finalize())
        .decode()
        .rstrip("=")
    )

    key_material = (
        base64.b64encode(key).decode() + " " + base64.b64encode(iv).decode()
    )
    wrapped = public_key.encrypt(key_material.encode(), asym_padding.PKCS1v15())
    ck = _escape(base64.urlsafe_b64encode(wrapped).decode())

    body = urllib.parse.urlencode(
        {"encrypted": 1, "ct": ciphertext, "ck": ck}
    ).encode()
    with _request(opener, f"{base}/login_web_app.cgi", data=body,
                  headers=HEADERS_FORM) as resp:
        if resp.status != 299:
            sys.exit(f"login failed with HTTP {resp.status}")
        session = json.load(resp)

    token = session.get("token")
    if not token:
        sys.exit("login succeeded but returned no CSRF token")
    return opener, token


def get_json(opener, url: str):
    with _request(opener, url) as resp:
        status = resp.status
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        return {"_status": status, "_raw": raw[:200]}


def post_form(opener, url: str, data: dict, token: str):
    body = dict(data)
    body["csrf_token"] = token
    encoded = urllib.parse.urlencode(body).encode()
    with _request(opener, url, data=encoded, headers=HEADERS_FORM) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return resp.status, raw


def _find(node, key):
    """Depth-first search for the first matching key (the LAN payload nests config)."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find(value, key)
            if found is not None:
                return found
    return None


def cmd_status(args, opener, token):
    base = args.base
    device = get_json(opener, f"{base}/device_status_web_app.cgi?getroot")
    wan = get_json(opener, f"{base}/wan_internet_status_web_app.cgi")
    lan = get_json(opener, f"{base}/lan_ipv4_status_web_app.cgi")
    caps = get_json(opener, f"{base}/capabilities_status_web_app.cgi")

    print(f"host        {args.host}")
    print(f"model       {device.get('ModelName')}  ({device.get('ProductClass')})")
    print(f"serial      {device.get('SerialNumber')}")
    print(f"firmware    {device.get('SoftwareVersion')}")
    print(f"uptime      {device.get('UpTime')} s")
    print(f"wan up      {wan.get('gwwanup')}")

    cfg = lan.get("ipv4_config") or {}
    if cfg:
        address = _find(lan, "IPInterfaceIPAddress")
        mask = _find(lan, "IPInterfaceSubnetMask")
        print(f"lan         {address}/{mask}")
        print(f"pool        {cfg.get('MinAddress')} - {cfg.get('MaxAddress')}")
        print(f"reservations {len(lan.get('bind_mac') or [])}")

    auth = (caps.get("AdminUserData") or {}).get("authorizedcgi") or []
    print(f"authorised  {len(auth)} CGI endpoints")
    return 0


def cmd_optimize(args, opener, token):
    url = f"{args.base}/wlan_config_web_app.cgi?OptimizeNetwork"
    if not args.commit:
        print("dry-run — would POST", url)
        print("  body: csrf_token=<token>")
        print("  (this triggers a Wi-Fi channel optimisation; add --commit to send)")
        return 0
    code, body = post_form(opener, url, {}, token)
    print(f"HTTP {code}  {body[:200]}")
    return 0 if code == 200 else 1


def cmd_raw(args, opener, token):
    url = f"{args.base}/{args.path.lstrip('/')}"
    data = {}
    if args.data:
        for pair in args.data.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                data[k] = v
    if not args.commit:
        print("dry-run — would POST", url)
        print("  body:", urllib.parse.urlencode({**data, "csrf_token": "<token>"}))
        return 0
    code, body = post_form(opener, url, data, token)
    print(f"HTTP {code}  {body[:400]}")
    return 0 if code == 200 else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="One-shot Nokia WiFi SPA actions (evicts the HA integration session)."
    )
    parser.add_argument("--host", default=os.environ.get("NOKIA_HOST", "192.168.1.1"))
    parser.add_argument("--user", default=os.environ.get("NOKIA_USER", "admin"))
    parser.add_argument("--password", default=os.environ.get("NOKIA_PASSWORD"))
    parser.add_argument("--commit", action="store_true", help="actually send writes")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="read-only summary")

    sub.add_parser("optimize", help="trigger Wi-Fi network optimisation")

    raw = sub.add_parser("raw", help="POST any endpoint with form data")
    raw.add_argument("--path", required=True, help="e.g. 'wlan_config_web_app.cgi?setwifi'")
    raw.add_argument("--data", default="", help="form fields, e.g. 'a=1&b=2'")

    args = parser.parse_args(argv)
    args.base = f"http://{args.host}"

    password = args.password
    if not password:
        password = getpass.getpass(f"password for {args.user}@{args.host}: ")

    try:
        opener, token = login(args.base, args.user, password)
    except urllib.error.URLError as err:
        sys.exit(f"cannot reach {args.host}: {err}")

    handlers = {"status": cmd_status, "optimize": cmd_optimize, "raw": cmd_raw}
    return handlers[args.command](args, opener, token)


if __name__ == "__main__":
    sys.exit(main())
