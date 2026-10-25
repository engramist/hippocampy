## Principle

<!-- Which principle in PRINCIPLES.md this change serves (number + name). -->

## Lever and target

<!-- What you changed (the lever) and which benchmark/questions it should move (the target). -->

## Graph design

<!-- The edge(s) this change reads or writes and the query that reads them (SPARQL or NamedQuery name), or "None — <reason>". See skills/campy-graph/SKILL.md "Design-review checklist". -->

## Score effect

<!-- Gate table (suite | main | branch | gained | lost) on the published metric, or "None — <reason>" (e.g. docs-only, test-only, infra). With a gate table, add a line "Targets in gate: N" (N >= 10, or "all", or "none — <reason>"): how many of the lever's target questions the gate slice holds; count or pick a slice with scripts/gate_slice.py. -->

## What

<!-- What does this PR do, and why? -->

## Test Plan

<!-- How did you verify this works? -->

## Checklist

- [ ] I ran the existing test suite: `pytest tests/ -q`
- [ ] No new module-level dicts/lists in `campy/` used as persistent stores (use the graph store)
- [ ] New code is in the right directory per `docs/ecosystem-rules.md`
- [ ] New MCP tools are added to `TOOL_HANDLERS` in `campy/brain/thalamus/tools/__init__.py`
- [ ] Schema changes include an entry in the `_MIGRATIONS` list inside `init_schema()` in `campy/brain/hippocampus/schema.py`
