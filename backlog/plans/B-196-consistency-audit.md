# Plan for B196 — Internal Consistency Audit

## Card Metadata
- **Card ID**: B196
- **Priority**: P3
- **Dependencies**: None

## Summary
Add `_audit_consistency()` sweep step that detects contradicting Lessons within the same domain, stale Lessons with no recent activity, and orphan Lessons with no inbound edges.

## Technical Approach

### Step 1: Schema addition (schema.py)

Add `last_audited_at` to Lesson node if not present:
```python
# In Lesson DDL, add:
last_audited_at  TIMESTAMP,
```

### Step 2: Add _audit_consistency() to sweep.py

Insert after dreaming (B191) step, before centroid recomputation:

```python
async def _audit_consistency(db, config, llm_client) -> dict:
    audit_cfg = config.get("sweep", {}).get("consistency_audit", {})
    if not audit_cfg.get("enabled", False) or not llm_client:
        return {"skipped": True}

    max_llm_calls = audit_cfg.get("max_llm_calls_per_sweep", 10)
    stale_days = audit_cfg.get("stale_threshold_days", 30)
    llm_calls = 0
    contradictions_found = 0
    stale_flagged = 0
    orphans_flagged = 0
    now = datetime.now(timezone.utc).isoformat()

    # --- Pairwise contradiction detection ---
    # Get distinct domains with 2+ active Lessons
    domains = await db.execute("""
        MATCH (l:Lesson) WHERE l.archived = false AND l.pathway_strength > 0.3
        RETURN l.domain, count(l) AS cnt
    """)

    for domain, count in domains:
        if count < 2 or llm_calls >= max_llm_calls:
            continue

        # Top-20 highest-strength Lessons per domain
        lessons = await db.execute("""
            MATCH (l:Lesson)
            WHERE l.domain = $domain AND l.archived = false AND l.pathway_strength > 0.3
            RETURN l.lesson_id, l.text_raw, l.embedding, l.pathway_strength
            ORDER BY l.pathway_strength DESC
            LIMIT 20
        """, {"domain": domain})

        # Pairwise vector similarity in application code
        for i in range(len(lessons)):
            for j in range(i + 1, len(lessons)):
                if llm_calls >= max_llm_calls:
                    break
                sim = emb.cosine_similarity(lessons[i][2], lessons[j][2])
                if sim < 0.70:
                    continue  # Not similar enough to be contradictory

                # LLM check: are these contradictory?
                prompt = f"""Do these two lessons contradict each other?
Lesson A: {lessons[i][1]}
Lesson B: {lessons[j][1]}
Answer: CONTRADICT, COMPATIBLE, or SUPERSEDES_A_OVER_B / SUPERSEDES_B_OVER_A"""
                response = await llm_client.chat(prompt)
                llm_calls += 1

                verdict = _parse_audit_verdict(response)
                if verdict == "CONTRADICT":
                    # Create DisambiguationEvent
                    await _create_disambiguation_event(db, lessons[i], lessons[j], now)
                    contradictions_found += 1
                elif verdict.startswith("SUPERSEDES"):
                    # Archive the superseded one, create DEPRECATED_BY edge
                    old_idx = 0 if "A_OVER_B" in verdict else 1
                    new_idx = 1 - old_idx
                    await _deprecate_lesson(db, lessons[old_idx], lessons[new_idx], now)

        # Mark audited
        for lesson in lessons:
            await db.execute_write("""
                MATCH (l:Lesson {lesson_id: $lid})
                SET l.last_audited_at = timestamp($now)
            """, {"lid": lesson[0], "now": now})

    # --- Stale detection ---
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
    stale = await db.execute("""
        MATCH (l:Lesson)
        WHERE l.archived = false AND l.lesson_type != 'synthesis'
          AND l.created_at < timestamp($cutoff)
          AND NOT EXISTS { MATCH (l)-[:APPLIES_TO|RELATED_TO|GENERALIZES_LESSON]->() }
        RETURN l.lesson_id
    """, {"cutoff": stale_cutoff})
    stale_flagged = len(stale)
    # Flag stale lessons by reducing pathway_strength
    for row in stale:
        await db.execute_write("""
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.pathway_strength = l.pathway_strength * 0.5
        """, {"lid": row[0]})

    # --- Orphan detection ---
    orphans = await db.execute("""
        MATCH (l:Lesson)
        WHERE l.archived = false
          AND NOT EXISTS { MATCH ()-[:CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED]->(l) }
        RETURN l.lesson_id
    """)
    orphans_flagged = len(orphans)

    return {
        "contradictions_found": contradictions_found,
        "stale_flagged": stale_flagged,
        "orphans_flagged": orphans_flagged,
        "llm_calls_used": llm_calls,
    }
```

### Step 3: Config in sidequests.toml

```toml
[sweep.consistency_audit]
enabled = true
max_llm_calls_per_sweep = 10
stale_threshold_days = 30
```

### Step 4: Tests

Create `tests/test_b196_consistency_audit.py`:
1. Test contradicting Lessons detected → DisambiguationEvent created
2. Test compatible Lessons → no event
3. Test superseding → DEPRECATED_BY edge + archive
4. Test stale Lessons flagged (30+ days, no activity edges)
5. Test orphan Lessons detected (no inbound edges)
6. Test max_llm_calls cap respected
7. Test top-20 per domain limit
8. Test skipped when disabled in config

## Verification
```bash
pytest tests/test_b196_consistency_audit.py -v
```
