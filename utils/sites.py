import re

from constants import SITE_LIMIT
from models import SiteData, SiteMetrics
from utils.common import paginated_fetch


def fetch_site_data(
    central_conn, site_names: list[str] | None = None
) -> dict[str, SiteData]:
    """Fetch site health, device health, and client health data on one connection.

    When site_names are provided, filtering is pushed upstream via OData so
    all three endpoint calls request only the targeted sites.

    Args:
        central_conn: Central API connection object
        site_names: Optional list of exact site names to filter server-side.

    Returns:
        Dictionary of site names to normalized SiteData objects.

    """
    endpoints = [
        "network-monitoring/v1/sites-health",
        "network-monitoring/v1/sites-device-health",
        "network-monitoring/v1/sites-client-health",
    ]
    site_filter = _build_site_name_filter(site_names)
    additional_params = {"filter": site_filter} if site_filter else None

    results = [
        paginated_fetch(
            central_conn,
            endpoint,
            SITE_LIMIT,
            additional_params=additional_params,
        )
        for endpoint in endpoints
    ]

    return process_site_health_data(*results)


def _build_site_name_filter(site_names: list[str] | None) -> str | None:
    """Return an OData siteName filter, or None when no valid names are provided."""
    if not site_names:
        return None

    normalized = [name.strip() for name in site_names if name and name.strip()]
    if not normalized:
        return None

    escaped_names = [name.replace("'", "''") for name in normalized]
    values = ", ".join(f"'{name}'" for name in escaped_names)
    return f"siteName in ({values})"


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
            processed_sites[site["siteName"]].metrics.devices["details"] = (
                groups_to_map(site["deviceTypes"])
            )

    for site in client_health:
        if site["siteName"] in processed_sites:
            processed_sites[site["siteName"]].metrics.clients["details"] = (
                groups_to_map(site["clientTypes"])
            )

    return processed_sites


def transform_to_site_data(site_raw: dict) -> SiteData:
    """Transform raw Central API data to standardized SiteData model."""
    health_obj = groups_to_map(site_raw.get("health", {}))
    score = compute_health_score(health_obj)
    if score is not None:
        health_obj["summary"] = score
        health_obj.pop("total", None)

    devices_obj = groups_to_map(site_raw.get("devices", {}))

    metrics = SiteMetrics(
        health=health_obj,
        devices={"summary": devices_obj},
        clients={"summary": groups_to_map(site_raw.get("clients", {}))},
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

            name = _to_snake_case_key(item.get("name"))
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
        flat_dict = {}
        for key, value in obj.items():
            normalized_key = _to_snake_case_key(key)
            if normalized_key is None:
                continue
            flat_dict[normalized_key] = value
        return flat_dict

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
        flat["total"] = total

    return flat


def _groups_list_to_dict(groups: list) -> dict:
    """Convert list of {name, value/count} to dict."""
    return {
        _to_snake_case_key(g.get("name")): g.get("value", g.get("count"))
        for g in groups
        if _to_snake_case_key(g.get("name")) is not None
    }


def _to_snake_case_key(value):
    """Normalize Central group labels to snake_case output keys."""
    if not isinstance(value, str):
        return value

    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", normalized).strip("_")
    return normalized.lower() or None


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_health_score(health_obj: dict) -> int | None:
    """Compute a weighted health score from Central Poor/Fair/Good counts.

    Central may omit zero-value health buckets, so treat missing Poor/Fair/Good
    keys as zero when at least one bucket is present. If none of the expected
    health buckets exist, return None to signal that no health distribution was
    provided.
    """
    weights = {"poor": 0, "fair": 0.5, "good": 1}
    if not any(key in health_obj for key in weights):
        return None

    return round(
        sum(health_obj.get(key, 0) * weight for key, weight in weights.items())
    )
