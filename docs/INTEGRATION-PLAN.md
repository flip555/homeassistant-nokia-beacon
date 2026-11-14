# HA integration plan — `nokia_wifi_beacon`

Custom component for the Nokia WiFi Beacon 19.1, built only on the **legacy CGI family**
that is actually script-accessible. No SPA endpoints, no scraping.

- Domain: `nokia_wifi_beacon` (avoids colliding with HA's existing `nokia` domain)
- IoT class: `local_polling`
- Quality: config flow, unique_id, reauth, diagnostics, services

---

## 1. Scope

### In

| Capability | Endpoint | Verified |
|---|---|---|
| Auth / session | `POST login_app.cgi` | ✅ |
| Router identity | `GET device_status_app.cgi` | ✅ |
| Feature flags | `GET get_devmap_cap_status_app.cgi` | ✅ |
| DHCP config + reservations | `GET dhcpv4_server_status_app.cgi` | ✅ |
| Add / delete reservation | `POST lan_ipv4_app.cgi` (`act=Add`/`act=Del`) | ✅ |
| SSID inventory | `GET wlan_list_app.cgi` | ✅ |
| WAN link state | `GET wan_internet_status_app.cgi` | ✅ |
| WAN config (PPPoE) | `GET wan_list_app.cgi` | ✅ (redacted) |
| Port forwards | `GET portmaps_status_app.cgi` | ✅ |
| UPnP state | `GET upnp_status_app.cgi` | ✅ |
| LED state | `GET ledctrl_status_app.cgi` | ✅ |
| Radio congestion | `GET network_optimize_status_app.cgi` | ✅ |
| **Live client list** | **websocket `ws://<gw>:8099`** | ✅ |

### Out (deliberately)

- **Writing LAN/DHCP config** — refused by the capability profile (`lan_ipv4_web_app.cgi`
  not in `authorizedcgi`, plus CSRF). There is no workaround.
- **Wi-Fi PSK / WAN password as entities** — the API returns both in cleartext; surfacing
  them in HA state would spread credentials into the recorder database and any dashboard.
  If ever needed, expose only via `diagnostics` with explicit redaction off.
- **Reboot button (v1)** — `reboot_app.cgi` exists but is untested and destructive. Add in
  v2 behind an opt-in option.

---

## 2. Authentication model

```python
POST /login_app.cgi
data: {"name": user, "pswd": password, "srip": ""}
→ {"result":0,"reason":0, "cookie":{"sid":"sid=…","lsid":"lsid=…"}}
```

- Keep an `aiohttp.CookieJar` per config entry.
- Response `302` (or a non-JSON body) means the session is gone → re-login once, retry once,
  then raise `ConfigEntryAuthFailed`.
- Observed: sessions can die within minutes. Do **not** assume a 30-minute lifetime.
- Known hazard: the gateway appears to allow one admin session. Opening the router UI can
  evict the integration, and the re-login can then evict the browser. Mitigate with a
  re-login backoff (max 1 attempt per 30 s) and log it at debug, not warning.

---

## 2b. Websocket client (device tracking)

Verified working against the live gateway.

### Sequence

1. `POST /login_app.cgi` → `sid`, `lsid`
2. Open `ws://<host>:8099`, header `Cookie: lang=eng; sid=…; lsid=…`
3. Send `base64("<user>:<password>")` as the first text frame; expect `200 OK`
4. `POST /websoc_session_app.cgi` with `command=Session_START{Mobile}&timeout=1800`
5. Consume JSON events

### Events to handle

- `AllDeviceInfo` — full snapshot, take it as the authoritative list
- `DeviceStatusUpdate` — repeated full/delta refresh (every few seconds): use `active` to set
  `home`/`not_home`
- `NewDeviceAdded` — new client
- `Wifi_Associated_Devices_Update` — clients on the gateway's own radios
- `SSIDInfo`, `MeshNetwork` — informational

### Device record

`{gw, mac, ip, ipv6[], host, friendlyname, interface, active, band, rssi, txPhyRate,
rxPhyRate, isBeacon, isCritical, model, manufacturer, category}`

- `active` `"1"`/`"0"` drives presence
- `interface` is `Ethernet` for everything here (Wi-Fi is served by third-party APs), so
  `band`/`rssi` are `NA` — do not model those as meaningful in this topology
- rates are in **bps** as strings

### Implementation notes

- `aiohttp` `ClientSession.ws_connect`; send the base64 frame, then call session start
- the socket pushes constantly, so the coordinator should be event-driven rather than polled
  for trackers; keep the 60 s HTTP poll only for config/leases
- reconnect with backoff; auth failure returns a non-`200 OK` string and closes the socket
- the session start POST needs the HTTP cookie, so the API client must hold both

## 3. Coordinator

One `DataUpdateCoordinator`, default interval **60 s**, four GETs per cycle:

```
device_status_app.cgi          (uptime, firmware)
dhcpv4_server_status_app.cgi   (pool, reservations)
wan_internet_status_app.cgi    (link state)
network_optimize_status_app.cgi (congestion)
```

Static data fetched once at setup and the first refresh: `get_devmap_cap_status_app.cgi`,
`wlan_list_app.cgi`, `wan_list_app.cgi`, `portmaps_status_app.cgi`.

`upnp_status_app.cgi` and `ledctrl_status_app.cgi` on a slower cadence (every 5th cycle).

Options flow: `scan_interval` (30–300 s), `enable_diagnostics_sensors`.

---

## 4. Entities

### Device
One device: `identifiers={(DOMAIN, serial)}`, `manufacturer="Nokia"`,
`model="WiFi Beacon 19.1"`, `sw_version=firmware`, `name="Nokia WiFi"`,
`configuration_url="http://<host>"`.

### Sensors

| Entity | Source | Notes |
|---|---|---|
| `sensor.nokia_wifi_beacon_uptime` | `UpTime` | seconds, `duration` device class, diagnostic |
| `sensor.nokia_wifi_beacon_firmware` | `SoftwareVersion` | diagnostic |
| `sensor.nokia_wifi_beacon_dhcp_leases_used` | `len(bind_mac)` | reservations count |
| `sensor.nokia_wifi_beacon_dhcp_pool_size` | Min/MaxAddress | computed |
| `sensor.nokia_wifi_beacon_dhcp_pool_utilisation` | computed | `%`, diagnostic |
| `sensor.nokia_wifi_beacon_port_forwards` | `portmaps` | count |
| `sensor.nokia_wifi_beacon_congestion_2g` | RadioList oid 1 | `%`, 0–100 |
| `sensor.nokia_wifi_beacon_congestion_5g` | RadioList oid 2/3 | `%` |
| `sensor.nokia_wifi_beacon_wan_dns` | `wan_list.DNSServers` | diagnostic |
| `sensor.nokia_wifi_beacon_ssid` | `wlan_list` enabled entries | state = SSID, attrs = bands, security |

### Binary sensors

| Entity | Condition |
|---|---|
| `binary_sensor.nokia_wifi_beacon_wan` | `gwwanup == 1` → on, device_class `connectivity` |
| `binary_sensor.nokia_wifi_beacon_upnp` | `upnp.Enable == 1` |
| `binary_sensor.nokia_wifi_beacon_led` | `LEDGlobalSts` (semantics need confirming) |

### device_tracker

One entity per client MAC, fed by the websocket:

- `source_type`: `router`
- state: `home` when `active == "1"`, else `not_home`
- attributes: `ip`, `host`, `interface`, `txPhyRate`, `rxPhyRate`, `isBeacon`
- created from `AllDeviceInfo`, updated by `DeviceStatusUpdate` / `NewDeviceAdded`
- name from `friendlyname` → `host` → MAC
- entities are added dynamically; prune on restart from the first `AllDeviceInfo`

### Not entities
- reservation list → exposed as **attributes** of `sensor.dhcp_leases_used` (mac, ip, oid,
  capped to 50), so dashboards can table them without 30 entities
- SSID slots → attributes on `sensor.ssid`
- capability flags → `diagnostics` only

---

## 5. Services

```yaml
action: nokia_wifi_beacon.add_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"     # normalised to lowercase
  ip: "192.168.1.127"
```

```yaml
action: nokia_wifi_beacon.delete_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"     # or:
  oid: 29
```

Both accept `entry_id` when multiple gateways are configured. `delete` resolves `oid` from
the coordinator's cached `bind_mac` if given a MAC. Both refresh the coordinator on success
and raise `ServiceValidationError` on `{"result":1}`.

---

## 6. Config flow

1. **user** — host (default: the HA host's default gateway), username, password
2. validate: login → `device_status_app.cgi` → require `SerialNumber`
3. `unique_id` = serial (`AA11BB22CC33`); abort `already_configured` if seen
4. **reauth** — re-prompt password on `ConfigEntryAuthFailed`
5. Store password in the entry; no re-auth token exists

---

## 7. Diagnostics

`async_get_config_entry_diagnostics` returns the coordinator snapshot with these redacted:
`PreSharedKey`, `WEPKey`, `Password`, `Username`, `cldClaimID`, `sid`, `lsid`.
Tests must assert the redaction rather than trusting the code.

---

## 8. File layout

```
custom_components/nokia_wifi_beacon/
├── __init__.py        # setup, unload, service registration
├── api.py             # NokiaBeaconApi: login, get, post, session handling
├── const.py           # DOMAIN, endpoints, defaults
├── coordinator.py     # DataUpdateCoordinator + parsers
├── config_flow.py
├── sensor.py
├── binary_sensor.py
├── services.py
├── diagnostics.py
├── manifest.json      # requirements: []  (aiohttp is core)
├── strings.json
└── translations/en.json
```

Estimated ~700 lines including tests. `api.py` is the only place that knows the CGI names.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Session eviction ping-pong with the router UI | re-login backoff, single retry, debug logging |
| Firmware update renames/removes a CGI | every GET is optional except `device_status`; log and continue |
| `result:0` with no body from a writer | only treat known writers as writes; never infer success from an empty body |
| Credentials in state | never expose PSK/PPPoE; diagnostics redaction test |
| ISP disables `Ip_Reservation` on another profile | gate services on the `Settings.Ip_Reservation` flag |
| Slow/hung CGI blocks the poll | 10 s per-request timeout, coordinator `update_interval` floor 30 s |

---

## 10. Build order

1. `api.py` + `const.py` — login, GET/POST, 302 handling, parsers
2. `config_flow.py` + `__init__.py` — a working entry that logs "connected, firmware X"
3. `coordinator.py` + `sensor.py` — uptime, firmware, WAN, reservations count
4. `services.py` — add/delete reservation, round-trip tested against the live gateway
5. `binary_sensor.py`, congestion sensors, attributes
6. `diagnostics.py` + redaction test
7. `strings.json`, icons, README

Verification: run against the live gateway from the HA container
(`/root/homeassistant`) with `custom_components/` mounted, then restart HA and confirm
entities appear and services mutate a test reservation.
