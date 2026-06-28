## Description

<!-- What does this PR do? Why? -->

## Test Plan

<!-- How did you verify this works? -->

## Checklist

- [ ] I ran the existing test suite: `pytest tests/ -q`
- [ ] No new module-level dicts/lists in `campy/` used as persistent stores (use KuzuDB)
- [ ] New code is in the right directory per `docs/ecosystem-rules.md`
- [ ] New MCP tools are added to `TOOL_HANDLERS` in `campy/brain/thalamus/tools/__init__.py`
- [ ] Schema changes include an entry in the `_MIGRATIONS` list inside `init_schema()` in `campy/brain/hippocampus/schema.py`
