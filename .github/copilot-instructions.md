# GitHub Copilot Instructions for HippoCampy

## Principles (binding for all agents)

<!-- principles:begin (copy of PRINCIPLES.md; edit that file) -->
These bind every agent working here. If a change cannot say which principle it serves, stop and ask.

1. **The benchmark score is the measure.** Every change to retrieval or answering names its target and reports its gate result on the published metric (LoCoMo categories 1-4, LongMemEval overall, DMR accuracy). Receipts and paperwork are not progress.
2. **Graph first.** The graph store (Oxigraph today) is the single source of truth; no shadow stores. The detailed rule is under Sources Of Truth.
3. **The model advises; rules decide.** Retrieved evidence stays linked to its source turn; anything a model writes into memory is a candidate until a rule or an independent source confirms it.
4. **Generalise, don't memorise.** No rule fitted to one benchmark question or dataset; a fix names the general construction and must hold on held-out conversations.
5. **Fix the structure, not the wording.** Prefer retrieval and structural changes over prompt rewording; wording changes swing results by noise alone.
6. **Measure correctly before believing.** Every result records what ran (commits, flags, prompts); doubt the scorer and the answer key before the pipeline.
7. **Small, reversible, one lever per PR.** Ship behind a flag, gate it, then flip the default.

### Signs of drift

- A week of commits with no gate result.
- New docs, receipts or process files that no score depends on.
- A fix that matches one question rather than a general construction.
- Prompt rewording as the main change.
- Persistent data held outside the graph.
- A PR that cannot say which principle it serves.

Run `python scripts/drift_report.py` to check for these; CI (`pr-score-effect`) requires a `## Score effect` section on PRs that touch retrieval, answering or config code.
<!-- principles:end -->

These are repository custom instructions for GitHub Copilot, including **Copilot code review**.

## Sources of Truth

Before reviewing or generating code, respect these:
- `docs/ecosystem-rules.md` — layer boundaries and import constraints (the rules below enforce it)
- The graph store (Oxigraph today) is the **single source of truth** for persistent agent state; `vectors.db` is an index, not a store. In-memory structures are allowed only as read-through caches over graph-backed state — never as the primary store.
- `skills/campy-graph/SKILL.md` — for capture, retrieval and answering changes: flag Python that counts, filters or joins what a SPARQL query anchored on the subject entity could compute.

## PR Review Checklist (Ecosystem Gate)

When reviewing a pull request, check each rule below and report findings in this table format:

| File | Line | Rule | Severity | Fix |
|------|------|------|----------|-----|

**Rules:**

**1. Layer placement** — new code must go in the correct directory per `docs/ecosystem-rules.md`.
- Flag: any file under `campy/` that imports from `agents/` or `benchmarks/`
- Flag: any file under `agents/` or `benchmarks/` that imports from `campy/`
- Flag: new files placed in the wrong top-level directory for their responsibility

**2. No shadow stores** — persistent agent state must go through the graph store, not in-memory structures.
- Flag: module-level `dict` or `list` in `campy/` whose name contains `store`, `cache`, `state`, `registry`, or `db` as an underscore-delimited component (e.g. `_cache`, `session_state`, `vector_db`)
- In-memory caches backed by graph-store reads are permitted; standalone in-memory state is not

**3. Tool registration** — every new MCP tool must follow the schema-first flow.
- Flag: a new function in `campy/brain/thalamus/tools/__init__.py` matching `*_tool` or `handle_*`
  that does not appear in the `TOOL_HANDLERS` dict in the same file
- A new MCP tool must be added to `tool_schemas.TOOLS` and `TOOL_HANDLERS`, then regenerate extension entries via
  `python scripts/generate_extension_tools.py` (CI enforces generated file freshness)

**4. Schema migrations** — schema additions need a migration entry.
- Flag: additions to `NODE_TABLES` or `REL_TABLES` in `campy/brain/hippocampus/schema.py`
  (both are module-level, no underscore prefix) that have no corresponding entry added to
  the `_MIGRATIONS` list inside the `init_schema()` function in the same file

**Decision:**
- If all rules pass: approve the PR.
- If any rule fails: request changes with the findings table above. Do not approve until fixed.
