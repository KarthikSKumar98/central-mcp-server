from typing import Literal

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register prompt tools with the MCP server."""

    @mcp.prompt
    def network_health_overview() -> str:
        """Full network health overview using a tool-response-only workflow."""
        return """
Provide a full network health overview by following these steps:

1. Call `central_get_site_name_id_mapping` to get all sites with health scores, device/client/alert counts.
2. Identify sites with poor or fair health, or notably high alert counts.
3. Call `central_get_sites` with site_names=["<site A>", "<site B>", "<site C>"] for only the highest-priority sites (maximum 3).
4. Summarize per site: health score, device/client/alert totals, and any notable issues.
5. End with an overall network health assessment strictly based on tool outputs. If remediation is needed, direct the user to resolve it in Central.
        """.strip()

    @mcp.prompt
    def troubleshoot_site(site_name: str) -> str:
        """Deep-dive troubleshooting workflow for a specific site."""
        return f"""
Troubleshoot the site "{site_name}" by following these steps:

1. Call `central_get_site_name_id_mapping` to verify the site name and get its site_id and current health score.
2. Call `central_get_sites` with site_names=["{site_name}"] to get detailed site metrics.
3. Call `central_get_alerts` with the site_id and status="Active" to get all active alerts. Prioritize by severity (Critical > High > Medium > Low).
4. Call `central_get_devices` with the site_id to get all devices at the site.
5. Summarize: site health, active alert breakdown by category and severity, and device status overview. Do not provide recommendations; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def client_connectivity_check(mac_address: str) -> str:
        """Investigate a client's connectivity status and the health of their site and connected device."""
        return f"""
Check connectivity for the client with MAC address "{mac_address}":

1. Call `central_find_client` with mac_address="{mac_address}" to get the client's current status and connected device serial number.
2. If found, note the site_id from the response.
3. Call `central_get_alerts` with the site_id and status="Active" to check for site-level issues that may affect the client.
4. Call `central_find_device` with the serial_number of the connected device to check device health.
5. Summarize: client status, connection details (type, VLAN, WLAN if wireless), and related site/device alerts based only on tool output. Do not infer root cause; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def investigate_device_events(
        serial_number: str, time_range: str = "last_1h"
    ) -> str:
        """Investigate recent events for a specific device to diagnose issues."""
        return f"""
Investigate recent events for device with serial number "{serial_number}" over the {time_range} window:

1. Call `central_find_device` with serial_number="{serial_number}" to confirm the device exists and get its site_id and device_type.
2. Map device_type to the matching context_type: ACCESS_POINT → ACCESS_POINT, SWITCH → SWITCH, GATEWAY → GATEWAY.
3. Call `central_get_events_count` with site_id=<site_id>, context_type=<mapped type>, context_identifier="{serial_number}", time_range="{time_range}", response_mode="compact" to discover top event_id/category/source_type values.
4. If total > 0, call `central_get_events` with site_id=<site_id>, context_type=<mapped type>, context_identifier="{serial_number}", time_range="{time_range}", and at least one of the top filters from step 3 (event_id/category/source_type).
5. Summarize: event timeline, dominant event types, and any recurring or critical events from tool output only. Do not recommend actions; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def site_event_summary(site_name: str, time_range: str = "last_1h") -> str:
        """Summarize all events at a site to identify patterns and anomalies."""
        return f"""
Summarize events at site "{site_name}" over the {time_range} window:

1. Call `central_get_site_name_id_mapping` to verify the site name and get its site_id.
2. Call `central_get_events_count` with site_id=<site_id>, time_range="{time_range}", response_mode="compact" to get ranked event_id/category/source_type values.
3. If total > 0, call `central_get_events` with site_id=<site_id>, time_range="{time_range}", and one or more top filters from step 2 to fetch focused event details.
4. Group events by category and name. Highlight any spikes, repeated errors, or critical events.
5. Summarize: total event count, top event types, and notable patterns from tool output only. Do not suggest follow-up actions; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def failed_clients_investigation(site_name: str) -> str:
        """Find and diagnose all failed clients at a site."""
        return f"""
Investigate failed client connections at site "{site_name}":

1. Call `central_get_site_name_id_mapping` to verify the site name and get its site_id.
2. Call `central_get_clients` with site_id=<site_id> and status="Failed" to get all failed clients.
3. If no failed clients are found, report the site is clean.
4. For each failed client (up to 5), call `central_find_device` with the connected device serial number to check device health.
5. Call `central_get_alerts` with site_id=<site_id> and category="Clients" to check for site-level client alerts.
6. Summarize: number of failed clients, connection types affected (wired vs wireless), common failure patterns, and related device/site alerts from available Central data. Do not infer root causes; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def site_client_overview(site_name: str) -> str:
        """Overview of all client connectivity at a site, broken down by type and status."""
        return f"""
Provide a client connectivity overview for site "{site_name}":

1. Call `central_get_site_name_id_mapping` to verify the site name and get its site_id.
2. Call `central_get_clients` with site_id=<site_id> to get all clients at the site.
3. Break down clients by: connection type (Wired vs Wireless), status (Connected vs Failed), and VLAN.
4. For wireless clients, note WLAN distribution and any clients on unusual bands or security types.
5. Summarize: total client count, connected vs failed breakdown, and anomalies based only on tool output. Do not provide recommendations; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def device_type_health(
        site_name: str,
        device_type: Literal["Access Point", "Switch", "Gateway"],
    ) -> str:
        """Health check for all devices of a specific type at a site."""
        return f"""
Check the health of all {device_type} devices at site "{site_name}":

1. Call `central_get_site_name_id_mapping` to verify the site name and get its site_id.
2. Normalize the requested type for `central_get_devices`: "Access Point" -> ACCESS_POINT, "Switch" -> SWITCH, "Gateway" -> GATEWAY.
3. Call `central_get_devices` with site_id=<site_id> and normalized device_type to list all matching devices.
4. Call `central_get_alerts` with site_id=<site_id> and device_type using display values ("Access Point", "Switch", "Gateway", "Bridge") to get relevant active alerts.
5. For devices with associated alerts, call `central_get_events_count` with site_id=<site_id>, context_type=<normalized device type>, context_identifier=<serial_number>, time_range="last_1h", response_mode="compact".
6. Optionally call `central_get_events` with the same context and top filters from count output for detailed evidence.
7. Summarize: total device count, provisioned vs unprovisioned, active alert breakdown by severity, and devices with high event activity from tool output only. Do not provide remediation steps; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def top_event_drivers(site_name: str, time_range: str = "last_24h") -> str:
        """Identify dominant event drivers at a site and pull supporting evidence."""
        return f"""
Identify top event drivers at site "{site_name}" for {time_range}:

1. Call `central_get_site_name_id_mapping` and resolve site_id for "{site_name}".
2. Call `central_get_events_count` with site_id=<site_id>, time_range="{time_range}", response_mode="compact".
3. Select top 3 event_id values and top 2 categories from the compact response.
4. Call `central_get_events` with site_id=<site_id>, time_range="{time_range}", event_id="<id1,id2,id3>", category="<cat1,cat2>".
5. Summarize: dominant event drivers and affected source types based only on tool output. Do not provide troubleshooting actions; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def critical_alerts_review() -> str:
        """Review all active critical alerts across the network."""
        return """
Review all active critical alerts across the network:

1. Call `central_get_site_name_id_mapping` to get all sites with their site_ids and alert counts.
2. For each site with critical_alerts > 0, call `central_get_alerts` with the site_id and status="Active" to get all active alerts.
3. Identify sites with the highest concentration of critical alerts.
4. Filter to Critical severity only. Group by site and category.
5. Summarize: critical alert count across the network, top affected sites, most common alert names by category.
        """.strip()

    @mcp.prompt
    def compare_site_health(site_names: list[str]) -> str:
        """Compare health metrics across multiple sites side by side."""
        sites_str = ", ".join(f'"{s}"' for s in site_names)
        return f"""
Compare health across sites: {sites_str}

1. Call `central_get_site_name_id_mapping` to verify all site names and get their site_ids and health scores.
2. Call `central_get_sites` with site_names={list(site_names)} to get detailed metrics for each site.
3. For each site, call `central_get_alerts` with the site_id and status="Active" to get active alert counts by severity.
4. Present a side-by-side comparison table: site name, health score, device count, client count, alert breakdown (Critical/High/Medium/Low).
5. Rank sites from worst to best health.
        """.strip()
