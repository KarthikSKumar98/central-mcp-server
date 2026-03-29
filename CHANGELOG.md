# Changelog

All notable changes to this project will be documented in this file.

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
