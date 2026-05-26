# Auto-Skill Generation ("The Basal Ganglia")

## Context

Campy's dreaming sweep (`_synthesize_procedures()`) already distills reusable Procedures from clusters of successful Plans. But it only fires on repetition (Plans sharing a `strategy` string) and misses a critical signal: **pain**. In human neuroscience, the basal ganglia handles both procedural learning (repetition → habit) and avoidance learning (pain → "don't do that"). Campy has the Amygdala (emotional salience weighting) but no mechanism to translate concentrated frustration into actionable avoidance Procedures.

**Problem:** High-frustration areas in the graph don't automatically generate avoidance knowledge. A user can say "NO! I told you three times!" and the salience multiplier boosts pathway_strength, but no Procedure exists to prevent the same mistake from recurring. Meanwhile, existing Procedure synthesis requires 3+ Plans with identical strategy strings — too high a bar for many useful patterns.

**Solution:** Add two Procedure synthesis triggers to the dreaming sweep:
1. **Frustration clusters** → avoidance Procedures (graph-only, no LLM)
2. **Enhanced Plan clustering** → automation Procedures (existing LLM path, lower threshold)

Add a maturity lifecycle (nascent → developing → mature → degraded → archived) and store `salience_score` on nodes to enable frustration cluster queries.

## Design

### 1. Salience Score Storage

The Amygdala (shipped in `280e2a68`) computes `salience_multiplier` at encoding time but discards it after applying to `pathway_strength`. The Basal Ganglia needs access to this raw signal during sweeps.

**Change:** When `_store_concept()` writes nodes to KuzuDB, include `salience_score` alongside existing `pathway_strength` and `confidence`:

```python
# In _store_concept(), add to the CREATE/MERGE params:
"salience_score": salience,  # preserve encoding-time emotional signal
```

**Schema:** Add `salience_score FLOAT DEFAULT 1.0` to all GCL-encoded node tables (Concept, Decision, Constraint).

**Why store it?** `pathway_strength = confidence * salience` at encoding, but pathway_strength is subsequently modified by Hebbian reinforcement and Ebbinghaus decay. After one sleep cycle, the original salience is irrecoverable from pathway_strength. The salience_score property preserves the encoding-time emotional signal permanently.

**Graph modeling rationale:** Per anti-pattern #4 ("don't create node explosions for scalar facts"), salience_score is a scalar property on existing nodes, not a new node type. It has no lifecycle (write-once at encoding), no relationships, and no independent identity.

### 2. Frustration Cluster Detection (Avoidance Archetype)

New function `_detect_frustration_clusters()` in `sweep.py`, called during dreaming sweeps.

**Algorithm:**

1. **Query high-salience nodes** created since last sweep:
   ```cypher
   MATCH (n:Concept) WHERE n.salience_score >= 1.3
     AND n.created_at > timestamp($since)
     AND n.archived = false
   RETURN n.concept_id AS id, n.name AS name, n.description AS desc,
          n.embedding AS emb, n.salience_score AS salience
   ```
   (Separately for Concept, Decision, Constraint — the types most likely to carry frustration context.)

2. **Cluster by embedding similarity:** Greedy single-linkage clustering — for each unvisited high-salience node, expand the cluster by adding any other unvisited high-salience node with cosine similarity >= 0.65. Continue until no more nodes qualify. Keep clusters with >= 3 members.

3. **Synthesize avoidance Procedure (no LLM):** For each qualifying cluster:
   - `name`: `"Avoid: {cluster_topic}"` (most frequent entity name in cluster)
   - `description`: Assembled from cluster node descriptions
   - `steps_json`: Avoidance steps extracted from Lesson text linked to cluster nodes
   - `archetype`: `"avoidance"`
   - `domain`: `"auto-discovered"`
   - `salience_score`: Average salience of the cluster

4. **Link to source nodes:** `DISTILLED_FROM` edges from new Procedure to each cluster member.

5. **Auto-bind trigger metadata:** Extract the most common error pattern from cluster source messages. Set `trigger_pattern`, `trigger_hook_type="PreToolUse"`, `trigger_tool=""`.

**Cost model:** Cypher queries + in-memory clustering. No LLM calls. Near-zero cost.

### 3. Enhanced Plan Clustering (Automation Archetype)

Enhance existing `_synthesize_procedures()`, not replace it.

**Changes:**
- Lower `min_cluster_size` from 3 to 2
- Set `archetype = "automation"` on newly synthesized Procedures
- Compute `salience_score` as average salience across source Plans' linked nodes
- Skip synthesis when a Procedure with the same archetype already exists (prevent duplicates)

**Existing behavior preserved:** LLM synthesis path, DISTILLED_FROM edges, embedding computation, trigger binding all unchanged.

### 4. Maturity Tracking

Add `maturity_stage STRING DEFAULT 'nascent'` to Procedure node table.

**Stages:**

| Stage | Criteria | Effect |
|---|---|---|
| `nascent` | `application_count < 3` | Normal pathway_strength |
| `developing` | `application_count >= 3 AND success_rate >= 0.5` | +10% pathway_strength boost |
| `mature` | `application_count >= 5 AND success_rate >= 0.75` | +25% pathway_strength boost |

New function `_update_procedure_maturity()` runs during sweeps after Procedure synthesis:

```python
async def _update_procedure_maturity(db, config):
    """Update maturity_stage and apply pathway_strength boosts."""
    await db.execute_write(
        "MATCH (p:Procedure) WHERE p.archived = false "
        "SET p.maturity_stage = CASE "
        "  WHEN p.application_count >= 5 AND p.success_rate >= 0.75 THEN 'mature' "
        "  WHEN p.application_count >= 3 AND p.success_rate >= 0.50 THEN 'developing' "
        "  ELSE 'nascent' END"
    )
```

Pathway strength boosts: track `last_maturity_boost` timestamp on the Procedure. During maturity update, only apply the boost if `maturity_stage` actually changed this sweep. This prevents compounding boosts across sweeps.

**Trigger manifest integration:** Already sorts by `pathway_strength DESC` — mature Procedures rank higher automatically.

### 5. Procedure Lifecycle — Pruning & Staleness

**Already handled:**
- **Ebbinghaus decay:** Procedures decay like all nodes. Unused ones archive naturally.
- **Success tracking:** `application_count`, `success_count`, `success_rate` already exist and are updated by `report_outcome`.

**New — degradation detection:**

| Condition | Action |
|---|---|
| `application_count >= 3 AND success_rate < 0.30` | Set `maturity_stage = 'degraded'`, halve `pathway_strength` |
| `maturity_stage = 'degraded'` and still `success_rate < 0.20` after next sweep | Archive the Procedure |

**Avoidance Procedure staleness:** During frustration cluster detection, also check for "resolution clusters" — nodes with high positive salience (excitement signals) whose embeddings overlap with existing avoidance Procedures. When found, downgrade the avoidance Procedure to `degraded`.

Full lifecycle:

```
nascent → developing → mature        (happy path)
                    ↘ degraded → archived  (failure/staleness path)
```

### What Doesn't Change

- **ASSISTANT_CAP (0.85):** Unchanged
- **Existing sweep steps:** Ebbinghaus decay, Hebbian promotion, consistency audit, centroid recomputation — all unmodified
- **sweep_patterns.py failure-sequence Procedures:** Continue working unchanged
- **Trigger manifest compilation:** Already sorts by pathway_strength, already filters archived
- **Step 4b (Anticipatory Engine):** Already auto-binds triggers to new Procedures
- **Recall tools:** Already return Procedures by success_rate/success_count
- **Layer 4 skills:** No disk-based skills generated — purely graph-native
- **No new dependencies:** Cypher queries + existing embedding infrastructure

## Implementation

### Files to modify (4)

| File | Change |
|---|---|
| `mcp_engine/loop/orchestrator.py` | Write `salience_score` property when storing nodes (~3 lines) |
| `mcp_engine/sweep.py` | Add `_detect_frustration_clusters()` (~50 lines), enhance `_synthesize_procedures()` (~15 lines), add `_update_procedure_maturity()` (~20 lines), wire into `_dream_consolidation()` (~5 lines) |
| `mcp_engine/schema.py` | Add `salience_score FLOAT DEFAULT 1.0` to node tables, `maturity_stage STRING DEFAULT 'nascent'` to Procedure (~6 lines) |
| `docs/ARCHITECTURE.md` | Document Basal Ganglia in biomimetic architecture section |

### No new files

All changes are to existing modules. No schema migration tool needed — KuzuDB `ALTER TABLE ADD COLUMN` handles runtime additions.

### Testing

| Test | Expected |
|---|---|
| `salience_score` written on new nodes | Node query returns salience_score matching compute_salience_multiplier output |
| Frustration cluster: 3+ high-salience nodes on same topic | New avoidance Procedure created with archetype="avoidance" |
| Frustration cluster: 2 high-salience nodes (below threshold) | No Procedure created |
| Enhanced Plan clustering: 2 Plans with same strategy | New automation Procedure created (was 3 before) |
| Duplicate prevention: same strategy clustered again | No duplicate Procedure |
| Maturity: application_count=5, success_rate=0.80 | maturity_stage="mature" |
| Maturity: application_count=3, success_rate=0.25 | maturity_stage="degraded", pathway_strength halved |
| Degraded + still failing | Procedure archived |
| Avoidance staleness: positive sentiment on same topic | Avoidance Procedure degraded |
| Full pipeline: frustrated messages → sleep → Procedure appears | End-to-end integration |

## IP Significance

This adds the **Basal Ganglia** to Campy's biomimetic architecture. The existing system models:
- **Hebbian learning** (fire-together-wire-together) — co-occurrence strengthening
- **Synaptic pruning** (Ebbinghaus decay) — forgetting curve
- **Hippocampus** (quest routing) — goal-directed navigation
- **Cocktail party effect** (selective attention) — signal detection
- **Amygdala** (emotional salience) — encoding intensity multiplier

Auto-skill generation adds:
- **Basal ganglia (procedural learning)** — repetition → automation habits
- **Basal ganglia (avoidance learning)** — pain → "don't do that" reflexes
- **Maturity tracking** — skill confidence lifecycle analogous to motor skill acquisition stages

The synergy between Amygdala and Basal Ganglia is the key insight: emotional salience at encoding time (Amygdala) feeds frustration cluster detection at consolidation time (Basal Ganglia). Pain drives habit formation — the same mechanism that makes you pull your hand from a hot stove.

## Implementation Status

| Step | Status | Commit |
|---|---|---|
| Store salience_score on nodes | Complete | `894907ed` |
| Frustration cluster detection | Complete | `d31e5fa8` |
| Enhanced Plan clustering | Complete | `a06320d4` |
| Maturity tracking + degradation | Complete | `a06320d4` |
| Architecture docs | Complete | — |
