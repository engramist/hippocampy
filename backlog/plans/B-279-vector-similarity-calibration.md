# B-279 — Vector Similarity Calibration Audit and Fix

Card: backlog/B279.md
Priority: P0
Dependencies: none

## Summary

`KuzuClient.vector_search()` returns `score = 1/(1+distance)` while all callers interpret the score as cosine similarity. For L2-normalized embeddings the relationship between L2 distance and cosine is `d² = 2(1 − cos)`, so the transform is wrong on either metric assumption. Fix the facade to return true cosine, pin the index metric explicitly, prove it with a fixture test, and audit every consumer threshold.

## Math Reference (for the implementer)

For L2-normalized vectors a, b:
- L2 distance: `d = sqrt(2 - 2·cos(a,b))` → `cos = 1 - d²/2`
- Cosine distance (as used by most HNSW impls): `d_cos = 1 - cos` → `cos = 1 - d_cos`

Current transform `1/(1+d)`:
- If metric=L2: score 0.92 ⇒ d=0.087 ⇒ cos≈0.996. Score 0.75 ⇒ d=0.333 ⇒ cos≈0.944.
- If metric=cosine: score 0.92 ⇒ d_cos=0.087 ⇒ cos≈0.913. Score 0.75 ⇒ d_cos=0.333 ⇒ cos≈0.667.

## Technical Approach

### Step 1: Empirically determine the metric (write this test FIRST)

Create `tests/test_vector_calibration.py`:

```python
"""Calibration regression tests for KuzuClient.vector_search.

Guards against drift between HNSW distance metric and the similarity
scores consumed by Step 5 dedup, quest routing, and analogical search.
"""
import math
import shutil
import tempfile
import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


@pytest.fixture()
def calib_db():
    tmp = tempfile.mkdtemp(prefix="kuzu_calib_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(
        "CREATE NODE TABLE CalibNode("
        "id STRING, embedding FLOAT[4], PRIMARY KEY (id))"
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _insert(db, node_id, vec):
    db.execute(
        "CREATE (n:CalibNode {id: $id, embedding: $vec})",
        {"id": node_id, "vec": vec},
    )


def test_vector_search_returns_cosine(calib_db):
    db = calib_db
    # Unit vectors with known cosine similarities to the query [1,0,0,0]:
    _insert(db, "identical",  [1.0, 0.0, 0.0, 0.0])              # cos = 1.0
    _insert(db, "deg45",      [math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0])  # cos ≈ 0.7071
    _insert(db, "orthogonal", [0.0, 1.0, 0.0, 0.0])              # cos = 0.0
    db.create_vector_index("CalibNode", "embedding", "calib_idx")

    rows = db.vector_search("CalibNode", "calib_idx", [1.0, 0.0, 0.0, 0.0], 3)
    scores = {r["node"]["id"]: r["score"] for r in rows}

    assert abs(scores["identical"] - 1.0) < 0.01
    assert abs(scores["deg45"] - 0.7071) < 0.02
    assert abs(scores["orthogonal"] - 0.0) < 0.02
```

Note: FLOAT[4] keeps the fixture readable. If Kuzu 0.11.3 HNSW requires a minimum dimension, fall back to FLOAT[384] with vectors padded with zeros — cosine values are unchanged.

Run it BEFORE changing the facade. The observed scores tell you which metric the index actually uses:
- identical→1.0, orthogonal→0.5, deg45→~0.67  ⇒ metric is **cosine** (`score=1/(1+d_cos)`)
- identical→1.0, orthogonal→~0.414, deg45→~0.567 ⇒ metric is **L2** (`score=1/(1+d_l2)`)

Record the finding in the commit message.

### Step 2: Fix the facade

In `campy/brain/hippocampus/graph/kuzu_client.py`:

1. `create_vector_index()` — pass the metric explicitly. Kuzu 0.11.x signature supports optional params; check `CALL CREATE_VECTOR_INDEX('tbl','idx','prop', metric := 'cosine')`. If the pinned version rejects the named arg, keep the default but assert it in the calibration test and document it.

2. `vector_search()` — replace the score transform with a metric-correct cosine conversion:

```python
# Kuzu 0.11.3 HNSW distance semantics (verified by tests/test_vector_calibration.py):
#   metric = cosine → distance = 1 - cosine_similarity
#   metric = l2     → distance = sqrt(2 - 2*cos) for unit vectors
# We return TRUE COSINE SIMILARITY so thresholds across the codebase
# (Step 5 dedup 0.75/0.92, routing 0.85, analogical 0.7) are meaningful.
if _INDEX_METRIC == "cosine":
    score = 1.0 - distance
else:  # l2 on normalized vectors
    score = 1.0 - (distance * distance) / 2.0
score = max(-1.0, min(1.0, score))
```

Module-level `_INDEX_METRIC` constant set from the Step 1 finding; if Kuzu accepts the explicit metric arg, set both to `"cosine"`.

### Step 3: Threshold audit

For every consumer below, decide: keep the documented threshold (now correct under true cosine) or adjust. Default position: **the documented values were the design intent — keep them, now that scores are真 cosine.** But verify against live behavior where tests exist.

| File | Constant | Documented intent | Action |
|---|---|---|---|
| `temporal_lobe/loop/step5_retrieval.py` | `MATCH_THRESHOLD=0.75`, `GRAY_ZONE_UPPER=0.92`, `TOPO_SEARCH_FLOOR=0.55` | cosine | Keep values; update comment: "true cosine similarity (B279)" |
| `hippocampus/hippocampus.py` | `S1_AUTO_BIND_THRESHOLD=0.85`, `S1_ESCALATION_THRESHOLD=0.60` | cosine | Keep; add comment |
| `thalamus/analogical.py` | `min_similarity=0.7` default | cosine | Keep; add comment |
| `temporal_lobe/warm_frontier.py` | `MIN_ACTIVATION=0.3`, `SIMILARITY_WEIGHT=0.6` | activation score derived from similarity | Keep; add comment |
| `brainstem/sweep.py` | resurrection_threshold + frustration cluster cosine 0.65 | frustration clusters compute cosine in numpy already (correct); resurrection uses vector_search score | Verify resurrection threshold semantics, comment |
| `basal_ganglia/action_selector.py`, `exploration_policy.py` | implicit use of `score` | cosine | Add comment |
| `thalamus/tools/__init__.py` (current_truth, recall_*, register_plan dedup at line ~567) | various | cosine | Grep for hardcoded score comparisons; comment each |

Grep command for the implementer: `rg -n "score|similarity" campy/brain --include="*.py" -g '!__pycache__' | rg "0\.[0-9]"` and check each hit that compares against a vector_search result.

### Step 4: Behavioral smoke check

After the fix, scores generally INCREASE for near matches under metric=cosine (e.g. raw cos 0.913 used to read 0.92, now reads 0.913 — nearly unchanged) but DECREASE for weak matches (cos 0.667 used to read 0.75, now reads 0.667). Expected behavioral deltas:
- Fewer false "matches" at the 0.75 boundary (weak candidates no longer clear MATCH_THRESHOLD).
- The 0.92 additive-merge boundary fires on genuinely-similar concepts instead of near-exact only (if metric was L2) or behaves nearly the same (if cosine).

Run the dedup-relevant test files and eyeball: `pytest tests/ -q -k "step5 or orchestrator or retrieval or dedup"`.

## Validation Commands

```bash
pytest tests/test_vector_calibration.py -v
pytest tests/ -q -k "step5 or orchestrator or retrieval"
pytest tests/test_web.py tests/test_b195_proactive_push.py -q
python3 -m py_compile campy/brain/hippocampus/graph/kuzu_client.py
```

## Risks

- Changing score semantics shifts live behavior (dedup rate, routing). Mitigate: land the calibration test in the same commit; note the metric finding in the commit message; monitor `~/.campy/activity.log` for a few sessions after deploy.
- Kuzu 0.11.3 may not accept an explicit metric arg — acceptable; the test pins the default and the transform compensates.
- The existing graph contains nodes deduped under the old scale. Do NOT attempt retroactive re-dedup in this card; if duplicate accumulation is confirmed, file a follow-up sweep card.
