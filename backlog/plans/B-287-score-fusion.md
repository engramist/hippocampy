# B-287 — Principled Score Fusion in current_truth

Card: backlog/B287.md
Priority: P3
Dependencies: B279 (must land first)

## Summary

Replace ad-hoc score merging in `current_truth` with Reciprocal Rank Fusion plus bounded adjustments, and pin the ranking contract with fixture tests.

## Step 1 — Document current behavior (do before changing anything)

Read `current_truth` end to end (`thalamus/tools/__init__.py` ~line 1126 onward, through the final sort/return). Write a short BEFORE.md note (paste into the PR description, not the repo) answering:
- What is the final sort key today?
- Where do pathway_strength / outcome signals enter?
- What exactly happens to lexical hits with `score: 1.0`?
- How are per-table results interleaved (the `per_table_limit = max(limit,5)` per table means up to 10×5 raw candidates)?

## Step 2 — RRF implementation

Inside `current_truth`, after candidate collection, replace the existing ranking with:

```python
RRF_K = 60

def _rrf_fuse(source_lists: dict[str, list[dict]], limit: int) -> list[dict]:
    """Reciprocal Rank Fusion across ranked source lists.

    source_lists: {"vector:Concept": [cand, ...] (sorted desc by score),
                   "vector:Decision": [...], ..., "lexical": [...]}
    Each cand must carry a stable identity key "node_id".
    """
    fused: dict[str, dict] = {}
    for source, ranked in source_lists.items():
        for rank, cand in enumerate(ranked):
            nid = cand["node_id"]
            entry = fused.setdefault(nid, {"cand": cand, "rrf": 0.0, "sources": {}})
            entry["rrf"] += 1.0 / (RRF_K + rank + 1)
            entry["sources"][source] = {"rank": rank, "score": cand.get("score")}
            # keep the richest candidate dict (vector results carry node props)
            if cand.get("score", 0) > entry["cand"].get("score", 0):
                entry["cand"] = cand
    return sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)
```

Then bounded adjustments on the fused score:

```python
PATHWAY_CAP = 5.0      # pathway_strength contribution saturates here
VALENCE_WEIGHT = 0.2   # outcome valence shifts ±20% max

for entry in fused_entries:
    node = entry["cand"]
    ps = min(float(node.get("pathway_strength") or 0.0), PATHWAY_CAP)
    valence = outcome_map.get(entry_node_id, 0.0)        # existing outcome_map, clamp [-1,1]
    entry["final"] = entry["rrf"] * (1 + ps / (2 * PATHWAY_CAP)) * (1 + VALENCE_WEIGHT * max(-1.0, min(1.0, valence)))

results = sorted(fused_entries, key=lambda e: e["final"], reverse=True)[:limit]
```

Lexical handling: build the lexical list as its own ranked source (already ordered by `created_at DESC`). Remove the hardcoded `"score": 1.0`; keep the `lexical_exact: True` flag on the result for downstream display. A hit appearing in BOTH lexical and a vector list naturally gets two RRF contributions — that's the desired "agreement boost".

Identity key: build `node_id` consistently from the per-table pk during collection (the code already extracts `nid = node.get(pk)` for the outcome lookup — reuse that point to stamp `cand["node_id"]`).

Debug surface: when `params.get("debug_ranking")` is truthy, attach `entry["sources"]` + `rrf` + `final` to each returned result as `ranking_signals`. Default off — context-window bloat matters here.

Preserve everything else the function returns (quest_context, rationale enrichment, etc.) — only the ordering machinery changes. Check whether downstream consumers sort by a `score` field on results; if the response previously exposed `score`, keep exposing it (set it to `final`, documented as "fused relevance, not cosine").

## Step 3 — Tests (`tests/test_score_fusion.py`)

Mock db pattern; control the candidate sets precisely:

1. `test_vector_consensus_beats_single_lexical` — node A ranked #1 in two vector tables; node B lexical-only #1. Assert A above B.
2. `test_lexical_recent_hit_still_surfaces` — lexical-only candidate appears in top `limit`.
3. `test_pathway_strength_bounded` — identical RRF, pathway 100.0 vs 1.0: ratio of finals ≤ 1.5×.
4. `test_negative_valence_demotes` — valence −1 demotes below an otherwise-equal peer.
5. `test_rrf_pure_function` — direct unit test of `_rrf_fuse` with hand-computed expected values: two lists, k=60, assert exact floats.
6. `test_response_shape_unchanged` — keys of a result item match pre-change snapshot (grab from existing test_web.py expectations).

## Validation Commands

```bash
pytest tests/test_score_fusion.py -v
pytest tests/test_web.py tests/test_b195_proactive_push.py -q
python3 -m py_compile campy/brain/thalamus/tools/__init__.py
```

## Risks

- Behavior change in recall ordering is the point, but verify no test encodes the old ordering (run the full suite, fix expectations deliberately, never blindly).
- `current_truth` is 200+ lines; extract `_rrf_fuse` and `_apply_adjustments` as module-level functions for testability rather than growing the closure.
- If `compile_context` (bundle_compiler) or proactive push reuse the same ranking path, check and align (`rg "pathway_strength" campy/brain/thalamus/bundle_compiler.py`).
