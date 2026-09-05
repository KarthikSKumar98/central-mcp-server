---
title: "Capability Reference: Supported APIs & Features"
description: "What the Central MCP server can do, organized by capability category — sites, devices, APs, switches, gateways, WLANs, clients, alerts, events, and live troubleshooting — and which HPE Aruba Networking Central API families each category uses."
keywords: ["Central MCP capabilities", "supported APIs", "Aruba Central MCP tools", "network monitoring MCP", "Central API coverage", "MCP tool reference", "HPE Aruba AI tools", "what can Central MCP do"]
---

# Capability Reference

This page lists what the Central MCP server can do, grouped by capability category rather than
individual API endpoints. Each category names the MCP tools that power it and the Central API
family they call. For real example questions per area, see
[What You Can Ask](what-you-can-ask.md).

**Current as of v0.2.0.** This reference is updated with every release.

## At a glance

| Category | What you can ask about | Tools | Central API family |
|---|---|---|---|
| [Sites & network health](#sites--network-health) | Fleet-wide health overview, per-site metrics | 1 | Network Monitoring |
| [Devices](#devices) | Inventory, family detail, and trends | 3 | Network Monitoring |
| [WLANs](#wlans) | Configured WLANs, per-WLAN throughput | 1 | Network Monitoring |
| [Clients](#clients) | Connected/failed clients, exact MAC lookup | 1 | Network Monitoring |
| [Alerts](#alerts) | Active alerts per site, by severity/category | 1 | Network Notifications |
| [Events](#events) | Event records and facets for a site, device, or client | 1 | Network Troubleshooting |
| [Gateway clusters](#gateway-clusters) | Cluster health, resources, and capacity | 1 | Network Monitoring |
| [Live troubleshooting](#live-troubleshooting) | Ping/traceroute-style tests, show commands, port bounce | 3 | Network Troubleshooting |

**12 tools total.** All tools are read-only except `central_bounce_port`, which changes device
state and always asks for your confirmation first.

## Categories

### Sites & network health

Fleet-wide status and per-site drill-down. The usual entry point for any investigation.

- `central_get_sites` — paginated summary or detailed health views; `view` selects the upstream view and `response_format` shapes returned fields.

### Devices

Cross-type device queries when you don't yet know whether something is an AP, switch, or gateway.

- `central_get_devices` — unified inventory and AP/switch/gateway monitoring lists, plus exact serial/name lookup.
- `central_get_device_details` — typed AP, switch, or gateway snapshots with family-specific includes.
- `central_get_device_trends` — bounded family-specific time-series samples.

### WLANs

- `central_get_wlans` — WLAN inventory and optional throughput for an exact WLAN name.

### Clients

- `central_get_clients` — filtered client lists or one exact MAC-address lookup.

### Alerts

- `central_get_alerts` — filtered alerts for a site, by device type, severity, or category.

### Events

- `central_get_events` — `mode="records"` returns events; `mode="facets"` returns count/filter breakdowns.

### Gateway clusters

- `central_get_gateway_cluster` — cluster members and tunnel health with optional resources and capacity trends.

### Live troubleshooting

Live diagnostics executed on Central-managed devices.

- `central_run_network_test` — run a network diagnostic test (e.g. ping) from a device.
- `central_run_show_commands` — run show commands on a device and return the output.
- `central_bounce_port` — bounce ports or toggle PoE. **The only state-changing tool**; always requires your explicit confirmation.

## Scope & limitations

- **New Central only.** The server targets the new HPE Aruba Networking Central REST APIs (`network-monitoring/v1`, `network-notifications/v1`, `network-troubleshooting/v1`). Classic Central APIs are not supported.
- **Monitoring, not configuration.** The server reads live network state. It does not create, modify, or delete Central configuration (the single exception is port bouncing, above).
- **Live data.** Every answer reflects your Central instance at query time; nothing is cached or stored.

Capability coverage grows with each release — see the [CHANGELOG](../CHANGELOG.md) for what each version added.
