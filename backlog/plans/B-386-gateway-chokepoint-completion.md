# B-386-gateway-chokepoint-completion — GraphGateway Chokepoint Completion & Raw-Cypher Ratchet to Zero

**Card:** B386 | **Priority:** P0 | **Depends on:** B314  
**Branch:** `feat/b386-gateway-chokepoint-completion` | **PR Target:** `main`

---

## 1. Summary

Complete the architectural seam started in B314 by eliminating all 592 lines of inline Cypher scattered across 48 files in `campy/`. Centralize all query text into domain modules under `campy/brain/hippocampus/graph/queries/`, update application call sites to use `GraphGateway.run()`, remove direct application imports of `KuzuClient`, and drive the CI ratchet in `scripts/check_cypher_ratchet.py` to zero.

This card is the prerequisite bridge that makes B384's Oxigraph (SPARQL) storage cutover safe, bounded, and feasible.

---

## 2. Subagent Parallel Workstreams (Disjoint File Slices)

Because the files containing inline Cypher have clean domain boundaries, this card decomposes into 5 parallel implementation slices to avoid context window bloat:

### Group A: ARC & Cognitive Sibling Tools (~100 lines)
- Target Files: `arc_queries.py` (46), `arc_artifacts.py` (27), `arc_mechanics.py` (27).
- Target Query Module: **Modify** `campy/brain/hippocampus/graph/queries/arc.py` (already exists, 134 lines; append queries following established `arc.<verb>_<subject>` convention).
- Registers named queries: `arc.get_active_mechanics`, `arc.match_scene_graph`, `arc.fetch_disappeared_entities`, etc.

### Group B: Brainstem & Hippocampus Core (~127 lines)
- Target Files: `sweep.py` (68), `quest.py` (27), `hippocampus.py` (19), `export.py` (13).
- Output Query Modules: Create `queries/sweep.py`, create `queries/quests.py`.
- Follows existing conventions from `backup.py` and `continuity.py`.
- Registers named queries: `sweep.decay_pathway_strengths`, `sweep.prune_orphaned_edges`, `quests.get_active_quest`, etc.

### Group C: Consolidation Loop & Retrieval (~106 lines)
- Target Files: `step7_pathway.py` (27), `orchestrator.py` (24), `retrieval.py` (16), `working_memory.py` (14), `capture.py` (14), `ingest.py` (11).
- Output Query Modules: Create `queries/pathways.py`, create `queries/orchestrator.py`, create `queries/retrieval.py`.
- Registers named queries: `pathways.strengthen_co_occurrence`, `orchestrator.record_step_transition`, `retrieval.get_working_memory_nodes`, etc.

### Group D: Thalamus Tools & Web Control Panel (~121 lines)
- Target Files: `quests.py` (42), `task_graph.py` (27), `web/server.py` (31), `procedure_synthesis.py` (11), `wiki_projection.py` (10).
- Output Query Modules: Create `queries/task_graph.py`, create `queries/web.py`.
- Follows existing conventions from `lessons.py` and `capability.py`.
- Registers named queries: `task_graph.add_action_item`, `web.fetch_graph_stats`, etc.

### Group E: Tail (~138 lines)
- Target Files: ~30 remaining files with 1–5 lines of inline Cypher each.
- Centralizes into appropriate domain files or `queries/common.py`.

*Shared write surface:* Strictly append-only `campy/brain/hippocampus/graph/queries/__init__.py` and `scripts/cypher_baseline.json` (orchestrator updates at merge).

---

## 3. Gateway Architecture Upgrade

In `campy/brain/hippocampus/graph/gateway.py`:
```python
@dataclass(frozen=True)
class NamedQuery:
    name: str
    cypher: str
    sparql: str | None = None  # Provisional for pure-graph traversal queries (~90%)
    params: tuple[str, ...]
    mutating: bool
    doc: str = ""
```

### Explicit Handler Dispatch Boundary (B384 Storage Foundation)
Not all queries have a 1:1 SPARQL string equivalent:
1. **Vector ANN Search:** Kùzu's `QUERY_VECTOR_INDEX` has no SPARQL counterpart. In B384 Phase 2B, vector search routes through `sqlite-vec` in Python for top-k entity IDs, followed by graph node hydration via Oxigraph.
2. **RDF-Star Edge Reification:** Mutating edge properties (e.g. `MATCH (a)-[r:LOADED]->(b) SET r.token_estimate = ...`) with `:event_id` discriminators requires Python-level quoted triple handling, not simple string transliteration.

`NamedQuery` serves as the semantic query contract (`name`, `params`, `mutating`), allowing engine-specific query strings or dedicated Python handlers for vector/reified operations.

---

## 4. Phasing & Schedule

- **Phase 1 Concurrency:** B386 has zero file collisions with B380 (patent tests), B381 (benchmarks), and B374 (compression). It runs concurrently during Phase 1.
- Completing B386 in Phase 1 removes it from Phase 2's critical path entirely, allowing Phase 2 to collapse into sequential 2A (drop PyTorch) -> 2B (cutover to Oxigraph + sqlite-vec).

---

## 5. Acceptance Criteria

- [ ] `python3 scripts/check_cypher_ratchet.py` passes with count = 0.
- [ ] `scripts/cypher_baseline.json` updated to `cypher_lines: 0`.
- [ ] Zero files in `campy/` outside `hippocampus/graph/` import `KuzuClient`.
- [ ] 100% test pass across `tests/test_gateway.py`, `tests/test_loop.py`, `tests/test_retrieval.py`.
