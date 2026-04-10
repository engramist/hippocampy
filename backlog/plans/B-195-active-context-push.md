# Plan for B195 — Active Context Push: Proactive Lesson Injection

## Card Metadata
- **Card ID**: B195
- **Priority**: P2
- **Dependencies**: None

## Summary
Extend `notify_turn` to return a `proactive_context` field containing high-signal Lessons relevant to the agent's current turn. Rate-limited to max 1 push per 5 turns.

## Technical Approach

### Step 1: Update tool schema (tool_schemas.py)

Add `proactive_context` to `notify_turn` response description:
```python
# In notify_turn schema, add to description:
# Response includes optional `proactive_context` field with relevant warnings/lessons
```

### Step 2: Proactive matching in notify_turn (tools/__init__.py)

After the existing `notify_turn` logic that creates the Message node and queues the consolidation loop:

```python
# --- Proactive Context Push (B195) ---
proactive_context = []
turn_count = await db.execute("""
    MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
    RETURN count(m) AS cnt
""", {"sid": session_id})

# Rate limit: only push every 5 turns
if turn_count and turn_count[0][0] % 5 == 0:
    # Embed the incoming turn text
    turn_embedding = emb.embed(text)

    # Vector search for high-signal Lessons
    matches = await db.execute("""
        CALL db.index.vector.queryNodes('lesson_emb_idx', $emb, 5)
        YIELD node, score
        WHERE score > 0.80 AND node.archived = false
          AND (abs(node.valence) > 0.7 OR node.pathway_strength > 0.8)
        RETURN node.lesson_id, node.text_raw, node.valence, node.domain, score
        ORDER BY score DESC
        LIMIT 2
    """, {"emb": turn_embedding})

    for row in matches:
        proactive_context.append({
            "lesson_id": row[0],
            "text": row[1],
            "valence": row[2],
            "domain": row[3],
            "relevance_score": row[4],
            "type": "warning" if row[2] < -0.3 else "hint",
        })

    # Track proactive push in working memory via LOADED edge
    for item in proactive_context:
        await db.execute_write("""
            MATCH (l:Lesson {lesson_id: $lid})
            MERGE (l)-[:LOADED {source: 'proactive_push', loaded_at: timestamp($now)}]->(l)
        """, {"lid": item["lesson_id"], "now": now})

# Include in response
result["proactive_context"] = proactive_context
```

### Step 3: Tests

Create `tests/test_b195_proactive_push.py`:
1. Test proactive_context returned when matching high-signal Lesson exists on turn 5
2. Test no proactive_context on turns 1-4 (rate limiting)
3. Test threshold: similarity < 0.80 → no push
4. Test threshold: |valence| < 0.7 AND pathway_strength < 0.8 → no push
5. Test negative-valence Lesson tagged as "warning"
6. Test empty proactive_context when no Lessons exist (no crash)
7. Test LOADED edge created with source = "proactive_push"

## Verification
```bash
pytest tests/test_b195_proactive_push.py -v
```
