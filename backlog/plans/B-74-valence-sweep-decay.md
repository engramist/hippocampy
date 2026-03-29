# B74 Plan — Wire Valence Into Sweep Decay Logic

Card: B74
Priority: HIGH
Finding: R2-P1
Depends on: B69

## Summary

Add a valence-aware phase to the background sweep that adjusts concept pathway_strength based on accumulated OUTCOME_SIGNAL edges.

## Technical Approach

After the standard Ebbinghaus decay phase, add a new phase:

1. Query all Concepts that have OUTCOME_SIGNAL edges:
   ```cypher
   MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept)
   WHERE c.archived = false
   RETURN c.concept_id, avg(o.valence) AS avg_valence, count(o) AS signal_count
   ```

2. For each concept with signals, adjust pathway_strength:
   ```python
   # Positive valence → slower decay (multiply by 1.0 to 1.3)
   # Negative valence → faster decay (multiply by 0.7 to 1.0)
   valence_factor = 1.0 + avg_valence * 0.3  # [-1,1] maps to [0.7, 1.3]
   # Apply atomically:
   SET c.pathway_strength = c.pathway_strength * $valence_factor
   ```

3. Cap at bounds: pathway_strength remains in [0.0, 1.0]

## Concrete File Changes

### 1. `mcp_engine/sweep.py`
- Add `_apply_valence_decay()` function after existing decay logic
- Query OUTCOME_SIGNAL edges in batch
- Apply atomic pathway_strength adjustment per concept
- Log how many concepts were valence-adjusted per sweep cycle

## Test Updates

- Add `test_sweep_valence_decay_negative()` — concept with negative OUTCOME_SIGNAL has lower pathway_strength after sweep
- Add `test_sweep_valence_decay_positive()` — concept with positive OUTCOME_SIGNAL retains more pathway_strength after sweep
- Add `test_sweep_valence_no_signals()` — concepts without OUTCOME_SIGNAL are unaffected

## Acceptance Criteria

- Sweep includes valence phase
- Negative-valence concepts decay faster
- Positive-valence concepts decay slower
- `pytest tests/ -k sweep -q` passes

## Validation Commands

```bash
pytest tests/ -k sweep -q
```

## Risks

- Double-counting: valence affects both live ranking (current_truth) and background decay. The 0.3 cap limits total influence. Monitor for over-penalization of failed-plan concepts.
