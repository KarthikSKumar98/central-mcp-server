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

**Current as of v0.1.9.** This reference is updated with every release.

## At a glance

| Category | What you can ask about | Tools | Central API family |
|---|---|---|---|
| [Sites & network health](#sites--network-health) | Fleet-wide health overview, per-site metrics | 2 | Network Monitoring |
| [Device inventory](#device-inventory) | All devices, find one by serial/MAC/name | 2 | Network Monitoring |
| [Access points](#access-points) | AP lists, per-AP detail, radio/port trends | 3 | Network Monitoring |
| [Switches](#switches) | Switch lists, per-switch detail, hardware/interface trends | 3 | Network Monitoring |
| [Gateways](#gateways) | Gateway lists, detail, clusters, capacity trends | 5 | Network Monitoring |
| [WLANs](#wlans) | Configured WLANs, per-WLAN throughput | 2 | Network Monitoring |
| [Clients](#clients) | Connected/failed clients, find one by MAC | 2 | Network Monitoring |
| [Alerts](#alerts) | Active alerts per site, by severity/category | 1 | Network Notifications |
| [Events](#events) | Event history and counts for a site, device, or client | 2 | Network Troubleshooting |
| [Live troubleshooting](#live-troubleshooting) | Ping/traceroute-style tests, show commands, port bounce | 3 | Network Troubleshooting |

**25 tools total.** All tools are read-only except `central_bounce_port`, which changes device
state and always asks for your confirmation first.

## Categories

### Sites & network health

Fleet-wide status and per-site drill-down. The usual entry point for any investigation.

- `central_get_summary` — lightweight overview of every site: health score, device, client, and alert counts.
- `central_get_sites` — detailed metrics for one or more named sites.

### Device inventory

Cross-type device queries when you don't yet know whether something is an AP, switch, or gateway.

- `central_get_devices` — filtered device list (OData v4.0 filter syntax).
- `central_find_device` — locate a single device by serial, MAC, or name.

### Access points

- `central_get_aps` — filtered AP list.
- `central_get_ap_details` — single-AP snapshot including radios and ports.
- `central_get_ap_trends` — time-series trends for an AP, radio, or wired port (throughput, CPU, memory, channel utilization/quality, noise floor, and more).

### Switches

- `central_get_switches` — filtered switch list.
- `central_get_switch_details` — single-switch snapshot.
- `central_get_switch_trends` — time-series trends at hardware or interface scope (CPU, memory, PoE, port throughput, and more).

### Gateways

- `central_get_gateways` — filtered gateway list.
- `central_get_gateway_details` — single-gateway snapshot.
- `central_get_gateway_trends` — time-series trends for a gateway, port, tunnel, or uplink.
- `central_get_gateway_cluster` — cluster snapshot with members and tunnel health.
- `central_get_cluster_capacity_trends` — cluster capacity trends over time.

### WLANs

- `central_get_wlans` — WLANs configured in Central, filterable by name, site, or AP.
- `central_get_wlan_stats` — throughput trends for a specific WLAN.

### Clients

- `central_get_clients` — filtered client list (OData v4.0 filter syntax), including failed clients.
- `central_find_client` — locate a single client by MAC address.

### Alerts

- `central_get_alerts` — filtered alerts for a site, by device type, severity, or category.

### Events

- `central_get_events` — events for a site, device, or client within a time range.
- `central_get_events_count` — event count breakdown for a context without fetching full details.

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
