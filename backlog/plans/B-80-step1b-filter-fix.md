# B80 Plan — Fix Step 1b Filter Aggressiveness After O4 Fix

Card: B80
Priority: MEDIUM
Finding: R2-O2
Depends on: None

## Summary

Relax the Step 1b post-noise-filter to accept relations where at least the tail entity survived NER, even if the head is a noun chunk.

## Technical Approach

Currently:
```python
surviving_texts = {e["text"].lower() for e in typed_entities}
filtered_rels = [r for r in step1b_rels if r["head"].lower() in surviving_texts and r["tail"].lower() in surviving_texts]
```

Change to: keep the relation if at least one of head/tail is in surviving_texts (the NER-verified entities). This preserves the intent of filtering noise while allowing noun-chunk heads from verb pattern extraction.

Alternative: also add Step 1b head/tail texts to surviving_texts before filtering.

## Concrete File Changes

### 1. `mcp_engine/loop/orchestrator.py`
- Locate the Step 1b post-filter logic
- Change from `head in surviving AND tail in surviving` to `head in surviving OR tail in surviving`
- Or: add Step 1b heads/tails to surviving_texts before filtering

## Test Updates

- Add test: Step 1b relation with noun-chunk head + NER tail passes filter
- Add test: Step 1b relation with both noise head and tail is still filtered

## Acceptance Criteria

- Noun-chunk head relations preserved when tail is valid
- Fully-noise relations still filtered
- `pytest tests/ -k orchestrator -q` passes

## Validation Commands

```bash
pytest tests/ -k orchestrator -q
```

## Risks

- Relaxing from AND to OR may allow some false-positive relations. The tail-in-surviving check still provides quality gating for the most common case.
