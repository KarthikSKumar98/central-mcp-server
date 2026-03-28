from concurrent.futures import ThreadPoolExecutor

from constants import SITE_LIMIT
from models import SiteData, SiteMetrics
from utils.common import paginated_fetch


def fetch_site_data_parallel(central_conn) -> tuple:
    """Fetch site health, device health, and client health data in parallel.

    Args:
        central_conn: Central API connection object

    Returns:
        tuple: (site_health_data, device_health_data, client_health_data)

    """
    endpoints = [
        "network-monitoring/v1/sites-health",
        "network-monitoring/v1/sites-device-health",
        "network-monitoring/v1/sites-client-health",
    ]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(paginated_fetch, central_conn, endpoint, SITE_LIMIT)
            for endpoint in endpoints
        ]
        results = [future.result() for future in futures]

    return process_site_health_data(*results)


def process_site_health_data(site_health, device_health, client_health):
    """Combine site health, device health, and client health data into unified site objects.

    Args:
        site_health: List of site health data
        device_health: List of device health data by site
        client_health: List of client health data by site

    Returns:
        dict: Dictionary of site names to SiteData objects

    """
    processed_sites = {
        site["siteName"]: transform_to_site_data(site) for site in site_health
    }

    for site in device_health:
        if site["siteName"] in processed_sites:
            processed_sites[site["siteName"]].metrics.devices["Details"] = (
                groups_to_map(site["deviceTypes"])
            )

    for site in client_health:
        if site["siteName"] in processed_sites:
            processed_sites[site["siteName"]].metrics.clients["Details"] = (
                groups_to_map(site["clientTypes"])
            )

    return processed_sites


def transform_to_site_data(site_raw: dict) -> SiteData:
    """Transform raw Central API data to standardized SiteData model."""
    health_obj = groups_to_map(site_raw.get("health", {}))
    score = compute_health_score(health_obj)
    if score is not None:
        health_obj["Summary"] = score
        health_obj.pop("Total", None)

    devices_obj = groups_to_map(site_raw.get("devices", {}))

    metrics = SiteMetrics(
        health=health_obj,
        devices={"Summary": devices_obj},
        clients={"Summary": groups_to_map(site_raw.get("clients", {}))},
        alerts=groups_to_map(site_raw.get("alerts", {})),
    )

    location = site_raw.get("location", {}) or {}
    lat = _safe_float(location.get("latitude"))
    lng = _safe_float(location.get("longitude"))

    return SiteData(
        site_id=site_raw.get("id"),
        name=site_raw.get("siteName"),
        address=site_raw.get("address", {}),
        location={"lat": lat, "lng": lng},
        metrics=metrics,
    )


def groups_to_map(obj):
    """Transform an object that either is {"groups":[...], ...} or wraps that as a parent (e.g. {"health": {"groups":[...], "count": ...}}) or is a list of device/client types with nested health groups."""
    if not isinstance(obj, dict) and not isinstance(obj, list):
        return obj

    # Handle list of device/client types
    if isinstance(obj, list):
        result = {}
        for item in obj:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not name:
                continue

            health_obj = item.get("health", {})
            groups = health_obj.get("groups", [])

            if groups:
                result[name] = _groups_list_to_dict(groups)

        return result

    # Handle single object with groups
    if "groups" not in obj:
        for value in obj.values():
            if isinstance(value, dict) and "groups" in value:
                obj = value
                break

    groups = obj.get("groups")
    if not isinstance(groups, list):
        return obj

    flat = _groups_list_to_dict(groups)

    total = obj.get("count") or obj.get("totalCount") or obj.get("total")
    if total is None:
        try:
            total = sum(
                int(v) for v in flat.values() if isinstance(v, (int, float, str))
            )
        except Exception:
            total = None

    if total is not None:
        flat["Total"] = total

    return flat


def _groups_list_to_dict(groups: list) -> dict:
    """Convert list of {name, value/count} to dict."""
    return {
        g.get("name"): g.get("value", g.get("count"))
        for g in groups
        if g.get("name") is not None
    }


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_health_score(health_obj: dict) -> int | None:
    """Compute weighted health score from Poor/Fair/Good counts. Returns None if keys are absent."""
    if all(k in health_obj for k in ["Poor", "Fair", "Good"]):
        return round(
            (health_obj["Poor"] * 0)
            + (health_obj["Fair"] * 0.5)
            + (health_obj["Good"] * 1)
        )
    return None
