# Nokia WiFi Beacon — Home Assistant integration

Local-only integration for Nokia WiFi gateways (developed against a **Beacon 19.1**).
No cloud account, no Nokia app, no scraping — it drives the gateway's own CGI endpoints and
subscribes to its telemetry websocket on port 8099.

## What you get

- **`device_tracker`** — one entity per client, live, from the gateway's websocket
  (`AllDeviceInfo` / `DeviceStatusUpdate`). Presence is the device's `active` flag.
- **Sensors** — firmware, uptime, DHCP reservations count (with the full list as an
  attribute), pool utilisation, per-radio congestion.
- **`binary_sensor`** — WAN link state.
- **Services** — add and delete DHCP reservations.
- **Config / reconfigure / reauth** — reconfigure changes host, admin username and admin
  password in one step.

## Requirements

- Home Assistant 2024.6 or newer
- The gateway reachable on the LAN (plain HTTP, port 80) and TCP 8099 open
- Admin credentials for the gateway

## Install

1. Copy `custom_components/nokia_wifi_beacon/` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Nokia WiFi Beacon*.
4. Enter the gateway host (e.g. `192.168.1.1`), admin username and password.

## Changing the admin username or password

Settings → Devices & Services → **Nokia WiFi Beacon** → **Reconfigure**. It validates by
logging in before saving, and refuses if the credentials now point at a different gateway
(different serial number).

If the gateway starts rejecting the stored password, HA raises a reauth prompt
automatically — password only, not the whole config.

## Services

```yaml
action: nokia_wifi_beacon.add_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"
  ip: "192.168.1.127"
```

```yaml
action: nokia_wifi_beacon.delete_reservation
data:
  mac: "aa:bb:cc:dd:ee:01"     # or oid: "29"
```

`oid` is the gateway's own handle; it is exposed in the `reservations` attribute of the
**Reservations** sensor.

## Limitations

- **No client list over HTTP.** The CGI family exposes configuration and reservations only;
  the device table is streamed on the websocket. If port 8099 is unreachable, trackers will
  not work but sensors will.
- **LAN/DHCP settings are read-only.** ISP capability profiles disable the writer
  (`lan_ipv4_web_app.cgi` is not in `authorizedcgi`). This is a device-side restriction.
- **`band` and `rssi` are meaningless** when clients reach the gateway through third-party
  access points — they all report `interface: Ethernet` with `NA` for band. They only
  populate for clients on the gateway's own radios.
- **One admin session.** Opening the router's web UI can evict the integration's session;
  the socket reconnects on its own every 15 s.

## API reference

`README.md` documents every endpoint, the websocket handshake and the device payload, with
verification status for each.
