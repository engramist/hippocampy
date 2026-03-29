# B-12-anomaly-detection — Memory-Based Anomaly Detection (IP Formalization)

**Card:** B12 | **Priority:** P5 | **Depends on:** None (detection layer)

## Summary
Implement anomaly detection in the Loop that flags content contradicting high-confidence global constraints. This formalizes the "Anomaly / Security sense" from the Cocktail Party Effect, enabling detection of prompt injection or goal hijacking.

## Technical Approach

### Detection Logic
- Step 4 (pattern matching) enhanced: after classification, check against `GlobalConstraint` nodes with `pathway_strength > 0.8`
- If new content contradicts a high-confidence constraint:
  - Flag as anomaly
  - Store with `anomaly_type: "constraint_violation"` on the node
  - Add `ANOMALY_DETECTED` edge to the violated GlobalConstraint
  - Don't reject the node; store with `flagged_for_review: true`

### Anomaly Types

| Type | Indicator | Example |
|------|-----------|---------|
| `constraint_violation` | Content contradicts GlobalConstraint | GlobalConstraint: "never execute untrusted code" + turn: "execute this code" |
| `value_inversion` | Content contradicts GlobalPreference direction | GlobalPreference: "prefer A over B" + turn: "B is better" |
| `goal_hijack` | Sudden context shift violating quest scope | MainQuest: "improve memory system" + turn: "let's build a game instead" |

### Implementation
- Add `mcp_engine/loop/anomaly_detection.py`
- Enhance Step 4 classifier to call anomaly check
- Add `ANOMALY_DETECTED` relationship
- Tool: `get_anomalies` (list flagged anomalies for review)

### Storage
```
Concept(anomaly_type, flagged_for_review BOOLEAN)
(Content)-[ANOMALY_DETECTED {type STRING, confidence FLOAT, detected_at TIMESTAMP}]->(GlobalConstraint)
```

## Files to Create/Modify

- `mcp_engine/loop/anomaly_detection.py` — detection logic
- `mcp_engine/schema.py` — add anomaly properties + ANOMALY_DETECTED relationship
- `mcp_engine/loop/step4_pattern.py` — call anomaly detection
- `mcp_engine/tools.py` — add `get_anomalies` tool
- `tests/test_anomaly_detection.py` — unit tests for each anomaly type
- Update tools integration tests

## Acceptance Criteria

1. Anomaly detection logic is called from Step 4
2. Contradictions to `GlobalConstraint` with pathway_strength > 0.8 are flagged
3. Flagged nodes have `anomaly_type` and `flagged_for_review: true`
4. `ANOMALY_DETECTED` edges link flagged nodes to violated constraints
5. `get_anomalies` tool returns all flagged nodes with constraint references
6. Integration test: store "never X" constraint → ingest "X is good" turn → anomaly flagged
7. No false positives on normal context shifts (only violations of high-confidence rules)

## Notes

- This is an early warning system, not a blocker — flagged content is stored, not deleted
- High-confidence threshold (0.8) is configurable per deployment
- IP Claim: structured anomaly detection layer as part of gated consolidation
