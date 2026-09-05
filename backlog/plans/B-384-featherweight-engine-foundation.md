# B-384-featherweight-engine-foundation — Pure ONNX + Oxigraph (RDF-star) + sqlite-vec Architecture

**Card:** B384 | **Priority:** P0 | **Depends on:** B281, B311, B342, B355, B386  
**Branch:** `feat/b384-featherweight-engine-foundation` | **PR Target:** `main`

---

## 1. Summary

Transition HippoCampy from the legacy, heavy, EOL Kùzu/PyTorch stack to a featherweight, 100% Apache-2.0 / MIT embedded architecture:
- Ingestion: Pure ONNX token classification + rule parser (eliminating `torch`, `thinc`, `spacy`).
- Query Seam: Builds on B386's centralized `campy/brain/hippocampus/graph/queries/` chokepoint.
- Storage: In-process `pyoxigraph` (RocksDB RDF-star) for graph and edge metadata + `sqlite-vec` for 384-dim vector embeddings.
- Footprint: Sub-80 MB physical idle RAM with zero memory commit spikes.

---

## 2. Phased Execution Sequencing

To prevent git merge collisions and enable clean, independently measurable milestones:

### Phase 2A: Ingestion Front-End (Pure ONNX + Drop PyTorch)
- Replace spaCy/thinc in `campy/brain/temporal_lobe/loop/step1_zoning.py` with ONNX token classification via `fastembed`'s existing ONNX Runtime provider.
- Refactor `step1b_fast_relations.py` with lightweight universal verb/lemma pattern matching (*require, enable, replace, contradict, part_of*).
- Remove `torch`, `torchvision`, `thinc`, and `spacy` from `pyproject.toml` and `requirements.txt`.
- **Milestone 1:** `tests/test_torch_free_import.py` verifies zero instances of `torch` in `sys.modules`. Process RSS drops from ~1.2 GB down to ~245 MB.

### Phase 2B: Storage Back-End (`pyoxigraph` + `sqlite-vec`)
*(Leverages B386's centralization of all 592 lines of Cypher completed in Phase 1)*
- Translate the centralized query catalog in `graph/queries/` to SPARQL (pure-graph traversals).
- Dispatch Vector ANN search via `sqlite-vec` (Python-coordinated hydration) and edge mutations with `:event_id` discriminators via Python-level RDF-star handlers.
- Build `campy/brain/hippocampus/graph/oxigraph_client.py`:
  - Native RDF-star (`<< :s :p :o >>`) statement terms for edge properties (`LOADED`, `CO_OCCURS_WITH`, `ENABLES`, `DEPRECATED_BY`).
  - Event occurrence discriminators (`:event_id` or timestamp) on discrete repeated events.
- Build `campy/brain/hippocampus/graph/vector_store.py`:
  - `sqlite-vec` index over 384-dim FastEmbed embeddings.
  - Sub-millisecond SQLite cosine distance queries.
- Remove `kuzu` from `pyproject.toml` and `requirements.txt`.
- **Milestone 2:** Process RSS drops from ~245 MB down to <80 MB RAM.

### Phase 2C: Gateway Cutover & Patent Re-Certification
- Point `gateway.py` to route through `oxigraph_client.py` and `vector_store.py`.
- Update `scripts/check_cypher_ratchet.py`: Replace `kuzu_client.py` with `oxigraph_client.py` in `ALLOWLIST_FILES`, and adjust regex to handle SPARQL 1.1 `CREATE GRAPH` statements without false-positive Cypher alerts.
- Update `campy export-graph` and `campy import-graph` (B281).
- Re-run full GCL test suite (`tests/test_loop.py`, `tests/test_retrieval.py`).
- **Dual-Engine Patent Re-Certification:** Re-run all 9 B380 patent claim tests against the new engine via observable mechanism outputs.
- Certify <80 MB physical RAM on macOS (`vmmap -summary`) and Linux (`/proc/[pid]/status`).

---

## 3. Concrete File Changes

- Create: `campy/brain/hippocampus/graph/oxigraph_client.py`
- Create: `campy/brain/hippocampus/graph/vector_store.py`
- Modify: `campy/brain/temporal_lobe/loop/step1_zoning.py`
- Modify: `campy/brain/temporal_lobe/loop/step1b_fast_relations.py`
- Modify: `campy/brain/hippocampus/graph/gateway.py`
- Modify: `campy/brain_daemon.py`
- Modify: `scripts/check_cypher_ratchet.py`
- Modify: `scripts/cypher_baseline.json`
- Modify: `pyproject.toml` & `requirements.txt`
- Create: `tests/test_featherweight_engine.py`
- Create: `tests/test_torch_free_import.py`

---

## 4. Acceptance Criteria

- [ ] Zero instances of `torch`, `thinc`, `spacy`, or `kuzu` in `sys.modules`.
- [ ] `scripts/check_cypher_ratchet.py` passes with 0 violations under new Oxigraph allowlist.
- [ ] Process physical idle footprint verified at <80 MB RAM.
- [ ] 100% of Gated Consolidation Loop tests pass.
- [ ] B380 patent claim suite re-certified 100% passing on Oxigraph.
