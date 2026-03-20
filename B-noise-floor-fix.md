# B-ISSUE-025: Noise Floor Too Aggressive — Decisions Dropped as Noise

## Problem

Step 2 gist classification drops decision-related messages as noise because:
1. The `NOISE_FLOOR` (0.25) is too high for `all-MiniLM-L6-v2` score distribution
2. Seed examples lack decision-oriented sentences for PhysicalThing/Category classes

**Evidence:**
- "We decided to use SQLAlchemy as the ORM" → best centroid score is PhysicalThing at 0.2355 → below 0.25 → dropped as noise
- "All API endpoints require JWT authentication" → Restriction at 0.4370 → passes to System 2 → works
- Result: Constraints are captured, Decisions are not

## Fix — Two Parts

### Part 1: Lower NOISE_FLOOR

**File:** `mcp_engine/loop/step2_gist.py`

**Change:** Line 16, change:
```python
NOISE_FLOOR       = 0.25
```
to:
```python
NOISE_FLOOR       = 0.18
```

**Why 0.18:** The SQLAlchemy message scores 0.2355 against PhysicalThing. We need headroom for even weaker signals. Cross-class noise scores range 0.01–0.13, so 0.18 is still well above random noise. Anything 0.18–0.50 goes to System 2 (LLM) for disambiguation — that's the correct behavior for ambiguous inputs.

### Part 2: Add Decision-Oriented Seed Examples

**File:** `InvertorsDocs/GistSeedExamples.md`

Add 5 new seed examples to **gist:PhysicalThing** section (after existing example 15). These should represent technology decision language — the gap the current seeds don't cover.

Add these lines after the last PhysicalThing example:
```
16. "We decided to use SQLAlchemy as the ORM for its migration support."
17. "We chose PostgreSQL over SQLite for the production database."
18. "The team selected FastAPI as the web framework for the REST API."
19. "We're using Redis as the caching layer instead of Memcached."
20. "The project runs on Docker containers deployed to AWS ECS."
```

Also add 3 decision-oriented examples to **gist:Category** section (after existing example 15):
```
16. "We defined the project as a microservices architecture rather than a monolith."
17. "The API versioning strategy is URL-based: /v1/, /v2/."
18. "We categorized this as a P0 critical bug, not a feature request."
```

### Part 3: Update Tests

**File:** `tests/test_loop.py`

Add one new test after the existing Step 2 tests that verifies a decision sentence is NOT classified as noise:

```python
def test_step2_decision_sentence_not_noise():
    """ISSUE-025: decision sentences about tools must not be dropped as noise."""
    from mcp_engine.loop.step2_gist import classify_concept, NOISE_FLOOR
    from mcp_engine.graph import embeddings as emb
    import numpy as np
    from pathlib import Path
    import re

    # Build centroids from seed file (same as daemon does)
    seed_path = Path('InvertorsDocs/GistSeedExamples.md')
    seed_text = seed_path.read_text()
    current_class = None
    class_vectors = {}
    for line in seed_text.split('\n'):
        if line.startswith('## '):
            match = re.search(r'gist:(\w+)', line)
            if match:
                current_class = match.group(1)
                class_vectors[current_class] = []
        elif re.match(r'\d+\.', line.strip()) and current_class:
            m = re.search(r'"(.+?)"', line)
            if m:
                class_vectors[current_class].append(emb.embed(m.group(1)))

    centroids = {}
    for cls, vecs in class_vectors.items():
        arr = np.array(vecs)
        mean = arr.mean(axis=0)
        norm = np.linalg.norm(mean)
        centroids[cls] = (mean / norm).tolist() if norm > 0 else mean.tolist()

    result = classify_concept(
        "SQLAlchemy",
        "sentence-transformers/all-MiniLM-L6-v2",
        centroids,
        None,  # no LLM — should still pass noise floor
        context="We decided to use SQLAlchemy as the ORM because it has better migration support than raw SQL."
    )
    assert result["system"] != "noise", (
        f"Decision sentence classified as noise (score={result['confidence']:.4f}, "
        f"NOISE_FLOOR={NOISE_FLOOR}). Expected System 1 or System 2."
    )
```

Find the right insertion point: search for the last Step 2 test (look for functions starting with `test_step2_`). If there are no Step 2 tests, insert before the first Step 4 test (`test_step4_decision_keywords_hard_lock`).

### Part 4: Log the Issue

**File:** `runningIssueLog.md`

Append this entry at the end of the file:

```markdown
---

### ISSUE-025 · Decisions dropped as noise — NOISE_FLOOR too aggressive for all-MiniLM-L6-v2
**Symptom:** "We decided to use SQLAlchemy as the ORM" processed by the Loop but zero concepts stored. `recent_decisions` always empty. JWT/constraint messages work fine.

**Root cause:** Step 2 `NOISE_FLOOR = 0.25` is too high for `all-MiniLM-L6-v2` cosine similarity scores against gist class centroids. Decision-oriented sentences score 0.20–0.24 against PhysicalThing centroid — just below the noise floor. Constraint sentences score 0.40+ against Restriction centroid — well above. Additionally, seed examples are biased toward constraint/restriction language with no decision-making examples for PhysicalThing or Category.

**Fix:** Lowered `NOISE_FLOOR` from 0.25 to 0.18 (still above cross-class noise range of 0.01–0.13). Added 5 decision-oriented seed examples to PhysicalThing and 3 to Category in `GistSeedExamples.md`.

**Files changed:** `mcp_engine/loop/step2_gist.py`, `InvertorsDocs/GistSeedExamples.md`, `tests/test_loop.py`, `runningIssueLog.md`
```

## Implementation Order

1. Edit `mcp_engine/loop/step2_gist.py` — change NOISE_FLOOR
2. Edit `InvertorsDocs/GistSeedExamples.md` — add seed examples
3. Edit `tests/test_loop.py` — add test
4. Edit `runningIssueLog.md` — log the issue
5. Run: `python3 -m pytest tests/test_loop.py -v` — verify new test passes
6. Run: `python3 -m pytest tests/ -v` — verify no regressions

## Verification

After implementation, run this to confirm the fix:
```python
python3 -c "
from mcp_engine.loop.step2_gist import classify_concept, NOISE_FLOOR
print(f'NOISE_FLOOR = {NOISE_FLOOR}')
# Should print system='1' or system='2_degraded', NOT 'noise'
"
```
