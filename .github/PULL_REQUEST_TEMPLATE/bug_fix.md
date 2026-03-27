## What broke and why
<!-- One sentence: root cause -->

## What this fixes
<!-- Which tool(s) or function(s) are affected -->

## Checklist
- [ ] Root cause identified (not just symptom patched)
- [ ] Existing tests updated or new tests added to cover the fix
- [ ] `ruff check . && ruff format .` passes
- [ ] `uv run pytest tests/ -v` passes
- [ ] PR targets `development`, not `main`
