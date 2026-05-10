# Changelog

All notable changes to this project will be documented in this file.

## [0.1.6] - 2026-05-11

### New Tools
- `central_run_network_test` — initiate ping, traceroute, or HTTPS reachability tests on CX/AOS-S/gateway devices and poll for results
- `central_run_show_commands` — execute read-only `show` commands on CX/AOS-S/gateway devices and return structured output
- `central_bounce_port` — bounce a switch port or toggle PoE on CX/AOS-S/gateway devices, gated by MCP elicitation confirmation; approval message surfaces connection-loss warnings, neighbour/connected-device details, current PoE status, and link speed

### Features
- Added `DIAGNOSTIC` and `DESTRUCTIVE` `ToolAnnotations` constants in `tools/__init__.py` for non-read-only tool classification
- Added `TroubleshootingResult` Pydantic model in `models.py` with `raw_output` field for ping/traceroute output capture
- Added troubleshooting limit/poll constants to `constants.py`
- Added `fetch_device_interfaces` and `select_interfaces_for_ports` helpers in `utils/troubleshooting.py`
- Added speed formatting utility for port-bounce approval messages

### Tests
- Added `tests/test_troubleshooting.py` covering `central_run_network_test`, `central_run_show_commands`, and `central_bounce_port`: parameter validation, unsupported family rejection, unknown port detection, decline/cancel flows, successful port and PoE bounce, HTTPS CX polling via `get_http_test_result`, and ping/traceroute `include_raw_output=True` initiation
- Added `tests/integration/test_troubleshooting_live.py` with auto-discovery against a live Central instance
- Updated fixtures to use bare model numbers (e.g. `"6300M"`) matching Central API responses

### Documentation
- Added Troubleshooting Tools section to `README.md` and `README.pypi.md`
- Added Destructive Operations section to `INSTRUCTIONS.md` describing the confirmation workflow and `central_bounce_port` usage guidelines
- Refreshed README AI assistant query examples and command descriptions
- Clarified network-monitoring usage guidelines in `INSTRUCTIONS.md`

### Maintenance
- Bumped `pycentral` to `2.0a19`
- Removed development-branch step from publish workflow
- Gitignored `fastmcp-docs.md`, `mcp.json`, `.agents/`, and `scripts/fetch_fastmcp_docs.py`

### Release
- Bumped package version to `0.1.6` in `pyproject.toml` and `uv.lock`

---

## [0.1.5] - 2026-05-06

### Features
- Updated `AccessPoint` model to match new `get_all_aps` API response structure — now includes `client_count`, `last_reboot_reason`, and `public_ipv4` fields with camelCase validation aliases (`clientCount`, `lastRebootReason`, `publicIpv4`)
- Added human-readable translation for `last_reboot_reason` on `AccessPoint` — Central reboot codes (e.g. `COLD_HW_RESET`, `POWER_LOSS`, `SOFTLOCKUP`) are mapped to descriptive strings via an internal `_REBOOT_REASON_MAP` covering 35+ codes; unknown codes pass through unchanged

### Refactoring
- Removed deprecated `uptime_in_millis` and `notes` fields from `AccessPoint` to match the trimmed Central payload
- Simplified `AccessPoint.from_api()` normalization — dropped explicit `buildingId`/`floorId` pop calls (silently ignored by the model now) and removed the `OFFLINE`-branch `uptimeInMillis` clearing; `lastSeenAt` blanking for `ONLINE` APs is retained

### Tests
- Updated `tests/test_ap_monitoring.py` raw fixture to reflect new payload shape (adds `partNumber`, `ipv4`/`ipv6`, `macAddress`, `cpuUtilization`, `memoryUtilization`, `powerConsumption`, `clientCount`, `lastRebootReason`, `publicIpv4`)
- Added regression tests for reboot-reason mapping: known key translated, unknown key passed through unchanged
- Replaced uptime-exclusion test with `test_get_aps_offline_payload_keeps_last_seen_at`; asserted removal of `uptime_in_millis` and `notes` from serialized output

### Release
- Bumped package version to `0.1.5` in `pyproject.toml` and `uv.lock`

### Maintenance
- Removed stale references to the `development` branch: updated `.github/pull_request_template.md`, `CONTRIBUTING.md`, and `.github/workflows/ci.yml` to reflect the current `main`-only merge flow

---

## [0.1.4.2] - 2026-04-29

### Features
- Added `MCP_TRANSPORT` environment variable to select transport mode (`stdio`, `streamable-http`, or `sse`); defaults to `stdio`
- Added `MCP_HOST` (default `127.0.0.1`) and `MCP_PORT` (default `8000`) environment variables for HTTP transport binding
- Server entry point (`run()`) and `__main__` block now honour `MCP_TRANSPORT` — set the variable and restart to switch modes with no code changes

### Refactoring
- Removed duplicate transport logic from `__main__` block; it now delegates to `run()`

### Documentation
- Added HTTP transport setup section to `README.md` and `README.pypi.md` with step-by-step instructions, environment variable reference table, and MCP client connection examples

---

## [0.1.4.1] - 2026-04-10

### Bug Fixes
- Fixed site health scoring so `central_get_summary` and `central_get_sites` no longer return `null` health for valid Central payloads that omit zero-value groups or use flat `Poor`/`Fair`/`Good` keys

### Tests
- Added regression coverage for site health normalization and scoring across both summary and detailed site tool paths
- Updated live AP monitoring and client integration tests to better match current Central behavior and avoid brittle failures when live data is absent

### Release
- Bumped package version to `0.1.4.1` in `pyproject.toml` and `uv.lock`

---

## [0.1.4] - 2026-04-09

### New Tools
- `central_get_aps` — filtered AP inventory with OData filtering by site, status, model, firmware, deployment, and cluster
- `central_get_ap_statistics` — AP CPU, memory, and power statistics over a configurable time range
- `central_get_ap_wlans` — WLANs active on a specific AP with optional online/offline filtering
- `central_get_wlans` — WLAN configurations from Central with optional SSID name filtering
- `central_get_wlan_stats` — throughput statistics (tx/rx time-series) for a specific WLAN over a time range

### New Models
- `AccessPoint` — full AP data model with `from_api()` normalization and `to_mcp_dict()` serialization
- `AccessPointStatistics` — AP statistics model with graph-data flattening
- `WLAN` — wireless network configuration model with alias choices for camelCase API fields
- `WLANThroughputSample` — standardized throughput data model for WLAN stats output

### New Prompts
- `wlan_health_check` — SSID configuration and throughput trend analysis using `central_get_wlans` and `central_get_wlan_stats`

### Prompt Improvements
- All prompts updated to call `central_get_summary` instead of `central_get_site_name_id_mapping`
- `network_health_overview`: added `central_get_alerts` for priority sites; skips detail steps when all sites are healthy
- `troubleshoot_site`: added event investigation steps using `central_get_events_count` and `central_get_events`
- `client_connectivity_check`: overhauled with evidence-first workflow — disconnect anchor from `last_seen_at`, cleared client alerts, per-client event history using `central_get_events_count`/`central_get_events`
- `failed_clients_investigation`: deduplicates `central_find_device` calls across shared connected devices
- `device_type_health`: limits event investigation to top 3 alerted devices instead of all
- `critical_alerts_review`: focuses on top 5 sites by `critical_alerts` count instead of all sites

### Bug Fixes
- Fixed `central_get_ap_statistics` to correctly flatten graph-format response data
- Fixed `central_get_ap_wlans` to handle empty WLAN result sets without error
- Wrapped all tool domains (alerts, clients, devices, events, sites) in `try/except` for consistent error handling via `format_tool_error`

### Constants & Utilities
- Added `WLAN_LIMIT = 100` and `TIME_RANGE` literal type to `constants.py`
- Added `utils/wlans.py` with `clean_wlan_data` and `clean_wlan_stats_data` helpers

### Tests
- Added `tests/test_wlans.py` and `tests/test_ap_monitoring.py` with unit test coverage for all new tools
- Added `tests/integration/test_wlans_live.py` and `tests/integration/test_ap_monitoring_live.py`
- Added `tests/test_tools_structure.py` to validate tool registration and annotations
- Expanded `tests/test_sites.py` and `tests/test_utils_sites.py` for site name filtering

### Documentation
- Updated `INSTRUCTIONS.md` to reference `central_get_summary` and add AP-specific tool guidance
- Updated README with WLAN and AP monitoring tools in the tools table and architecture diagram
- Bumped package version to `0.1.4` in `pyproject.toml`

---

## [0.1.3] - 2026-04-02

### Features
- Added async API concurrency control across tools using a shared lifecycle semaphore (`API_CONCURRENCY_LIMIT`) and `api_context()` wrapper
- Added `DYNAMIC_TOOLS` config flag to make `CodeMode` optional at startup
- Enhanced events workflows:
  - `central_get_events` now supports site-first defaults (`site_id` required, `context_type="SITE"` default, optional `context_identifier` for non-site contexts)
  - Added OData event filters (`event_id`, `category`, `source_type`) for targeted event retrieval
  - Added `response_mode` to `central_get_events_count` with a compact ranked output for faster filter discovery
  - Added compact event response models and helper transforms for LLM-friendly event triage

### Refactoring
- Standardized filter construction across tools with shared `build_filters()` helper
- Migrated tools to async-safe execution with `asyncio.to_thread(...)` for blocking Central SDK calls
- Updated event models to use normalized field names with aliases for cleaner schema handling

### Tests
- Expanded test coverage for events v2 input/response behavior and compact mode flows
- Added tests for dynamic tool/code mode behavior and asyncio-aware setup changes
- Added coverage for configuration updates including new dynamic tool settings

### CI
- Added `generate-release-pr.yml` to create release PR branches from `development`
- Added `publish-release.yml` to automate release tagging, GitHub Release creation, build, TestPyPI publish, and PyPI publish

### Documentation
- Updated event investigation guidance in `INSTRUCTIONS.md` and prompt templates for site-first usage
- Improved site/event tool docstrings and workflow notes in repository docs

### Maintenance
- Added release helper scripts:
  - `.github/scripts/generate_changelog.py`
  - `.github/scripts/extract_changelog_entry.py`
- Updated Ruff settings and `.gitignore` for release automation support
- Bumped package version to `0.1.3` in `pyproject.toml`

---

## [0.1.2] - 2026-03-30

### New Features
- `central_get_devices` now supports filtering by device status (`ONLINE`/`OFFLINE`)
- `central_get_sites` now includes a `critical_alerts` count in the site summary response

### Bug Fixes
- Fixed server not closing the Central API connection on shutdown
- Fixed `total_devices` and `total_clients` errors in `central_get_site_name_id_mapping` due to incorrect paramater

### Refactoring
- Removed `retry_central_command` wrapper — all tools now call `conn.command()` directly with explicit non-200 status checks, matching PyCentral's internal behaviour and removing inconsistent retry logic
- Replaced `utils.py` with a domain-specific `utils/` package; common helpers separated from domain transforms
- Added `constants.py` for shared constant values used across tools
- Added `compute_health_score`, `format_tool_error`, and `format_rfc3339` helpers to reduce duplication across tools
- Moved `prompts.py` from `tools/` to project root — it defines MCP prompt definitions, not resource-domain tools

### Tests
- Comprehensive unit tests added for all tools: alerts, clients, devices, events, sites, central_service
- Unit tests added for all `utils` helpers: `paginated_fetch`, `compute_time_window`, `clean_device_data`, `clean_client_data`, `clean_alert_data`, `clean_event_filters`, `transform_to_site_data`, `groups_to_map`, `process_site_health_data`
- Error-path tests (non-200 responses) added for `paginated_fetch`, alerts, and events tools
- Optional integration tests added for live tool testing against a real Central instance

### CI
- Ruff linting configuration added to `pyproject.toml`
- GitHub Actions workflow added to run ruff and pytest on PRs targeting `development` and `main`

### Documentation
- `CONTRIBUTING.md` added with project contribution guidelines and utils structure overview
- Python version and license badges added to `README.md`
- Python version classifiers added to `pyproject.toml`
- Improved accuracy and prompt text in `INSTRUCTIONS.md`
- Updated docstrings for `central_get_devices` for accuracy
- Removed stale files: `.vscode/mcp.json` and unused screenshot

---

## [0.1.0] - 2026-03-23

### New Tools
- `central_get_sites` — detailed health metrics, device/client/alert summaries, and location metadata per site
- `central_get_site_name_id_mapping` — lightweight overview of all sites with health scores and counts
- `central_get_devices` — device inventory with filtering by site, type, model, and status
- `central_get_clients` — client inventory with filtering by site and SSID
- `central_get_alerts` — active alerts with filtering by site, severity, and type
- `central_get_events` — event log with filtering by site and type

### Features
- FastMCP integration with stdio and SSE transport support
- OIDC credential loading from environment variables, `.env`, and `~/.config/central-mcp-server/.env`
- Connection verification at startup via `verify_connection()`
- Cursor-based and offset-based pagination via `paginated_fetch()`
- OData filter builder with field validation for device and client queries
- Site health scores sorted by priority in `central_get_site_name_id_mapping`
- `CodeMode` transform applied — tools return structured code blocks

### Documentation
- Architecture diagram (`architecture.svg`)
- MCP client configuration examples for Claude Desktop and GitHub Copilot
- Network monitoring assistant instructions (`INSTRUCTIONS.md`) injected at server startup
- Health score interpretation thresholds (Poor/Fair/Good) documented in server instructions
- `CODEOWNERS` file added
