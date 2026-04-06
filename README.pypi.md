# central-mcp-server

![PyPI - Python Version](https://img.shields.io/pypi/pyversions/central-mcp-server)
![PyPI - License](https://img.shields.io/pypi/l/central-mcp-server)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Community MCP server for HPE Aruba Networking Central. This exposes your Central data as tools that AI assistants can query directly.

---

> **WARNING - Unofficial Community Project**
>
> This is **not** an officially supported product of HPE. It is provided as-is, with no warranty or guarantee of fitness for any purpose.
>
> - Review your organization's **corporate device and data policies** before connecting this server to any AI assistant.
> - **Never share credentials** (API secrets, API keys) with AI model providers unless your security policy explicitly permits it.
> - All read operations query live data from your HPE Aruba Networking Central instance. Recommended to test MCP server use in non-production or lab environments where possible before running on production.
---

## Overview

`central-mcp-server` wraps Central REST APIs and exposes them as [MCP (Model Context Protocol)](https://modelcontextprotocol.io) tools. Once configured, AI assistants like Claude or GitHub Copilot can answer questions like:

- *"Which sites have poor health scores right now?"*
- *"Show me all failed wireless clients at HQ in the last 24 hours."*
- *"Show me all online access points at the Chicago office."*
- *"What events happened on switch SW-CORE-01 yesterday?"*

See the [full overview guide](https://developer.arubanetworks.com/new-central/docs/central-mcp-overview) for a deeper look at capabilities, limitations, and how the server works.

---

## Getting Started

### Getting Your Credentials

You need three values to connect this server to Central's REST APIs: `CENTRAL_BASE_URL`, `CENTRAL_CLIENT_ID`, and `CENTRAL_CLIENT_SECRET`.

#### API Gateway Base URL (CENTRAL_BASE_URL)

The API gateway base URL for your Central account (e.g. `https://us5.api.central.arubanetworks.com`).

> For instructions on how to locate your base URL, see [Finding Your Base URL in Central](https://developer.arubanetworks.com/new-central/docs/getting-started-with-rest-apis#finding-your-base-url).

#### API Client Credentials (CENTRAL_CLIENT_ID & CENTRAL_CLIENT_SECRET)

OAuth credentials created through the HPE GreenLake Platform:

1. Log in to your HPE GreenLake account and open **Manage Workspace**.
2. Click **Personal API clients**.
3. Click **Create Personal API client**.
4. Give it a nickname (e.g. `central-mcp-server`) and select your **HPE Aruba Networking Central** instance from the service dropdown.
5. Click **Create personal API client**.
6. Copy both the **Client ID** and **Client Secret** immediately. The platform does not store the secret and it cannot be retrieved later.

> Full guide: [Generating and Managing Access Tokens](https://developer.arubanetworks.com/new-central/docs/generating-and-managing-access-tokens)

---

### Installation

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already — it's the only prerequisite.

**Using an MCP client (Claude Desktop, Claude Code, GitHub Copilot)?**
No install command needed. Jump to [MCP Client Configuration](#mcp-client-configuration) — the client fetches and runs the server automatically via `uvx`.

**Want the server as a persistent CLI tool on your PATH?**

```bash
uv tool install --prerelease=allow central-mcp-server
```

> `--prerelease=allow` is required because this server depends on `pycentral`, which currently only has a pre-release version on PyPI. uv skips pre-releases by default.

See the [full setup guide](https://developer.arubanetworks.com/new-central/docs/central-mcp-setup) for prerequisites, troubleshooting, and step-by-step instructions.

---

### MCP Client Configuration

Replace the placeholder values with your actual credentials in all examples below.

#### Optional: Code Mode Transform (`DYNAMIC_TOOLS`)

`DYNAMIC_TOOLS` is optional and only affects startup behavior:

- Code Mode is enabled only when `DYNAMIC_TOOLS` is set to `true` (case-insensitive).
- Code Mode is disabled when `DYNAMIC_TOOLS` is not set or set to any other value.
- Variable name is strict: use `DYNAMIC_TOOLS` (plural). `DYNAMIC_TOOL` is ignored.

When enabled, the server starts with `CodeMode()` and exposes Code Mode meta-tools to the client. When disabled, the server runs without the transform and exposes the normal registered tool catalog directly. Recommended to use `CodeMode()` when you have multiple MCP servers running to preserve your context window.

#### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "central-mcp": {
      "command": "uvx",
      "args": ["--prerelease=allow", "central-mcp-server"],
      "env": {
        "CENTRAL_BASE_URL": "your-central-base-url",
        "CENTRAL_CLIENT_ID": "your-client-id",
        "CENTRAL_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

See the [Claude Desktop setup guide](https://developer.arubanetworks.com/new-central/docs/central-mcp-claude-desktop-setup) for full steps and troubleshooting.

#### Claude Code

```bash
claude mcp add central-mcp \
  -e CENTRAL_BASE_URL=your-central-base-url \
  -e CENTRAL_CLIENT_ID=your-client-id \
  -e CENTRAL_CLIENT_SECRET=your-client-secret \
  -- uvx --prerelease=allow central-mcp-server
```

See the [Claude Code setup guide](https://developer.arubanetworks.com/new-central/docs/central-mcp-claude-code-setup) for full steps and troubleshooting.

#### GitHub Copilot (VS Code)

Add `.vscode/mcp.json` to your workspace root and add that path to `.gitignore` to keep credentials out of version control:

```json
{
  "servers": {
    "central-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--prerelease=allow", "central-mcp-server"],
      "env": {
        "CENTRAL_BASE_URL": "your-central-base-url",
        "CENTRAL_CLIENT_ID": "your-client-id",
        "CENTRAL_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Add to `.gitignore`:
```
.vscode/mcp.json
```

See the [GitHub CoPilot setup guide](https://developer.arubanetworks.com/new-central/docs/central-github-copilot-setup) for full steps and troubleshooting.

---

## What You Can Ask

Once connected, you can ask your AI assistant questions like:

- *"Give me a health overview of all sites."*
- *"Which sites are in poor health right now?"*
- *"Show me all access points at the Chicago office."*
- *"What critical alerts are active across the network?"*
- *"Find all failed wireless clients at HQ in the last 24 hours."*
- *"What events happened on switch SW-CORE-01 yesterday?"*

See [Central MCP Server in Action]((https://developer.arubanetworks.com/new-central/docs/central-mcp-in-action)) for real query examples across all supported clients.

### Tools

#### Sites
| Tool | Description |
|------|-------------|
| `central_get_sites` | Detailed health metrics for one or more sites (device/client/alert counts, health score) |
| `central_get_site_name_id_mapping` | Lightweight mapping of all site names to IDs and health scores |

#### Devices
| Tool | Description |
|------|-------------|
| `central_get_devices` | Filtered list of devices — filter by type, site, model, serial number, and more |
| `central_find_device` | Look up a single device by serial number or device name |

#### AP Monitoring
| Tool | Description |
|------|-------------|
| `central_get_aps` | Filtered list of access points — filter by site, serial number, status, model, firmware version, deployment, or cluster |
| `central_get_ap_latest_stats` | Latest AP CPU, memory, and power stats for a given AP serial number |

#### Clients
| Tool | Description |
|------|-------------|
| `central_get_clients` | Filtered list of clients — filter by connection type, status, VLAN, WLAN, and more |
| `central_find_client` | Look up a single client by MAC address |

#### Alerts
| Tool | Description |
|------|-------------|
| `central_get_alerts` | Active, cleared, or deferred alerts for a site — filter by device type or category |

#### Events
| Tool | Description |
|------|-------------|
| `central_get_events` | Events for a site, device, or client within a time window |
| `central_get_events_count` | Event count breakdown by type with `response_mode="full"` (counts) or `response_mode="compact"` (ranked event id/name pairs + lists) |

### LLM Workflow for Events

Use this sequence for faster, lower-token event investigations:

1. For site-level queries, call events tools with `site_id` only.
2. For device/client queries, pass `site_id` plus `context_type` and `context_identifier`.
3. Call `central_get_events_count` with `response_mode="compact"` to get ranked `event_names` (each with `event_id` + `event_name`), `source_types`, and `categories`.
4. Pick the top category/source/event name as your likely starting point.
5. Call `central_get_events` with targeted filters (`category`, `source_type`, and/or `event_id`) to fetch detailed records.
6. Use `central_get_events_count` with `response_mode="full"` only when exact per-item counts are required.

### Guided Prompts

The server includes 10 built-in prompts to help AI assistants run common workflows:

| Prompt | Description |
|--------|-------------|
| `network_health_overview` | Full network health overview across all sites |
| `troubleshoot_site` | Deep-dive troubleshooting for a specific site |
| `client_connectivity_check` | Investigate connectivity status for a client by MAC address |
| `investigate_device_events` | Review recent events for a specific device |
| `site_event_summary` | Summarize all events at a site within a time window |
| `failed_clients_investigation` | Find and diagnose all failed clients at a site |
| `site_client_overview` | Overview of client connectivity at a site |
| `device_type_health` | Health check for all devices of a specific type at a site |
| `critical_alerts_review` | Review all active critical alerts across the network |
| `compare_site_health` | Compare health metrics side-by-side across multiple sites |

---

## Dev Setup

```bash
git clone <Github Server URL>
cd central-mcp-server
```

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
uv sync
```

Create `.env` with your credentials:

```
CENTRAL_BASE_URL=your-central-base-url
CENTRAL_CLIENT_ID=your-client-id
CENTRAL_CLIENT_SECRET=your-client-secret
```

Run the server:

```bash
python3 server.py
```

To install and test the package locally before publishing:

```bash
uv tool install .
```
