# Plan for B193 — Metacognition: Knowledge Gap Detection

## Card Metadata
- **Card ID**: B193
- **Priority**: P2
- **Dependencies**: B191 (meta-lessons provide coverage baseline)

## Summary
Add KnowledgeGap node type and sweep step that identifies domains with high message count but low lesson count. Expose via `get_knowledge_gaps` tool.

## Technical Approach

### Step 1: Schema additions (schema.py)

Node type:
```python
"KnowledgeGap": """
    gap_id           STRING,
    domain           STRING,
    gap_type         STRING,
    description      STRING,
    severity         DOUBLE,
    message_count    INT32,
    lesson_count     INT32,
    resolved         BOOLEAN,
    created_at       TIMESTAMP,
    resolved_at      TIMESTAMP,
    PRIMARY KEY (gap_id)
""",
```

Relationship:
```python
"CREATE REL TABLE IF NOT EXISTS IDENTIFIED_GAP_IN (FROM KnowledgeGap TO MainQuest, FROM KnowledgeGap TO Concept)",
```

### Step 2: Add _detect_knowledge_gaps() to sweep.py

```python
async def _detect_knowledge_gaps(db) -> dict:
    # Count lessons per domain
    domain_lessons = await db.execute("""
        MATCH (l:Lesson) WHERE l.archived = false
        RETURN l.domain AS domain, count(l) AS lesson_count
    """)
    lesson_map = {r[0]: r[1] for r in domain_lessons}

    # Count messages per gist_class (proxy for domain)
    domain_messages = await db.execute("""
        MATCH (m:Message)-[:ESTABLISHED]->(c:Concept)
        WHERE c.archived = false
        RETURN c.gist_class AS domain, count(DISTINCT m) AS msg_count
    """)

    gaps_created = 0
    for domain, msg_count in domain_messages:
        lesson_count = lesson_map.get(domain, 0)
        if msg_count >= 5 and lesson_count < 2:
            severity = min(1.0, msg_count / (lesson_count + 1) / 10)
            # Check if gap already exists
            existing = await db.execute("""
                MATCH (g:KnowledgeGap {domain: $domain, resolved: false})
                RETURN g.gap_id
            """, {"domain": domain})
            if not existing:
                gap_id = f"gap_{domain}_{int(time.time())}"
                await db.execute_write("""
                    CREATE (g:KnowledgeGap {gap_id: $id, domain: $domain,
                        gap_type: 'missing_lessons', severity: $sev,
                        message_count: $msgs, lesson_count: $lessons,
                        resolved: false, created_at: timestamp($now),
                        description: $desc})
                """, {...})
                gaps_created += 1

    return {"gaps_created": gaps_created}
```

### Step 3: Auto-resolve gaps when lessons are created

In step7_5_lesson.py, after creating a Lesson, check if it resolves a gap:
```python
await db.execute_write("""
    MATCH (g:KnowledgeGap {domain: $domain, resolved: false})
    SET g.resolved = true, g.resolved_at = timestamp($now)
""", {"domain": lesson_domain, "now": now})
```

### Step 4: Add get_knowledge_gaps tool

Return active (unresolved) gaps sorted by severity.

### Step 5: Tests
1. Test gap detected: 10 messages, 0 lessons → gap created
2. Test no gap: 10 messages, 5 lessons → no gap
3. Test auto-resolve: creating lesson in gap domain resolves the gap
4. Test no duplicate gaps for same domain

## Verification
```bash
pytest tests/test_b193_metacognition.py -v
```
