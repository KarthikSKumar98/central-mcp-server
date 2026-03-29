Fixes #<!-- issue number, if applicable -->

## Type
<!-- Check one -->
- [ ] New tool
- [ ] Bug fix
- [ ] Infrastructure / docs

## Summary
<!-- One sentence: what this does and why -->

## New tools added
<!-- For new tool PRs only. List each function name (max 3 per PR, same domain) -->
- `central_get_...`

Category: <!-- e.g. Sites, Devices, Clients, Alerts, Events -->

## Checklist
- [ ] PR targets `development`, not `main`
- [ ] `ruff check . && ruff format .` passes
- [ ] `uv run pytest tests/ -v` passes
- [ ] New/updated tests cover the change
- [ ] *(New tools)* Tool is in `tools/<domain>.py`, annotated `READ_ONLY`, return type is a `BaseModel` subclass in `models.py`
- [ ] *(New tools)* Docstring uses prose + `Parameters:` style (no Google-style Args/Returns)
- [ ] *(Docs)* `README.md` and `README.pypi.md` kept in sync
