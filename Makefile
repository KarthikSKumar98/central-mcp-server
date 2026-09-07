.PHONY: help test tool-budget verify-live verify selection-eval-dry selection-eval

help:
	@echo "Targets:"
	@echo "  make test         Run mock/unit tests (no live Central connection)"
	@echo "  make tool-budget  Print tool description and input-schema token estimates"
	@echo "  make verify-live  Per-release gate: run live integration tests against the real tenant"
	@echo "  make verify       Full pre-release gate: mock tests + live tests"
	@echo "  make selection-eval-dry  Validate selection-eval catalogs and cases offline"
	@echo "  make selection-eval      Refresh fold catalog and run live selection evaluation"
	@echo ""
	@echo "verify-live requires Central credentials in the environment or a root .env file"
	@echo "(CENTRAL_BASE_URL, CENTRAL_CLIENT_ID, CENTRAL_CLIENT_SECRET) — same path as the"
	@echo "deployed v0.1.8 server. Missing credentials FAIL the gate (they do not skip)."

# Mock/unit tests — deselects the live integration suite. Never needs credentials.
test:
	uv run pytest tests/ -v -m "not integration"

tool-budget:
	uv run python scripts/measure_tool_tokens.py

# Per-release verification gate against the live Central environment the
# published server runs against. CENTRAL_LIVE_REQUIRED turns missing-credential
# skips into hard failures so an un-credentialed run cannot masquerade as a pass.
verify-live:
	CENTRAL_LIVE_REQUIRED=1 uv run pytest tests/integration/ -v -m integration

# Full gate: mock suite must be green, then the live suite must pass.
verify: test verify-live

selection-eval-dry:
	uv run python evals/selection/run_eval.py --dry-run

selection-eval:
	uv run python evals/selection/snapshot_catalog.py --repo . --out evals/selection/catalogs/fold.json
	uv run python evals/selection/run_eval.py
