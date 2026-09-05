# Contributing to central-mcp-server

Thank you for your interest in contributing. Please read this guide before opening a PR or issue.

---

## Scope

This project wraps **HPE Aruba Networking Central REST APIs** as MCP tools. Contributions must stay within this scope:

- **Central only** not Classic Central
- **v1 API endpoints only**. Due to changing nature of non-GA APIs, only tools build around v1 APIs will be accepted
- **Read-only tools only** — all current tools are GET operations. Write operations (POST/PUT/DELETE) are out of scope for now and will be considered in a future milestone

If you're unsure whether your idea fits, open an issue to discuss before writing code.

---

## Dev Setup

```bash
uv sync
```

Create `.env` in the project root with your Central credentials:

```
CENTRAL_BASE_URL=central-base-url
CENTRAL_CLIENT_ID=central-cluster-id
CENTRAL_CLIENT_SECRET=central-cluster-secret
```

```bash
python server.py          # starts the FastMCP server
uv run pytest tests/ -v   # run all tests
```

---

## Adding a Tool

Follow these steps for every new tool:

1. **Add the tool function** to `tools/<domain>.py` (create a new file for a new domain)
2. **Add helper functions** — if your tool needs data-transform helpers (e.g. `clean_*_data`), add them to `utils/<domain>.py` (create the file if it's a new domain). Shared infrastructure (retry, pagination, OData filtering, error formatting) goes in `utils/common.py`.
3. **Register it** inside the `register(mcp)` function using `@mcp.tool(annotations=READ_ONLY)`
4. **Define return types** as Pydantic `BaseModel` subclasses in `models.py`
5. **Add mock tests** to `tests/test_<domain>.py` (see [Tests](#tests) below)
6. **Lint**: `ruff check . && ruff format .`
7. **Test**: `make test` — all mock/unit tests must pass
8. **Check description cost**: `make tool-budget` — every description must remain at or below 200 estimated tokens

---

## Code Standards

### Tool signature

Tools must be `async`, accept `ctx: Context` as the first parameter, and declare an explicit return type:

```python
async def central_get_sites(ctx: Context, site_names: list[str] | None = None) -> list[SiteData]:
```

### Docstrings

Tool docstrings are MCP descriptions. Keep each at or below 200 estimated tokens and use this order:

1. Imperative one-line summary.
2. A blank line.
3. A concise “Use after/for …” sequencing hint.
4. “Cross-field rule:” or “Cross-field rules:” for coupled inputs and safety constraints.
5. “Returns <Type> with …”; paginated tools also explain how to replay `next_cursor`.

Put parameter documentation in `Field(description=...)`, never in `Args:` or `Parameters:` sections. Run `make tool-budget` to print the catalog cost table.

```python
async def central_get_sites(...) -> SiteEnvelope:
    """Retrieve site summaries or detailed health records.

    Use for site selection and health review.
    Cross-field rule: site_names applies only to view='detail'.
    Returns SiteEnvelope. Replay next_cursor as cursor to continue.
    """
```

### Pydantic models

- All return types must be `BaseModel` subclasses defined in `models.py`
- Every field must include `Field(description=...)` — field descriptions are part of the tool's schema

```python
class SiteData(BaseModel):
    name: str = Field(description="Human-readable site name as it appears in Central.")
    health: int | None = Field(description="Site health score from 0–100.")
```

### Type annotations

Use modern Python 3.10+ union syntax throughout:

```python
# Correct
site_names: list[str] | None = None
metrics: dict[str, Any]

# Avoid
Optional[List[str]]
Dict[str, Any]
```

### Tool annotations

Always annotate with `READ_ONLY` from `tools/__init__.py`:

```python
@mcp.tool(annotations=READ_ONLY)
async def central_get_sites(...):
```

### Error handling

Return a descriptive string on failure using `format_tool_error` from `utils.common`. Do not raise exceptions to the caller:

```python
from utils.common import format_tool_error
# ...
except Exception as e:
    return format_tool_error("fetching sites", e)
```

### Linting

`ruff check . && ruff format .` must pass before submitting a PR.

---

## Tests

### Mock tests (required)

Every new or modified tool must have mock tests in `tests/test_<domain>.py`. Use `FakeMCP` from `tests/conftest.py` and `unittest.mock.patch` to stub pycentral calls. No live Central connection should be required.

```python
@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools

async def test_get_sites_returns_list(tools, mock_ctx):
    with patch("tools.sites.fetch_site_data", return_value=[...]):
        result = await tools["central_get_sites"](mock_ctx)
    assert isinstance(result, list)
```

### Integration tests (optional for PRs)

`tests/integration/` contains live tests that hit the real Central API, marked with `@pytest.mark.integration`. For a PR they are **optional** — they auto-skip if no credentials are found, so a PR does not need them to pass.

Run mock tests only (default for contributors, no credentials needed):

```bash
make test          # uv run pytest tests/ -v -m "not integration"
```

### Release verification gate (required before each release)

The map's standing constraint: **every release is validated against the live Central environment the published server runs against, before it ships.** The live integration suite is that gate.

```bash
make verify-live   # live integration suite against the real tenant
make verify        # mock suite + live suite (full pre-release gate)
```

- **Credentials** flow the same path as the deployed v0.1.8 server: OS env vars (the MCP client env block) or a root `.env` file — `CENTRAL_BASE_URL`, `CENTRAL_CLIENT_ID`, `CENTRAL_CLIENT_SECRET` (see `config.py`).
- **Pass criteria**: the live suite runs green against the real tenant. `verify-live` sets `CENTRAL_LIVE_REQUIRED=1`, so **missing credentials fail the gate rather than silently skipping** — an un-credentialed run cannot pass as green.
- **Coverage today**: ~24 of the active tools across sites, devices, clients, APs, switches, gateways, alerts, events, WLANs, troubleshooting, plus prompt/server smoke tests.
- Tests reference tools by name (e.g. `tools["central_get_sites"]`), so the **test bodies** track tool renames — expect churn at the 0.2.0 consolidation. The **gate itself** (`make verify-live`, the `integration` marker) is taxonomy-agnostic and stays put.

Add live tests alongside your mock tests where a tool's real-API behavior is worth guarding.

---

## Pull Requests & Issues

When opening a PR on GitHub, select the matching template (New Tool, Bug Fix, or Infrastructure). Fill in all sections before requesting review.

- **Target branch**: open PRs against `main`.
- **PR title**: describe the tool added or the change made (e.g. `Add central_get_clients tool`)
- **Reference the API**: include the Central v1 API endpoint your tool wraps in the PR description
- **APIs from the same category only, max 3 per PR**: tools must wrap APIs from the same category (e.g. Sites, Devices, Clients, Alerts, Events). Do not mix categories or submit more than 3 tools in one PR.
- **AI-generated contributions**: if your PR or issue was created by an AI agent, include 🤖 at the bottom of the description.
