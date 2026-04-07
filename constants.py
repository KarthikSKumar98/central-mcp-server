from typing import Literal

SITE_LIMIT = 100  # Max number of sites returned per API call
ALERT_LIMIT = 50  # Max number of alerts returned per API call
EVENT_LIMIT = 50  # Max number of events returned per API call
API_CONCURRENCY_LIMIT = 5  # Max concurrent outbound Central API calls

TIME_RANGE = Literal[
    "last_1h", "last_6h", "last_24h", "last_7d", "last_30d", "today", "yesterday"
]