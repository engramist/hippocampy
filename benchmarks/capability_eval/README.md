# capability_eval — B317 bounded multi-hop conformance suite

This directory turns an external platform's five published multi-hop
governance questions into an executable, regression-tested suite against
Campy's projected capability-graph subset (`FactEntity` + the ten
`FACT_*` rel tables in `campy/brain/hippocampus/schema.py`).

**This doubles as Campy's backend-conformance suite.** Any future storage
adapter claiming to back Campy must pass this suite unmodified — that is
the property that makes a graph-engine swap a measurable exercise
(run the suite, see what breaks) rather than a rewrite. See B314's
`GraphGateway` seam for the portability boundary this suite exercises
through: every query here is a `NamedQuery` reached via
`GraphGateway.run()`, never raw Cypher.

## Files

- `fixtures.py` — a ~40-entity synthetic capability graph, seeded through
  the real ingest handlers (`campy.brain.hippocampus.facts.ingest_entities`
  / `ingest_facts`), matching `benchmarks/ask_eval/fixtures.py`'s
  "seed through real handlers, not raw Cypher" convention.
- `questions.py` — the five questions, each as a registered query name +
  params + expected result set against the fixture.
- `README.md` — this file.

The actual grader is `tests/test_capability_queries.py`, which runs each
of the five queries against a real temporary Kùzu database (never
`:memory:` — unverified against the pinned Kùzu 0.11.3) and asserts exact
expected sets, not "returns something."

## Scope: three joinable entity types, not ten

A stable-identifier audit run after this card was written found only
**three** entity types with a usable stable ID in the real platform
today: `capability` (`agent/claude-design`), `agent` (directory name),
and `mcp_tool` (`service/servicesmcp#quote.verify`). Every other type the
customer's ontology names — Iteration, Run, Artifact, Infrastructure —
has no usable identity yet (Iteration doesn't exist as its own entity;
Run has three non-interoperable ID schemes; Artifact has two incompatible
conventions and one source with no `artifact_id` field at all;
Infrastructure is hand-typed Terraform literals).

**Consequence for this fixture:** every entity whose `entity_type` is
`capability`, `agent`, or `mcp_tool` uses an ID shape modeled on the
customer's own conventions. Everything else (`policy`, `dataset`,
`infrastructure`, `artifact`, `run`, `approver`) is a **structural
stand-in**, prefixed `synthetic:` in its `entity_id`, needed only so the
predicates that inherently reference those types
(`CONSTRAINED_BY`/`DEPLOYED_ON`/`PRODUCED`/`APPROVED_BY`/`READS`/`WRITES`)
and `capability.lineage_of` (Q4) have something to traverse to. **None of
that synthetic data is representative of the real platform's graph, and
Q4 in particular is unverifiable against production until Artifact and
Infrastructure gain stable IDs there.** `capability.lineage_of` is fully
implemented and tested against the fixture regardless — the card is
explicit that scoping out the query itself, rather than just flagging its
inputs as unverified, would be the wrong call.

## The five questions

| # | Question | Named query |
|---|---|---|
| Q1 | Given this user, intent, trust tier and policy set, what capability path is allowed? | `capability.permitted_paths` |
| Q2 | Why was this path selected or blocked? | `capability.explain_path` |
| Q3 | If this adapter changes, which agents, workflows, apps and policies are affected? | `capability.impact_of` |
| Q4 | Which skills, tools, data, approvals and infrastructure produced this artifact? | `capability.lineage_of` |
| Q5 | Can an existing chain of capabilities satisfy the request without building something new? | `capability.reuse_candidates` |

Every query is bounded (explicit `*N..M` hop limit, never a bare `*`) and
excludes superseded rows by default via an `include_superseded` parameter
— `tests/test_capability_queries.py` asserts both properties for each of
the five by inspecting the registered `NamedQuery.cypher` text directly,
not just by checking behavior.

## Deliberate difficulty in the fixture

- **A blocked path** — `CAP_GUARDED_1` is gated by a `CONSTRAINED_BY`
  edge requiring the `elevated` trust tier; Q1 at `trust_tier='public'`
  must exclude it and everything reachable only through it.
- **A superseded edge** — `CAP_ENTRY`'s `REQUIRES` edge to `CAP_OPEN_1` is
  ingested at `v1` and re-ingested at `v2` with a different confidence,
  producing a real supersession (not just a v1-only edge) that Q2's
  `explain_path` can be asked to include or exclude.
- **Two near-duplicate capabilities with lexically dissimilar labels**
  (`CAP_DUP_1` "Fast quote verification pass" / `CAP_DUP_2` "Velocity
  checking service for quotes") — Q5 must find this pair by embedding
  similarity; the test asserts this isn't achievable by any string-overlap
  heuristic on the labels.
- **A diamond dependency** — `CAP_DIAMOND_TOP` requires both
  `CAP_DIAMOND_MID_A` and `CAP_DIAMOND_MID_B`, which both require
  `CAP_DIAMOND_ROOT`. Q3's `impact_of(CAP_DIAMOND_ROOT)` must return
  `CAP_DIAMOND_TOP` exactly once, not twice.
