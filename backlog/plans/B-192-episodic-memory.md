# Plan for B192 — Episodic Memory: Temporal Chains

## Card Metadata
- **Card ID**: B192
- **Priority**: P2
- **Dependencies**: None

## Summary
Add FOLLOWED_BY edges between consecutive Messages within a Session. Add reconstruct_timeline tool for temporal chain traversal.

## Technical Approach

### Step 1: Schema additions (schema.py)
```python
"CREATE REL TABLE IF NOT EXISTS FOLLOWED_BY (FROM Message TO Message, gap_seconds DOUBLE)",
"CREATE REL TABLE IF NOT EXISTS DECISION_CHAIN (FROM Decision TO Decision, session_id STRING, step_number INT32)",
```

### Step 2: Write FOLLOWED_BY in notify_turn (tools/__init__.py)

In the `notify_turn` handler, after creating the Message node:

```python
# Find the previous message in this session
prev_msg = await db.execute("""
    MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
    WHERE m.message_id != $current_id
    RETURN m.message_id, m.created_at
    ORDER BY m.created_at DESC LIMIT 1
""", {"sid": session_id, "current_id": msg_id})

if prev_msg:
    gap = (current_time - prev_msg[0]["created_at"]).total_seconds()
    await db.execute_write("""
        MATCH (prev:Message {message_id: $prev_id}), (curr:Message {message_id: $curr_id})
        CREATE (prev)-[:FOLLOWED_BY {gap_seconds: $gap}]->(curr)
    """, {"prev_id": prev_msg[0]["message_id"], "curr_id": msg_id, "gap": gap})
```

### Step 3: Write DECISION_CHAIN in step7_pathway.py

When a new Decision is established, link it to the previous Decision in the same session.

### Step 4: Add reconstruct_timeline tool

```python
# tool_schemas.py
"reconstruct_timeline": {
    "description": "Reconstruct the temporal sequence of messages and decisions for a topic",
    "inputSchema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "session_id": {"type": "string", "description": "Optional: limit to one session"},
            "max_hops": {"type": "integer", "default": 20}
        },
        "required": ["topic"]
    }
}
```

Handler: Find a starting Message mentioning the topic, walk FOLLOWED_BY chain, collect Decisions along the way.

### Step 5: Tests
Create `tests/test_b192_episodic_memory.py`:
1. Test FOLLOWED_BY created between consecutive messages
2. Test gap_seconds calculated correctly
3. Test DECISION_CHAIN links sequential decisions
4. Test reconstruct_timeline returns time-ordered results
5. Test bounded at max_hops

## Verification
```bash
pytest tests/test_b192_episodic_memory.py -v
```
