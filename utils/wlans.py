from pycentral.new_monitoring import MonitoringAPs

from constants import WLAN_LIMIT
from models import WLAN


def get_all_wlans(central_conn, site_id=None, filter_str=None, sort=None):
    """Fetch all WLAN pages from the Central API, handling pagination."""
    wlans = []
    total_wlans = None
    next_page = 1
    while True:
        resp = MonitoringAPs.get_wlans(
            central_conn,
            site_id=site_id,
            filter_str=filter_str,
            sort=sort,
            limit=WLAN_LIMIT,
            next_page=next_page,
        )
        if total_wlans is None:
            total_wlans = resp.get("total", 0)
        wlans.extend(resp.get("items", []))
        if len(wlans) >= total_wlans:
            break
        next_page = resp.get("next")
        if not next_page:
            break
        next_page = int(next_page)
    return wlans


def clean_wlan_data(wlans):
    """Convert raw WLAN API dicts to WLAN Pydantic models."""
    return [WLAN(**w) for w in wlans if isinstance(w, dict)]


def clean_wlan_stats_data(raw_stats):
    """Flatten throughput-trends API response into a list of named-field dicts.

    Converts the nested graph structure into a flat list of per-sample dicts,
    pairing each key from ``graph.keys`` with its corresponding value in
    ``graph.samples[].data``. Samples where every value is ``None`` (returned
    for unknown WLANs) are dropped.

    Returns an empty list when the response contains no valid data.
    """
    if not isinstance(raw_stats, dict):
        return []
    graph = raw_stats.get("graph", {})
    keys = graph.get("keys", [])
    samples = graph.get("samples", [])
    result = []
    for sample in samples:
        data = sample.get("data", [])
        values = dict(zip(keys, data))
        if all(v is None for v in values.values()):
            continue
        result.append({"timestamp": sample.get("timestamp"), **values})
    return result
