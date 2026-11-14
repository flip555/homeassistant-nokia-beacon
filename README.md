# Nokia WiFi Beacon for Home Assistant

Local presence tracking and DHCP reservation management for Nokia WiFi gateways — no Nokia
cloud account, no mobile app, no internet dependency.

> Developed and tested against a **Nokia WiFi Beacon 19.1** on an ISP-managed profile. See [Supported devices](#supported-devices) if you have different hardware.

## Features

- **Device tracking** — every client on your network as a `device_tracker`, updated live from
  the gateway's own telemetry websocket. Presence is the gateway's `active` flag, not a ping
  guess.
- **DHCP reservations** — list them as a sensor attribute, add and delete them as services.
- **Gateway sensors** — firmware, uptime, DHCP pool utilisation, per-radio congestion, WAN
  state.
- **Credential backup** — optionally keeps the WAN/PPPoE username and password in a file under
  `.storage`, so they survive a router failure and ride along in your Home Assistant backups.
- **No cloud.** The integration talks to the gateway on your LAN and nothing else.

## Requirements

- Home Assistant **2024.6** or newer
- The gateway reachable on your LAN over **HTTP (port 80)** and **TCP 8099** (telemetry)
- The gateway's admin username and password
- Home Assistant and the gateway on the same network (or routed) — this is a local integration

## Installation

### HACS

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add this repository URL, category **Integration**
3. Install **Nokia WiFi Beacon**, then restart Home Assistant

### Manual

Copy `custom_components/nokia_wifi_beacon/` into your Home Assistant `config/custom_components/`
directory and restart.

## Setup

**Settings → Devices & Services → Add Integration → Nokia WiFi Beacon**

| Field | Value |
|---|---|
| Host | your gateway, e.g. `192.168.1.1` |
| Admin username | default `admin` |
| Password | your gateway admin password |

The integration logs in, reads the serial number, and creates one device with its entities.

If you later change the admin username or password on the gateway, use **Reconfigure** on the
integration — it validates the new credentials before saving.

## What you get

| Entity | Type | Notes |
|---|---|---|
| One per client | `device_tracker` | presence, MAC, IP, interface, link rates |
| Firmware | `sensor` | diagnostic |
| Uptime | `sensor` | diagnostic |
| Reservations | `sensor` | count; full list of `oid`/MAC/IP as an attribute |
| DHCP pool utilisation | `sensor` | percent |
| Congestion 2.4 GHz / 5 GHz | `sensor` | percent, per radio |
| WAN | `binary_sensor` | connectivity |
| WAN PPPoE credentials | `sensor` | **disabled by default** — see below |

## Services

```yaml
action: nokia_wifi_beacon.add_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"     # any case, colons or dashes
  ip: "192.168.1.127"
```

```yaml
action: nokia_wifi_beacon.delete_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"     # or: oid: "29"
```

The `oid` for each reservation is exposed in the `reservations` attribute of the **Reservations**
sensor. Both services accept an optional `entry_id` when more than one gateway is configured.

## Options

**Settings → Devices & Services → Nokia WiFi Beacon → Configure**

- **Poll interval** — 30 to 600 seconds (default 60). Only affects the sensors; presence comes
  from the websocket and is always live.
- **Include credentials in diagnostics** — off by default. When off, the diagnostics download
  redacts the password.

## Credential backup

The gateway returns the WAN/PPPoE username and password in clear text. If you enable the
**WAN PPPoE credentials** sensor, the integration also writes them to:

```
.storage/nokia_wifi_beacon_wan_credentials.json
```

That file is included in every Home Assistant backup and is never purged, so restoring an old
backup gives you the credentials you need to re-dial PPPoE on replacement hardware. The file is
created with `0600` permissions.

Enabling the sensor also puts the username and password into the recorder database. If you'd
rather not, leave the sensor disabled and rely on the `.storage` file alone.

## Limitations

These are properties of the device, not bugs:

- **Device tracking requires port 8099.** The gateway exposes no client list over HTTP; presence
  is streamed on its telemetry websocket. If that port is blocked, sensors still work and
  trackers stay absent.
- **`band` and signal are only meaningful on the gateway's own radios.** If your Wi-Fi is served
  by separate access points, clients appear as `Ethernet` with no band or RSSI. That is accurate.
- **The LAN subnet and DHCP pool are read-only.** ISP capability profiles do not authorise the
  write endpoint. Reservations are unaffected.
- **One admin session.** Opening the gateway's web UI logs the integration out; it
  re-authenticates automatically within one poll cycle.
- **Wi-Fi settings are not exposed** (channels, width, MLO). They live behind a different login
  type that would evict the integration's session.

## Supported devices

| Model | Status |
|---|---|
| Nokia WiFi Beacon 19.1 | ✅ tested |
| Other ALCL-based Nokia WiFi gateways | likely, if `login_app.cgi` and port 8099 exist |
| Nokia XS-2426G-B | different firmware — use the [mversluijs integration](https://github.com/mversluijs/homeassistant_nokiaxs2426gb_devicetracker) |

If you try it on other hardware, the diagnostics download and the debug log will show which
endpoints answered.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Setup fails with *invalid auth* | wrong username/password, or the gateway uses a different login type |
| Setup fails with *not a Nokia gateway* | wrong host, or a different vendor on that IP |
| Trackers appear then stop updating | port 8099 unreachable, or another admin session evicted ours |
| `sensor` values stop refreshing for a minute | something logged into the router UI; it recovers |
| Reservations service fails with `result:1` | address outside the pool, or already bound to another MAC |

Enable debug logging for `custom_components.nokia_wifi_beacon` to see each request and the
websocket event stream.

## Advanced: the `nokia-spa` tool

The gateway runs **two separate admin APIs**, and only one session may exist at a time:

| Session | Can do | Used by |
|---|---|---|
| `login_app.cgi` | DHCP reservations, gateway status | this integration |
| `login_web_app.cgi` | Wi-Fi settings, diagnostics, speed tests | the gateway's web UI |

`tools/nokia-spa.py` is a standalone script for the second one — for one-off actions the
integration deliberately does not expose:

```sh
pip install cryptography
export NOKIA_HOST=192.168.1.1 NOKIA_USER=admin

python3 tools/nokia-spa.py status
python3 tools/nokia-spa.py optimize --commit
python3 tools/nokia-spa.py raw --path "wlan_config_web_app.cgi?setwifi" \
    --data "ssid=MyNetwork&pwd=secret" --commit
```

- **Writes are dry-run** unless you pass `--commit`.
- **One-shot only.** While it is logged in, the integration is logged out; it re-authenticates
  on its next poll (up to one poll interval). Running it in a loop will starve the integration.
- The password comes from `--password` or `NOKIA_PASSWORD`, or is prompted for.

## Technical documentation

Endpoint inventory, the websocket handshake and capability flags are documented in the project
wiki. The raw reference also lives in [`docs/API.md`](docs/API.md).

## Licence

MIT — see [LICENSE](LICENSE).

Not affiliated with Nokia. Use at your own risk; this drives your gateway's administration
interface.
