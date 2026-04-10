# Plan for B194 — Procedural Memory: Reusable Solve Recipes

## Card Metadata
- **Card ID**: B194
- **Priority**: P1
- **Dependencies**: B191 (meta-lessons as input signal)

## Summary
Add Procedure node type for reusable, parameterized strategy templates. Synthesize from 3+ successful Plans in the same archetype. Expose via `recall_procedures` tool.

## Technical Approach

### Step 1: Schema additions (schema.py)

```python
"Procedure": """
    procedure_id       STRING,
    name               STRING,
    domain             STRING,
    archetype          STRING,
    description        STRING,
    steps_json         STRING,
    embedding          FLOAT[384],
    embedding_model    STRING,
    embedding_dim      INT64,
    success_count      INT32,
    application_count  INT32,
    success_rate       DOUBLE,
    confidence         DOUBLE,
    pathway_strength   DOUBLE,
    archived           BOOLEAN,
    created_at         TIMESTAMP,
    last_applied_at    TIMESTAMP,
    PRIMARY KEY (procedure_id)
""",
```

Relationships:
```python
"CREATE REL TABLE IF NOT EXISTS DISTILLED_FROM (FROM Procedure TO Plan, synthesized_at TIMESTAMP)",
"CREATE REL TABLE IF NOT EXISTS APPLIES_TO_ARCHETYPE (FROM Procedure TO Concept)",
"CREATE REL TABLE IF NOT EXISTS APPLIED_PROCEDURE (FROM Plan TO Procedure, success BOOLEAN, applied_at TIMESTAMP)",
```

### Step 2: Procedure synthesis in sweep (sweep.py)

Add to `_dream_consolidation()` or as separate step:

```python
async def _synthesize_procedures(db, llm_client, config) -> dict:
    # Find archetypes with 3+ successful plans
    results = await db.execute("""
        MATCH (p:Plan)
        WHERE p.valence > 0.5 AND p.status = 'completed'
        WITH p.strategy AS strategy_prefix, collect(p) AS plans
        WHERE size(plans) >= 3
        RETURN strategy_prefix, plans
    """)

    procedures_created = 0
    for strategy, plans in results:
        # Check if procedure already exists
        existing = await db.execute("""
            MATCH (proc:Procedure {archetype: $arch})
            WHERE proc.archived = false
            RETURN proc.procedure_id
        """, {"arch": strategy})
        if existing:
            continue

        # LLM synthesizes procedure from successful plans
        plan_summaries = [p["goal"] + ": " + p["strategy"] for p in plans[:5]]
        prompt = f"""Synthesize a reusable procedure from these {len(plan_summaries)} successful strategies:

{chr(10).join(plan_summaries)}

Return a JSON procedure with:
- name: short procedure name
- description: when to use this procedure
- steps: [{{"step": 1, "precondition": "...", "action": "...", "expected_outcome": "..."}}]
"""
        response = await llm_client.chat(prompt)
        procedure = _parse_procedure(response)

        # Create Procedure node
        proc_id = f"proc_{strategy}_{int(time.time())}"
        embedding = emb.embed(procedure["description"])
        await db.execute_write("""
            CREATE (p:Procedure {procedure_id: $id, name: $name, domain: $domain,
                archetype: $arch, description: $desc, steps_json: $steps,
                embedding: $emb, success_count: $count, application_count: 0,
                success_rate: 1.0, confidence: 0.7, pathway_strength: 0.8,
                archived: false, created_at: timestamp($now)})
        """, {...})

        # Link to source plans
        for plan in plans:
            await db.execute_write("""
                MATCH (proc:Procedure {procedure_id: $proc_id}), (p:Plan {plan_id: $plan_id})
                CREATE (proc)-[:DISTILLED_FROM {synthesized_at: timestamp($now)}]->(p)
            """, {...})

        procedures_created += 1

    return {"procedures_created": procedures_created}
```

### Step 3: recall_procedures tool

```python
async def recall_procedures(archetype, situation_embedding=None, limit=3):
    # Primary: match by archetype
    results = await db.execute("""
        MATCH (p:Procedure)
        WHERE p.archived = false AND p.archetype = $arch
        RETURN p ORDER BY p.success_rate DESC, p.success_count DESC
        LIMIT $limit
    """, {"arch": archetype, "limit": limit})

    # Secondary: vector search if situation provided
    if not results and situation_embedding:
        results = await db.execute("""
            CALL db.index.vector.queryNodes('procedure_emb_idx', $emb, $limit)
            YIELD node, score WHERE score > 0.70
            RETURN node, score
        """, {"emb": situation_embedding, "limit": limit})

    return results
```

### Step 4: Update procedure stats after application

In `report_outcome` handler, if the plan used a procedure:
```python
await db.execute_write("""
    MATCH (plan:Plan {plan_id: $pid})-[:APPLIED_PROCEDURE]->(proc:Procedure)
    SET proc.application_count = proc.application_count + 1,
        proc.success_rate = (proc.success_rate * (proc.application_count - 1) + $success) / proc.application_count,
        proc.last_applied_at = timestamp($now)
""", {"pid": plan_id, "success": 1.0 if valence > 0.5 else 0.0, "now": now})
```

### Step 5: Tests
1. Test 3 successful plans → procedure created
2. Test procedure has steps_json with correct structure
3. Test recall_procedures returns by archetype, ranked by success_rate
4. Test DISTILLED_FROM edges link to source plans
5. Test application_count and success_rate update correctly

## Verification
```bash
pytest tests/test_b194_procedural_memory.py -v
```
