# GitHub Copilot Instructions for HippoCampy

These are repository custom instructions for GitHub Copilot, including **Copilot code review**.

## Sources of Truth

Before reviewing or generating code, respect these:
- `docs/ecosystem-rules.md` — layer boundaries and import constraints (the rules below enforce it)
- KuzuDB is the **single source of truth** for persistent agent state. In-memory structures are allowed only as read-through caches over graph-backed state — never as the primary store.

## PR Review Checklist (Ecosystem Gate)

When reviewing a pull request, check each rule below and report findings in this table format:

| File | Line | Rule | Severity | Fix |
|------|------|------|----------|-----|

**Rules:**

**1. Layer placement** — new code must go in the correct directory per `docs/ecosystem-rules.md`.
- Flag: any file under `campy/` that imports from `agents/` or `benchmarks/`
- Flag: any file under `agents/` or `benchmarks/` that imports from `campy/`
- Flag: new files placed in the wrong top-level directory for their responsibility

**2. No shadow stores** — persistent agent state must go through KuzuDB, not in-memory structures.
- Flag: module-level `dict` or `list` in `campy/` whose name contains `store`, `cache`, `state`, `registry`, or `db`
- In-memory caches backed by KuzuDB reads are permitted; standalone in-memory state is not

**3. Tool registration** — every new MCP tool must be registered across all surfaces.
- Flag: a new function in `campy/brain/thalamus/tools/__init__.py` matching `*_tool` or `handle_*`
  that does not appear in the `TOOL_HANDLERS` dict in the same file
- A new MCP tool must also be added to `tool_schemas.TOOLS`, `extensions/hippocampy/src/index.ts`,
  and `tests/test_adapters.py` `EXPECTED_TOOLS` (these sets must stay equal)

**4. Schema migrations** — schema additions need a migration entry.
- Flag: additions to `NODE_TABLES` or `REL_TABLES` in `campy/brain/hippocampus/schema.py`
  (both are module-level, no underscore prefix) that have no corresponding entry added to
  the `_MIGRATIONS` list inside the `init_schema()` function in the same file

**Decision:**
- If all rules pass: approve the PR.
- If any rule fails: request changes with the findings table above. Do not approve until fixed.
