# Nokia WiFi Beacon 19.1 — local API (verified map)

Updated 2026-11-14 after a full probing session. Supersedes the earlier speculative version.

## Headline

The gateway runs **two CGI families**, and only one of them will talk to a script:

| Family | Example | Script access |
|---|---|---|
| Legacy `*_app.cgi` | `dhcpv4_server_status_app.cgi` | ✅ works with a plain session cookie |
| SPA `*_web_app.cgi` | `capabilities_status_web_app.cgi` | ❌ `302 → /` for anything that isn't the browser app |

We tried cookies, both usernames, `lang`, `Referer`, Chrome UA, fresh sessions, and
`Accept-Language`. The SPA family is gated at the server, not by anything we were getting
wrong. **Design the integration around the legacy family only.**

## Auth (verified)

```
POST /login_app.cgi
name=<user>&pswd=<password>&srip=
```

```json
{"result":0,"reason":0,"prio":0,"gwsnum":"AA11BB22CC33",
 "hieSrvURL":"https://edge.eu4.wifi.nokia.com",
 "cookie":{"sid":"sid=…","lsid":"lsid=…"},
 "gwtime":1794655419}
```

- Session tokens are returned **in the JSON body** as well as (sometimes) `Set-Cookie`.
- Legacy CGIs accept either a cookie jar (`-b`) or an explicit `Cookie: sid=…; lsid=…`.
- `name=admin` and `name=Administrator` both return `result:0`. Role differences are
  unconfirmed; the successful legacy calls used `admin`.
- `Local_Auto_Logout.Enable` is `0` with `Timeout: 1800`, yet sessions were seen to expire
  within minutes. Treat expiry as normal and re-login on failure.

### Failure modes

| Response | Meaning |
|---|---|
| `302` + `Location: /` | no/expired session, or an SPA-family endpoint |
| `{"result":-1,"reason":403}` | not authorised |
| `411 Length Required` | POST arrived without a body (malformed request) |
| `{"result":1,"reason":1}` | bad parameters |

## Legacy endpoints — verified responses

### `GET /device_status_app.cgi` — router identity ✅

```json
{"ManufacturerOUI":"F89B6E","ProductClass":"Beacon 19.1",
 "ModelName":"Nokia WiFi Beacon 19.1","Vendor":"Nokia",
 "SerialNumber":"AA11BB22CC33","HardwareVersion":"3TN01763CDAA",
 "SoftwareVersion":"3TN01886JJML39","X_ASB_COM_Chipset":"IPQ5424",
 "AdditionalSoftwareVersion":"u-boot-2023.04_2504_0417\n","UpTime":53948}
```

### `GET /dhcpv4_server_status_app.cgi` — DHCP config + reservations ✅

```json
{"dhcp_status":{"DHCPServerConfigurable":1,"DHCPServerEnable":1,
  "MinAddress":"192.168.1.2","MaxAddress":"192.168.1.253",
  "SubnetMask":"255.255.255.0","IPInterfaceIPAddress":"192.168.1.1",
  "IPInterfaceSubnetMask":"255.255.255.0","DHCPLeaseTime":86400,
  "ReservedAddresses":""},
 "bind_mac":[{"oid":"1","Chaddr":"aa:bb:cc:dd:ee:01",
              "Yiaddr":"192.168.1.30","FriendlyName":"…"}]}
```

`Chaddr` = MAC, `Yiaddr` = IP, `oid` = delete handle.

### `POST /lan_ipv4_app.cgi` — reservation add/delete ✅

```
act=Add&bindmac=<lowercase mac>&bindip=<ip>&oid=0    → {"result":0,"reason":0}
act=Del&oid=<oid>                                    → {"result":0,"reason":0}
```

MAC must be lowercase colon-separated. `oid=0` for new.

### `GET /get_devmap_cap_status_app.cgi` — feature flags ✅

```json
{"devapp_cap_info":[{"devVer":"6.5","devMode":"RGW","devGwSnum":"AA11BB22CC33",
   "devGwMac":"aa:bb:cc:dd:ee:02","cldRemoteUrl":"https://edge.eu4.wifi.nokia.com"}],
 "Settings":[{"Bridge_Mode":1,"Multiple_SSID_Support":1,"Software_Update":1,
   "Custom_Dns":1,"Port_Forwarding":1,"Ip_Reservation":1,"Upnp":1,"Network_Mode":1,
   "Local_Account_Password_Modification":1,"MLO":0,"WPA3Encryption":1,
   "Network_Optimize":1,"WAN_VlanId":1}],
 "Parental_Control":[{"Device_Access":1,"Client_Device_Blocking":1,"New_URL_Filter":1,
   "Bed_Time":1,"schedule":1,"New_Parental_control":1}],
 "Guest_Network":[{"Guest_Access":1,"Guest_Access_Open":-1}],
 "IoT_Network":[{"IoT_Access":-1}],
 "Network_Management":[{"LED_Control":1,"LED_Control_Extenders":1}],
 "Speed_Test":[{"TR143":-1}],
 "Password_Policy":[{"Modify_Login_Password":0,"Modify_SSID_Password":0}],
 "Local_Auto_Logout":[{"Enable":0,"Timeout":1800}]}
```

`1` = supported/enabled, `0` = disabled, `-1` = not applicable.

Notable: **`Bridge_Mode: 1`** (the firmware supports it, even if the ISP UI does not expose
the toggle) and **`MLO: 0`** (Wi-Fi 7 multi-link is off).

### `GET /wlan_devices_status_app.cgi` — Nokia's own wireless clients ✅

```json
{"wlan_devices_list":[],"wlan_guest_cnt":0}
```

Empty in this topology: the Wi-Fi is served by third-party APs, so the Nokia has no wireless
clients of its own. Not an error.

### Writers (return `{"result":0,"reason":0}`, no data)

| Endpoint | Purpose |
|---|---|
| `lan_devices_app.cgi` | `post_lan_details` — set device names |
| `wlan_devices_app.cgi` | `post_guest_wlan_details` — guest SSID |
| `portmaps_app.cgi` | port-forward rules |
| `portmaps_status_app.cgi` | **reader** for port-forward rules |

### Other legacy endpoints present in the bundle

`wlan_list_app.cgi` (SSIDs) · `wlan_config_app.cgi` · `wan_list_app.cgi` ·
`wan_config_app.cgi` · `wan_internet_status_app.cgi` · `upnp_status_app.cgi` ·
`parentalctrl_status_app.cgi` / `parentalctrl_app.cgi` ·
`parental_ctrl_nok_status_app.cgi` / `parental_ctrl_nok_app.cgi` ·
`device_name_status_app.cgi` (returned empty) · `ledctrl_status_app.cgi` / `ledctrl_app.cgi` ·
`reboot_app.cgi` · `factory_reset_app.cgi` · `service_function2_app.cgi` ·
`network_optimize_status_app.cgi` · `speed_test_tr143_status_app.cgi` ·
`websoc_session_app.cgi` (websocket session, `Session_START{Mobile}&timeout=1800`) ·
`index_app.cgi` · `password_policy_status_app.cgi`.

## There is no client list in the CGI family

Confirmed by exhaustion: `wlan_devices_status_app.cgi` (empty), `device_status_app.cgi`
(router identity), `device_name_status_app.cgi` (empty), `lan_devices_app.cgi` (writer),
`portmaps_status_app.cgi` (port forwards). The web UI's device table comes from the SPA family,
which refuses non-browser clients.

**But the client list does exist locally** — it is pushed over the websocket on port 8099.
An earlier version of this document concluded a `device_tracker` was impossible; that was
wrong. It is possible, it simply does not use HTTP.

## Verified response dump (2026-11-14)

Full sweep of every read-only endpoint. Shapes below; credentials redacted.

### `GET /wlan_list_app.cgi` — SSIDs ✅

```json
{"wlan_list":[
 {"oid":1,"Enable":1,"Type":"2.4G","MLOEnabled":0,"SSID":"<house-ssid>",
  "IsGuestSSID":0,"X_ALU_COM_IsIOTSSID":0,"BeaconType":"11iandWPA3",
  "WPAAuthenticationMode":"PSKAuthentication","WPAEncryptionModes":"AESEncryption",
  "HideFromUser":0,"PreSharedKey":"<redacted>","AutoChannelEnabled":1},
 {"oid":5,"Type":"5G","SSID":"<same-ssid>", ... }
]}
```

- One entry per band per SSID: oid 1 = 2.4G, oid 5 = 5G, disabled slots follow each band
- `BeaconType: 11iandWPA3` — WPA2/WPA3 **mixed** (correct for the Linksys APs)
- `MLOEnabled: 0` on every entry — Wi-Fi 7 multi-link is off
- `PreSharedKey` returned in cleartext
- `PossibleChannels` lists the regulatory channel set per band (2.4 = 1–13, 5 = 36–140)
- **No 6 GHz radio is exposed.** The full sweep returned 4 × `2.4G` and 3 × `5G` entries and
  zero `6G`. `MLOEnabled: 0` on every entry. So "Wi-Fi 7" on this SKU means the Wi-Fi 7 PHY
  on 2.4/5 GHz only — no 6 GHz, no multi-link.

### `GET /wan_list_app.cgi` — WAN ✅

```json
{"wan_list":[{"oid":1,"type":"ppp","Name":"1_TR069_INTERNET_OTHER_R_VID_0",
 "NATEnabled":1,"ConnectionType":"IP_Routed","Enable":1,
 "Username":"<isp-user>","Password":"<redacted>",
 "X_ASB_COM_VlanMuxID":0,
 "DNSServers":"<isp-dns-1>,<isp-dns-2>",
 "ConnectionStatus":"Connected"}]}
```

PPPoE, VLAN 0, ISP DNS, both credentials in cleartext. This is what you would need to
re-dial PPPoE yourself if the Nokia were ever put into bridge mode.

### Other verified readers

```json
GET /wan_internet_status_app.cgi      {"result":0,"reason":0,"gwwanup":1}
GET /portmaps_status_app.cgi          {"port_mappings":[{"oid":1,"portmaps":[],
                                        "WanConnectionMode":"ppp","hasInternetService":1}]}
GET /upnp_status_app.cgi              {"upnp":[{"Enable":0}]}
GET /ledctrl_status_app.cgi           {"LEDGlobalSts":0,"ledctrl_list":[{"oid":1,"Enable":1,
                                        "NodeID":"<gw-mac>"}]}
GET /network_optimize_status_app.cgi  per-radio "CongestionLevel" (0–100) per oid
GET /password_policy_status_app.cgi   password rules (min 8, max 24, two char classes)
```

`network_optimize_status_app.cgi` is the useful one operationally: on this install the 2.4 GHz
radio reported congestion 68 against 2 on the 5 GHz radios — i.e. 2.4 is the contended band.

### Present but not usable

| Endpoint | Result |
|---|---|
| `device_name_status_app.cgi` | 200, empty body (needs params) |
| `speed_test_tr143_status_app.cgi` | 200, empty body (needs params) |
| `parental_ctrl_nok_status_app.cgi` | 500 |
| `parentalctrl_status_app.cgi` | 404 |
| `cell_status_app.cgi`, `cell_list_app.cgi`, `index_app.cgi` | 404 — no LTE on this SKU |
| `radio_receiver_status_app.cgi` | 403 |

## Websocket :8099 — this is where the device list lives

Verified live. Local, no cloud account involved.

### Handshake

1. `POST /login_app.cgi` → `sid`, `lsid`
2. Open `ws://<gw>:8099` with header `Cookie: lang=eng; sid=…; lsid=…` → `101 Switching Protocols`
3. **Client sends first frame**: `base64("<user>:<password>")` → server replies the text frame `200 OK`
4. `POST /websoc_session_app.cgi` with `command=Session_START{Mobile}&timeout=1800` → `{"result":0,"reason":0}`
5. JSON events begin streaming (several per second)

A wrong credential returns a failure string instead of `200 OK` and the socket is closed.

### Events observed

| Event | Meaning |
|---|---|
| `AllDeviceInfo` | full snapshot of every client |
| `DeviceStatusUpdate` | delta/full refresh, repeats every few seconds |
| `Wifi_Associated_Devices_Update` | clients on the gateway's own radios |
| `SSIDInfo` | SSID state |
| `MeshNetwork` | topology (`aps[]`, `links[]`) |

Also present in the app's event list and worth handling: `NewDeviceAdded`, `DeviceInfo`,
`MeshLinks`, `MeshNodeAdded`, `ExtenderAdded`, `OnboardTimeout`, `SSIDInfoChange`.

### Device payload (verified)

```json
{"gw":"AA11BB22CC33","mac":"AA:BB:CC:DD:EE:03","serialNumber":"",
 "ip":"192.168.1.206","ipv6":[],"rssi":"0","manufacturer":"",
 "host":"laptop","name":"","model":"","category":"",
 "friendlyname":"laptop","interface":"Ethernet","active":"1",
 "isBeacon":false,"isCritical":false,"band":"NA",
 "supportedbands":"NA","preferred_radio_band":"NA",
 "txPhyRate":"10000000","rxPhyRate":"10000000"}
```

Fields that matter for a tracker:

- `mac`, `ip`, `host` / `friendlyname` — identity
- `active` — `"1"` present, `"0"` gone
- `interface` — `Ethernet` | `2.4G` | `5G` | `6G`
- `band`, `supportedbands`, `preferred_radio_band` — always `NA` for wired clients
- `rssi`, `txPhyRate`, `rxPhyRate` — link quality (rates in bps)
- `isBeacon`, `isCritical` — mesh / user flagged

Because every client in this install reaches the gateway over Ethernet (the Wi-Fi is served by
third-party APs), `interface` is `Ethernet` and `band`/`rssi` are `NA`. Their IPs, MACs,
hostnames and presence are all correct.

## Security findings

1. **The Wi-Fi PSK is the same string as the gateway admin password.** `wlan_list_app.cgi`
   returns it in cleartext and `login_app.cgi` accepts it. Anyone with the Wi-Fi password has
   the router password — and this API returns it without any extra auth beyond a session.
2. **PPPoE credentials are returned in cleartext** by `wan_list_app.cgi`.
3. **No port forwards, UPnP disabled** — inbound is only via the Cloudflare tunnel. That part
   is clean.
4. Consequence: `192.168.1.1` is a credential store. Never route this API through the tunnel,
   and treat the house LAN as trusted-only.

## Recommended integration design

**Nokia integration — what it can do well**

- config flow: host, username, password → verify via `login_app.cgi` then
  `device_status_app.cgi`
- coordinator: 60 s poll of `device_status_app.cgi` + `dhcpv4_server_status_app.cgi`
- sensors: firmware version, model, serial, uptime, DHCP pool range, pool utilisation
- number/select: DHCP lease time — **readable only**; the writer is in the blocked family
- services: `add_reservation`, `delete_reservation` (both verified), `reboot_router` (untested)
- gate optional features on `get_devmap_cap_status_app.cgi` flags
- device registry: `devGwSnum`, `devGwMac`, `ModelName`, `devVer`

**Presence — use HA's `nmap_tracker` instead**

Scan `192.168.1.0/24` on an interval. It yields MAC + IP per host and creates a tracker per
device without touching a vendor API. In this setup it is strictly better: the Nokia only
ever sees the Wi-Fi clients as wired anyway, so the data would have been equivalent — minus
the auth constraints.

## Implementation pitfalls

1. `curl -c <jar>` **truncates** the file. A failed login leaves an empty jar and every later
   call 302s. Use a fresh filename, or save the login body and read the sid from JSON.
2. Never build these URLs with backslash line continuations — a stray non-breaking space
   splits the command and produces `411` (no body) plus a `command not found`.
3. `{"result":0,"reason":0}` from `*_app.cgi` can mean "nothing to do" — writers and readers
   are not distinguishable by response shape.
4. The SPA family will never work from a script; don't spend time on it.
5. Sessions expire quickly; re-login on `302`.

## Untested / unknown

- Whether `Bridge_Mode` can be toggled via CGI (flag says supported).
- Whether `MLO` can be enabled.
- Exact response of `wlan_list_app.cgi`, `wan_internet_status_app.cgi`, `portmaps_status_app.cgi`.
- Whether `name=Administrator` grants more than `name=admin` on the SPA family (moot while
  that family is browser-only).

---

## Web UI session (SPA) — second, incompatible login

The gateway exposes two admin APIs with **separate session types**. Only one session can exist
at a time; logging in to one evicts the other. Same cookie name (`sid`), different authorisation.

### Handshake (verified)

```
POST /login_web_app.cgi?nonce          body: userName=<user>
  → {"nonce":"…","randomKey":"…","pubkey":"-----BEGIN PUBLIC KEY-----…"}
POST /login_web_app.cgi                body: encrypted=1&ct=<aes>&ck=<rsa>
  → HTTP 299, {"result":0,"sid":"…","token":"…","ModifyPassword":"…"}
```

- AES-128-CBC with a random key/iv, PKCS#7 padded, base64url (no `=` padding, `+`→`-`, `/`→`_`,
  and `.` used in place of `=` by the app)
- `ck` = RSA PKCS#1 v1.5 encryption of `base64(key) + " " + base64(iv)`
- plaintext: `userhash=<user>&RandomKeyhash=<randomKey>&response=<urlquoted password>&nonce=<…>&enckey=<…>&enciv=<…>&nohash=1&hPassword=undefined`

### CSRF (verified)

`POST_CSRF` endpoints require **`csrf_token` as a form field** — not a header:

| Attempt | Result |
|---|---|
| no token | 302 |
| `CsrfToken:` header | 302 |
| `X-CSRF-Token:` header | 302 |
| `csrf_token=<token>` form field | 200 `{"ret":0,"msg":"…"}` |

The token is the `token` value from the login response.

### What the SPA session can do

`capabilities_status_web_app.cgi` returns **150 `authorizedcgi` entries**, including:

- `wlan_config_web_app.cgi?setwifi`, `?do_config_glb`, `?do_config_glb11ac`, `?do_config_6gband`,
  `?do_config_mlo`, `?OptimizeNetwork`, `?pbc`, `?pin_get`, `?wps_status`
- `wlan_config_guest_web_app.cgi?ConfigWhwGuest`
- `troubleshooting_web_app.cgi?ping`, `?dnsrestest`, `?latencytest`, `?dspacketloss`,
  `?dsthroughputtest`, `?usthroughputtest`, `?port_mirror`
- `speed_test_tr143_web_app.cgi?start_download|start_upload|start_latency`
- `storage_web_app.cgi?ls`, `usb_web_app.cgi?import|export`
- `device_home_nw_client_status_web_app.cgi` (authorised, but returns an empty body — no data)
- `statistics_status_web_app.cgi`, `sta_info2_web_app.cgi`, `whw_beacon_mode_app_web_app.cgi`

**Not** authorised: `lan_ipv4_web_app.cgi` — the LAN/DHCP configuration writer. This is the
firmware's own restriction, not a login artefact. Subnet and pool changes are not possible from
any session.

### What it cannot do

`dhcpv4_server_status_app.cgi`, `device_status_app.cgi` and `wlan_list_app.cgi` all return
`{"result":-1,"reason":403}` under an SPA session — the legacy family is only reachable with
the legacy session. This is why the Home Assistant integration stays on `login_app.cgi`: the
reservation services depend on it.
