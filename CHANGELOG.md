# Changelog

All notable changes to this project will be documented in this file.

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
