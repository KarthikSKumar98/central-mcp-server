from pycentral.new_monitoring import WLAN as MonitoringWLAN

from models import WLAN, WLANThroughputSample


def get_all_wlans(
    central_conn, site_id=None, serial_number=None, filter_str=None, sort=None
):
    """Fetch all WLANs from the Central API, handling pagination automatically."""
    return MonitoringWLAN.get_all_wlans(
        central_conn,
        site_id=site_id,
        serial_number=serial_number,
        filter_str=filter_str,
        sort=sort,
    )


def clean_wlan_data(wlans):
    """Convert raw WLAN API dicts to WLAN Pydantic models."""
    return [WLAN(**wlan) for wlan in wlans if isinstance(wlan, dict)]


def clean_wlan_stats_data(raw_stats):
    """Flatten throughput-trends API response into standardized throughput models.

    Converts the nested graph structure into a flat list of per-sample models,
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
        result.append(
            WLANThroughputSample(
                timestamp=sample.get("timestamp"),
                tx=values.get("tx"),
                rx=values.get("rx"),
            )
        )
    return result
