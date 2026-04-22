from typing import Literal

SITE_LIMIT = 100  # Max number of sites returned per API call
ALERT_LIMIT = 50  # Max number of alerts returned per API call
EVENT_LIMIT = 50  # Max number of events returned per API call
WLAN_LIMIT = 100  # Max number of WLANs returned per API call
APP_LIMIT = 100  # Max number of apps returned per API call
SCOPE_LIMIT = (
    100  # Max number of scope elements (sites, collections) returned per API call
)
API_CONCURRENCY_LIMIT = 5  # Max concurrent outbound Central API calls

TIME_RANGE = Literal[
    "last_1h", "last_6h", "last_24h", "last_7d", "last_30d", "today", "yesterday"
]
