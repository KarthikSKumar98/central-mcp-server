from typing import Literal

SITE_LIMIT = 100  # Max number of sites returned per API call
ALERT_LIMIT = 50  # Max number of alerts returned per API call
EVENT_LIMIT = 50  # Max number of events returned per API call
WLAN_LIMIT = 100  # Max number of WLANs returned per API call
API_CONCURRENCY_LIMIT = 5  # Max concurrent outbound Central API calls
TROUBLESHOOTING_POLL_MAX_ATTEMPTS = (
    10  # Default poll iterations for async diagnostic tasks
)
TROUBLESHOOTING_POLL_INTERVAL = 15  # Default seconds between polls
BOUNCE_PORTS_MAX = 5  # Max ports per bounce call
SHOW_COMMANDS_MAX = 5  # Max show commands per central_run_show_commands call

TIME_RANGE = Literal[
    "last_1h", "last_6h", "last_24h", "last_7d", "last_30d", "today", "yesterday"
]

# Valid metric strings accepted by pycentral AP trend endpoints (keys of the library's metric maps).
AP_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "cpu-utilization",
    "memory-utilization",
    "power-consumption",
)
RADIO_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "channel-utilization",
    "channel-quality",
    "noise-floor",
    "frames",
)
PORT_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "frames",
    "crc",
    "collisions",
)

# Valid interface_type values for ap throughput trends.
AP_INTERFACE_TYPES: tuple[str, ...] = ("WIRED", "WIRELESS", "LTE")

# --- Switch monitoring (a20) ---
# Deployment literal values for get_all_switches filter
SWITCH_DEPLOYMENT_VALUES: tuple[str, ...] = ("Standalone", "Stack", "VSX")

# --- Gateway monitoring (a20) ---
# Valid metric strings accepted by pycentral gateway trend endpoints.
GATEWAY_TREND_METRICS: tuple[str, ...] = (
    "cpu-utilization",
    "memory-utilization",
    "wan-availability",
    "vpn-availability",
    "hardware-temperature",
)
GATEWAY_PORT_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "frames",
    "frames-errors",
    "frames-packets",
)
GATEWAY_TUNNEL_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "status",
    "dropped-packets",
)
GATEWAY_UPLINK_TREND_METRICS: tuple[str, ...] = (
    "throughput",
    "wan-compression",
    "wan-availability",
)
