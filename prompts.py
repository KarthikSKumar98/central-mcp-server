from typing import Literal

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register prompt tools with the MCP server."""

    @mcp.prompt
    def network_health_overview() -> str:
        """Full network health overview using a tool-response-only workflow."""
        return """
Provide a full network health overview by following these steps:

1. Call `central_get_summary` to get all sites with health scores and device/client/alert counts.
2. Prioritize up to 3 sites for deeper review where any of these are true: health < 80, critical_alerts > 0, or total_alerts > 5.
3. If prioritized sites exist, call `central_get_sites` once with site_names=["<site A>", "<site B>", "<site C>"] (maximum 3 names).
4. For each prioritized site, call `central_get_alerts` with site_id=<site_id>, status="Active", limit=20 to capture current high-impact issues.
5. If no prioritized sites exist, skip steps 3-4 and summarize directly from `central_get_summary`.
6. Summarize with these sections:
   - Network snapshot: total sites, healthy/fair/poor counts, total clients/devices, total alerts.
   - Priority sites: health score, critical/total alerts, and key signals from detailed data.
   - Overall assessment based strictly on tool output.
   Do not infer remediation steps; direct corrective actions to Central.
        """.strip()

    @mcp.prompt
    def troubleshoot_site(site_name: str) -> str:
        """Deep-dive troubleshooting workflow for a specific site."""
        return f"""
Troubleshoot the site "{site_name}" by following these steps:

1. Call `central_get_summary` to verify the site name and get its site_id and current health score.
2. Call `central_get_sites` with site_names=["{site_name}"] to get detailed site metrics.
3. Call `central_get_alerts` with the site_id and status="Active" to get all active alerts. Prioritize by severity (Critical > High > Medium > Low).
4. Call `central_get_devices` with the site_id to get all devices at the site.
5. Call `central_get_events_count` with site_id=<site_id>, time_range="last_1h", response_mode="compact" to identify dominant event types.
6. If total > 0, call `central_get_events` with site_id=<site_id>, time_range="last_1h", and the top event_id and category filters from step 5.
7. Summarize: site health, active alert breakdown by category and severity, device status overview, and dominant event patterns from the last hour. Do not provide recommendations; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def client_connectivity_check(mac_address: str) -> str:
        """Investigate one client's connectivity using client, site, device, and event evidence."""
        return f"""
Check connectivity for the client with MAC address "{mac_address}" using evidence-first steps:

1. Call `central_find_client` with mac_address="{mac_address}".
   If the response says the client is not found, report that clearly and stop.
2. From the client response, capture: status, connection_type, site_id, connected_device_serial, vlan_id, last_seen_at, and wireless fields (wlan_name, wireless_band, wireless_channel) when present.
3. If client status is "Failed" or "Disconnected", treat it as a disconnect state.
   If last_seen_at is present, use it as the disconnect anchor and create an investigation window around it:
   - start_time = last_seen_at minus 2 hours (RFC 3339)
   - end_time = last_seen_at plus 30 minutes (RFC 3339)
   If last_seen_at is missing, use time_range="last_24h" as fallback for disconnect-state analysis.
4. If site_id is present, call `central_get_alerts` with site_id=<site_id>, status="Active", category="Clients", limit=20.
   If client status is "Failed" or "Disconnected", also call `central_get_alerts` with site_id=<site_id>, status="Cleared", category="Clients", sort="updatedAt desc", limit=50, then prioritize alerts whose createdAt/updatedAt timestamps are closest to (or just before) last_seen_at.
   If site_id is missing, skip this step and explicitly state that site-scoped alerts could not be queried.
5. If connected_device_serial is present, call `central_find_device` with serial_number=<connected_device_serial>.
   If connected_device_serial is missing, skip this step and state that connected-device health could not be verified.
6. If site_id is present, map connection_type to events context_type:
   - Wireless -> WIRELESS_CLIENT
   - Wired -> WIRED_CLIENT
   If client status is "Failed" or "Disconnected", call `central_get_events_count` with site_id=<site_id>, context_type=<mapped type>, context_identifier="{mac_address}", response_mode="compact", and:
   - start_time/end_time from step 3 when last_seen_at is available, or
   - time_range="last_24h" fallback when it is not.
   If total > 0, call `central_get_events` with the same context and same time bounds, plus top event_id/category filters from the count output (limit=20).
   If client status is "Connected", call `central_get_events_count` with site_id=<site_id>, context_type=<mapped type>, context_identifier="{mac_address}", time_range="last_24h", response_mode="compact" and summarize that 24-hour event-count output.
   If connection_type is missing or unmapped, skip event calls and state why.
7. Summarize with these sections:
   - Client snapshot: status, connection type, VLAN/WLAN details, connected device serial/name.
   - Disconnect anchor: last_seen_at and the investigation window used (or why unavailable).
   - Site signals: active/cleared client-category alerts near the disconnect window (or why unavailable).
   - Device signals: connected device status/site/firmware (or why unavailable).
   - Recent client events:
     - Failed/Disconnected clients: top event drivers around disconnect window.
     - Connected clients: last 24-hour event counts from `central_get_events_count`.
   Use only tool output. Do not infer root cause or provide remediation steps; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def investigate_device_events(
        serial_number: str, time_range: str = "last_1h"
    ) -> str:
        """Investigate recent events for a specific device to diagnose issues."""
        return f"""
Investigate recent events for device with serial number "{serial_number}" over the {time_range} window:

1. Call `central_find_device` with serial_number="{serial_number}" to confirm the device exists and get its site_id and device_type. If not found, report the serial number could not be located and stop.
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

1. Call `central_get_summary` to verify the site name and get its site_id.
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

1. Call `central_get_summary` to verify the site name and get its site_id.
2. Call `central_get_clients` with site_id=<site_id> and status="Failed" to get all failed clients.
3. If no failed clients are found, report the site is clean.
4. Collect the unique connected_device_serial values from the failed clients (up to 5 unique serials). Call `central_find_device` once per unique serial to check device health — do not call it multiple times for the same serial.
5. Call `central_get_alerts` with site_id=<site_id> and category="Clients" to check for site-level client alerts.
6. Summarize: number of failed clients, connection types affected (wired vs wireless), common failure patterns, and related device/site alerts from available Central data. Do not infer root causes; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def site_client_overview(site_name: str) -> str:
        """Overview of all client connectivity at a site, broken down by type and status."""
        return f"""
Provide a client connectivity overview for site "{site_name}":

1. Call `central_get_summary` to verify the site name and get its site_id.
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

1. Call `central_get_summary` to verify the site name and get its site_id.
2. Normalize the requested type for `central_get_devices`: "Access Point" -> ACCESS_POINT, "Switch" -> SWITCH, "Gateway" -> GATEWAY.
3. Call `central_get_devices` with site_id=<site_id> and normalized device_type to list all matching devices.
4. Call `central_get_alerts` with site_id=<site_id> and device_type using display values ("Access Point", "Switch", "Gateway", "Bridge") to get relevant active alerts.
5. For up to 3 devices that have associated alerts, call `central_get_events_count` with site_id=<site_id>, context_type=<normalized device type>, context_identifier=<serial_number>, time_range="last_1h", response_mode="compact".
6. For each device from step 5 where total > 0, call `central_get_events` with the same context and the top event_id and category filters from the count output.
7. Summarize: total device count, provisioned vs unprovisioned, active alert breakdown by severity, and devices with high event activity from tool output only. Do not provide remediation steps; direct remediation to Central.
        """.strip()

    @mcp.prompt
    def top_event_drivers(site_name: str, time_range: str = "last_24h") -> str:
        """Identify dominant event drivers at a site and pull supporting evidence."""
        return f"""
Identify top event drivers at site "{site_name}" for {time_range}:

1. Call `central_get_summary` and resolve site_id for "{site_name}".
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

1. Call `central_get_summary` to get all sites with their site_ids and alert counts.
2. Sort sites by critical_alerts descending. For the top 5 sites with critical_alerts > 0, call `central_get_alerts` with the site_id and status="Active". Skip sites with critical_alerts = 0.
3. From the returned alerts, filter to Critical severity only. Group by site and category.
4. Summarize: total critical alert count across the network, top affected sites, most common alert names by category.
        """.strip()

    @mcp.prompt
    def wlan_health_check(wlan_name: str, time_range: str = "last_24h") -> str:
        """Check the configuration and throughput health of a specific WLAN (SSID)."""
        return f"""
Check the health of WLAN "{wlan_name}" over {time_range}:

1. Call `central_get_wlans` with wlan_name="{wlan_name}" to get WLAN configuration (band, security, VLAN, status).
2. Call `central_get_wlan_stats` with wlan_name="{wlan_name}" and time_range="{time_range}" to get throughput trends. Interpret tx as transmitted throughput and rx as received throughput, both in bits per second.
3. Summarize: WLAN configuration details, throughput trend (tx/rx over time, in bits per second), and whether throughput is stable or degrading.
4. If throughput data is absent or all-null, note the WLAN may be unused or the name may be incorrect.
        """.strip()

    @mcp.prompt
    def compare_site_health(site_names: list[str]) -> str:
        """Compare health metrics across multiple sites side by side."""
        sites_str = ", ".join(f'"{s}"' for s in site_names)
        return f"""
Compare health across sites: {sites_str}

1. Call `central_get_summary` to verify all site names and get their site_ids and health scores.
2. Call `central_get_sites` with site_names={list(site_names)} to get detailed metrics for each site.
3. For each site, call `central_get_alerts` with the site_id and status="Active" to get active alert counts by severity.
4. Present a side-by-side comparison table: site name, health score, device count, client count, alert breakdown (Critical/High/Medium/Low).
5. Rank sites from worst to best health.
        """.strip()
