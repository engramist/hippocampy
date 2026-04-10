# Plan for B191 — Offline Consolidation / "Dreaming"

## Card Metadata
- **Card ID**: B191
- **Priority**: P1
- **Dependencies**: None

## Summary
Add a "dreaming" step to `run_sweep()` that clusters related Lessons by domain + embedding similarity, LLM-synthesizes meta-lessons, and links them via `GENERALIZES_LESSON` edges.

## Technical Approach

### Step 1: Add GENERALIZES_LESSON to schema.py
```python
"CREATE REL TABLE IF NOT EXISTS GENERALIZES_LESSON (FROM Lesson TO Lesson, synthesized_at TIMESTAMP, cluster_size INT32)",
```

### Step 2: Add config to sidequests.toml
```toml
[sweep.dreaming]
enabled = true
min_cluster_size = 3
similarity_threshold = 0.75
max_syntheses_per_sweep = 5
constituent_decay_multiplier = 1.5
```

### Step 3: Add _dream_consolidation() to sweep.py

After the decay step, before centroid recomputation:

```python
async def _dream_consolidation(db, config, llm_client) -> dict:
    dream_cfg = config.get("sweep", {}).get("dreaming", {})
    if not dream_cfg.get("enabled", False) or not llm_client:
        return {"skipped": True}

    min_cluster = dream_cfg.get("min_cluster_size", 3)
    sim_thresh = dream_cfg.get("similarity_threshold", 0.75)
    max_synth = dream_cfg.get("max_syntheses_per_sweep", 5)
    syntheses = 0

    # Get distinct domains with enough lessons
    domains = await db.execute("""
        MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type != 'synthesis'
        RETURN l.domain, count(l) AS cnt
        HAVING cnt >= $min_cluster
    """, {"min_cluster": min_cluster})

    for domain, count in domains:
        if syntheses >= max_synth:
            break

        # Get lessons in this domain
        lessons = await db.execute("""
            MATCH (l:Lesson)
            WHERE l.domain = $domain AND l.archived = false AND l.lesson_type != 'synthesis'
              AND NOT EXISTS { MATCH (m:Lesson)-[:GENERALIZES_LESSON]->(l) WHERE m.lesson_type = 'synthesis' }
            RETURN l.lesson_id, l.text_raw, l.embedding, l.pathway_strength
            ORDER BY l.pathway_strength DESC
            LIMIT 20
        """, {"domain": domain})

        # Cluster by embedding similarity (greedy: pick seed, expand cluster)
        clusters = _cluster_by_similarity(lessons, sim_thresh)

        for cluster in clusters:
            if len(cluster) < min_cluster or syntheses >= max_synth:
                continue

            # LLM synthesis
            lesson_texts = [l["text_raw"] for l in cluster]
            prompt = f"Synthesize these {len(cluster)} lessons about '{domain}' into one concise meta-lesson:\n\n" + "\n---\n".join(lesson_texts)
            response = await llm_client.chat(prompt)
            meta_text = _parse_synthesis(response)

            # Create meta-lesson
            meta_id = f"synthesis_{domain}_{int(time.time())}"
            embedding = emb.embed(meta_text)
            await db.execute_write("""
                CREATE (l:Lesson {lesson_id: $id, text_raw: $text, embedding: $emb,
                    domain: $domain, lesson_type: 'synthesis', confidence: 0.8,
                    pathway_strength: 0.9, archived: false, created_at: timestamp($now)})
            """, {...})

            # Link to constituents
            for constituent in cluster:
                await db.execute_write("""
                    MATCH (m:Lesson {lesson_id: $meta_id}), (c:Lesson {lesson_id: $const_id})
                    CREATE (m)-[:GENERALIZES_LESSON {synthesized_at: timestamp($now), cluster_size: $size}]->(c)
                """, {...})

            syntheses += 1

    return {"syntheses_created": syntheses}
```

### Step 4: Clustering function
```python
def _cluster_by_similarity(lessons, threshold):
    # Greedy single-linkage clustering
    # For each unclustered lesson, start cluster, add all lessons with similarity > threshold
    ...
```

### Step 5: Tests
Create `tests/test_b191_dreaming.py`:
1. Test clustering produces correct groups at threshold 0.75
2. Test LLM called with correct prompt format
3. Test meta-lesson created with lesson_type = "synthesis"
4. Test GENERALIZES_LESSON edges link to all constituents
5. Test already-synthesized lessons are excluded from re-synthesis
6. Test max_syntheses_per_sweep cap respected

## Verification
```bash
pytest tests/test_b191_dreaming.py -v
```
