# B-11-lesson-artifact-node — Lesson Artifact Node

**Card:** B11 | **Priority:** P5 | **Depends on:** None (schema extension)

## Summary
Add a new `Lesson` artifact node type to the knowledge graph schema. Lessons capture domain-specific insights that survived multiple attempts or edge cases, enabling transfer learning across projects.

## Technical Approach

### Schema Addition
New node type `Lesson` with properties:
```
Lesson(
  lesson_id STRING PRIMARY KEY,
  text_raw STRING,
  embedding FLOAT[384],
  embedding_model STRING,
  domain STRING,  -- e.g., "rust", "graph-databases", "llm-routing"
  lesson_type STRING ENUM('mistake', 'edge-case', 'optimization', 'architecture-principle'),
  confidence FLOAT,
  archived BOOLEAN,
  created_at TIMESTAMP,
  pathway_strength FLOAT
)
```

### Relationships
```
(Session)-[LEARNED]->(Lesson)  -- explicit: when user or LLM articulates a lesson
(Lesson)-[APPLIES_TO]->(Concept | Decision | Requirement)  -- domain mapping
(Lesson)-[RELATED_TO]->(Lesson)  -- lesson similarity/redundancy
(Message)-[CONTAINS_LESSON]->(Lesson)  -- provenance
```

### Extraction Logic
Step 7.5 (new pipeline step): After pathway update, scan for lesson indicators:
- "we learned", "next time", "for future", "avoid", "best practice", "pattern is"
- LLM extracts candidates, stores as `Lesson` with opportunistic domain inference

### Tools Update
- `upsert_lesson` tool: user or LLM can explicitly add lessons
- `recall_relevant_lessons` tool: given domain or node, fetch relevant lessons
- Update `current_truth` to optionally include lessons in retrieval results

## Files to Create/Modify

- `mcp_engine/schema.py` — add Lesson node type and relationships
- `mcp_engine/loop/step7_pathway.py` — add lesson extraction logic
- `mcp_engine/tools.py` — add `upsert_lesson` and `recall_relevant_lessons`
- `tests/test_lesson_artifact.py` — schema validation, extraction, retrieval
- Update tests/test_schema.py to verify Lesson node creation

## Acceptance Criteria

1. `Lesson` node type exists in schema with all required properties
2. `LEARNED`, `APPLIES_TO`, `RELATED_TO` relationships are defined
3. Lesson extraction (Step 7.5) identifies lesson indicators in turn content
4. `upsert_lesson` tool accepts domain, lesson_type, text; creates or updates node
5. `recall_relevant_lessons` returns lessons matching a domain (with filtering)
6. Lessons integrate into `current_truth` optional results (not blocking, supplementary)
7. Integration: message with "learned X" → Lesson node created → `recall_relevant_lessons` finds it

## Notes

- Lessons are medium-confidence signals — don't auto-promote to Decision level
- Domain inference is best-effort (heuristic or LLM); fallback to generic if ambiguous
