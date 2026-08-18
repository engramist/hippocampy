# capability_eval — B317 named-query eval pack

A synthetic capability graph and five "customer questions" over it, used to
prove that Campy's projected capability-graph subset (`FactEntity` + the ten
`FACT_*` rel tables — see `docs/ARCHITECTURE.md`'s "Projected capability
graph" section) can answer real governed-platform queries with bounded,
provenance-aware Cypher.

## This doubles as the backend-conformance suite

**Any storage adapter claiming to back Campy must pass
`tests/test_capability_queries.py` unmodified against this fixture.**

That is the actual point of this directory, not a side effect of it. The
fixture (`fixtures.py`), the five questions' hand-traced expected result
sets (`questions.py`), and the assertions in
`tests/test_capability_queries.py` together form a fixed, versioned contract:
seed this exact graph through the real `ingest_entities()`/`ingest_facts()`
path, run these five named queries through `GraphGateway.run()`, and get
back exactly these rows. A future storage adapter (a second `KuzuClient`-
shaped implementation, a different graph engine entirely) is conformant
precisely to the extent that it reproduces this behavior — swap the adapter
underneath `GraphGateway`, re-run the same test file, same fixture, same
expected sets, no edits. If the test file needs modification to pass against
a new adapter, that adapter is not conformant; fix the adapter, not the test.

## What's here

- `fixtures.py` — `seed_fixture_graph(gateway)`. ~40 `FactEntity` nodes and
  ~30 `FACT_*` edges, seeded through the real ingest path (never raw
  Cypher), spanning every entity type and predicate in the customer's
  starter vocabulary. Retires one edge and one node after the initial
  ingest — one superseded row per question — so every one of the five
  questions has a real exclude-by-default / recover-with-
  `include_superseded=True` case to prove against, not a hypothetical one.
  Also constructs an exact-cosine-similarity near-duplicate pair (0.90) with
  a lexically dissimilar label for Q5, a below-floor entity (0.20), and an
  above-floor-but-unsatisfiable entity (0.80, whose dependency is retired at
  the node level) — see the module docstring for the full construction.
- `questions.py` — the five questions' exact expected result sets
  (`Q<N>_PARAMS`/`Q<N>_EXPECTED`, plus `_INCLUDE_SUPERSEDED` variants and
  `Q5_NEVER_APPEARS`), hand-traced against the fixture graph above — not
  approximated. This is the ground truth `tests/test_capability_queries.py`
  asserts equality against.

The five named queries themselves
(`campy/brain/hippocampus/graph/queries/capability.py`) and the write path
that seeds them (`campy/brain/hippocampus/facts.py`) are not duplicated
here — this directory only owns the fixture and the ground truth.

## The five questions

| id | query name                       | question                                                        |
|----|-----------------------------------|-------------------------------------------------------------------|
| Q1 | `capability.permitted_paths`      | Given a user's trust tier, what capability path is allowed?      |
| Q2 | `capability.explain_path`         | Why was this path selected or blocked?                           |
| Q3 | `capability.impact_of`            | If this adapter changes, what's affected?                        |
| Q4 | `capability.lineage_of`           | What produced this artifact?                                     |
| Q5 | `capability.reuse_candidates`     | Can an existing capability chain satisfy this request?           |

Every query carries an explicit hop bound (`*1..5`, `*1..4`, `*1..6` — never
a bare unbounded `*`) and excludes superseded rows by default via an
`include_superseded` parameter every query declares. See
`campy/brain/hippocampus/graph/queries/capability.py`'s module docstring for
the Kùzu 0.11.3 quirks its Cypher works around.

## Running the conformance suite

```bash
.venv/bin/python -m pytest tests/test_capability_queries.py tests/test_fact_ingest.py -q
```

`test_capability_queries.py` seeds a fresh temp Kùzu DB per test via
`benchmarks.capability_eval.fixtures.seed_fixture_graph()`, runs each of the
five queries through `GraphGateway.run()`, and asserts against
`questions.py`'s expected sets — both the default (`include_superseded=False`)
and `_INCLUDE_SUPERSEDED` variant of every question. `test_fact_ingest.py`
tests the write path (`ingest_entities()`/`ingest_facts()`) directly:
idempotency, supersession on a newer `source_version`, unknown-predicate
rejection, missing-`source_version` rejection, and the
`authority='projected'` invariant.

## Why this subset is `authority='projected'`, always

Everything this fixture seeds is a harvested mirror of an external system —
Campy is never the source of truth for it. See `docs/ARCHITECTURE.md`'s
"Projected capability graph" section for the full rationale (governed-
platform evaluation requirement, `drop_projections()` safety, and how this
subgraph coexists with Campy's own earned memory graph in the same Kùzu
database).
