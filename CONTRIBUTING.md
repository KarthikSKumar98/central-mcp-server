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
2. **Register it** inside the `register(mcp)` function using `@mcp.tool(annotations=READ_ONLY)`
3. **Define return types** as Pydantic `BaseModel` subclasses in `models.py`
4. **Add mock tests** to `tests/test_<domain>.py` (see [Tests](#tests) below)
5. **Lint**: `ruff check . && ruff format .`
6. **Test**: `uv run pytest tests/ -v` — all tests must pass

---

## Code Standards

### Tool signature

Tools must be `async`, accept `ctx: Context` as the first parameter, and declare an explicit return type:

```python
async def central_get_sites(ctx: Context, site_names: list[str] | None = None) -> list[SiteData]:
```

### Docstrings

Use **prose paragraphs** followed by a `Parameters:` bullet list. Do not use Google-style `Args:`/`Returns:` sections. These docstrings are surfaced directly as MCP tool descriptions and should be readable by an AI client.

```python
async def central_get_sites(ctx: Context, site_names: list[str] | None = None) -> list[SiteData]:
    """
    Returns detailed metrics for one or more sites.

    Prefer calling with a site_names filter targeting only the sites you care about.
    Do NOT call without a filter unless the user explicitly requests all sites.

    Parameters:
    - site_names: One or more site names to filter by. If omitted, all sites are returned (use sparingly).
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

Return a descriptive string on failure. Do not raise exceptions to the caller:

```python
except Exception as e:
    return f"Failed to retrieve sites: {e}"
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
    with patch("tools.sites.fetch_site_data_parallel", return_value=[...]):
        result = await tools["central_get_sites"](mock_ctx)
    assert isinstance(result, list)
```

### Integration tests (optional)

`tests/integration/` contains live tests that hit the real Central API. These are **optional** — they auto-skip if no `.env` credentials are found. You're welcome to add integration tests alongside your mock tests, but they are not required for a PR to be accepted.

Run all tests:

```bash
uv run pytest tests/ -v
```

---

## Pull Requests & Issues

- **Target branch**: open PRs against `development`, not `main`. Direct PRs to `main` will not be merged.
- **PR title**: describe the tool added or the change made (e.g. `Add central_get_clients tool`)
- **Reference the API**: include the Central v1 API endpoint your tool wraps in the PR description
- **One tool per PR**: each PR should add, fix, or modify a single tool. Do not bundle unrelated tools or mix tool changes with infrastructure changes.
- **AI-generated contributions**: if your PR or issue was created by an AI agent, include 🤖 at the bottom of the description.