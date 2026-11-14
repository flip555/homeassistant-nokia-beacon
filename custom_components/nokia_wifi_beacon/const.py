"""Constants for the Nokia WiFi Beacon integration."""

DOMAIN = "nokia_wifi_beacon"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

DEFAULT_HOST = "192.168.1.1"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30

WS_PORT = 8099
WS_SESSION_TIMEOUT = "1800"

# HTTP request timeout (seconds)
REQUEST_TIMEOUT = 10
# How often to retry the websocket after a drop
WS_RECONNECT_DELAY = 15

# legacy CGI endpoints (the only family reachable from a script)
EP_DEVICE_STATUS = "device_status_app.cgi"
EP_CAPABILITIES = "get_devmap_cap_status_app.cgi"
EP_DHCP_STATUS = "dhcpv4_server_status_app.cgi"
EP_LAN_IPV4 = "lan_ipv4_app.cgi"
EP_WLAN_LIST = "wlan_list_app.cgi"
EP_WAN_LIST = "wan_list_app.cgi"
EP_WAN_STATUS = "wan_internet_status_app.cgi"
EP_PORTMAPS = "portmaps_status_app.cgi"
EP_UPNP = "upnp_status_app.cgi"
EP_LED = "ledctrl_status_app.cgi"
EP_CONGESTION = "network_optimize_status_app.cgi"
EP_LOGIN = "login_app.cgi"
EP_WS_SESSION = "websoc_session_app.cgi"

# websocket events
EV_ALL_DEVICES = "AllDeviceInfo"
EV_DEVICE_UPDATE = "DeviceStatusUpdate"
EV_NEW_DEVICE = "NewDeviceAdded"
EV_WIFI_ASSOC = "Wifi_Associated_Devices_Update"
EV_SSID_INFO = "SSIDInfo"
EV_MESH = "MeshNetwork"
