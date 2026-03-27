## What this adds
<!-- One sentence: what category and what they return -->

Category: <!-- e.g. Sites, Devices, Clients, Alerts, Events -->

## Tools added
<!-- List each tool function name (max 3) -->
- `central_get_...`

## Checklist
- [ ] All tools wrap APIs from the same category (e.g. Sites, Devices, Clients, Alerts, Events) — max 3 per PR
- [ ] Tool(s) are in `tools/<domain>.py`, registered with `@mcp.tool(annotations=READ_ONLY)`
- [ ] Return types are `BaseModel` subclasses in `models.py` with `Field(description=...)`
- [ ] Docstrings use prose + `Parameters:` style (no Google-style Args/Returns)
- [ ] Mock tests added to `tests/test_<domain>.py`
- [ ] `ruff check . && ruff format .` passes
- [ ] `uv run pytest tests/ -v` passes
- [ ] PR targets `development`, not `main`
