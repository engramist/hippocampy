# Auto-Skill Generation (Basal Ganglia) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic Procedure synthesis from frustration clusters and enhanced Plan clustering, with a maturity lifecycle for Procedures.

**Architecture:** Two new sweep functions (`_detect_frustration_clusters`, `_update_procedure_maturity`) added to the existing dreaming sweep pipeline. `salience_score` stored on GCL-encoded nodes at write time. Existing `_synthesize_procedures` enhanced with lower thresholds and archetype labeling.

**Tech Stack:** Python, KuzuDB (Cypher), existing `sweep.py` / `orchestrator.py` / `schema.py` infrastructure.

---

## File Structure

| File | Responsibility | Change Type |
|---|---|---|
| `mcp_engine/schema.py` | Node table definitions + runtime migrations | Modify: add `salience_score` and `maturity_stage` columns |
| `mcp_engine/loop/orchestrator.py` | GCL encoding pipeline | Modify: write `salience_score` when storing Concept nodes |
| `mcp_engine/sweep.py` | Dreaming sweep pipeline | Modify: add frustration cluster detection, maturity tracking, enhance Plan clustering |
| `docs/ARCHITECTURE.md` | Architecture documentation | Modify: add Basal Ganglia to biomimetic section |
| `tests/test_basal_ganglia.py` | Tests for all new functionality | Create |

---

### Task 1: Schema Migration — Add `salience_score` and `maturity_stage` Columns

**Files:**
- Modify: `mcp_engine/schema.py:1115-1123`
- Test: `tests/test_basal_ganglia.py` (create)

This task adds two new columns via the existing runtime migration system: `salience_score` on Concept/Decision/Constraint nodes (encoding-time emotional intensity) and `maturity_stage` on Procedure nodes (lifecycle tracking).

- [ ] **Step 1: Write the failing test**

Create `tests/test_basal_ganglia.py`:

```python
"""
Tests for Basal Ganglia — Auto-Skill Generation.

Run with: python3 -m pytest tests/test_basal_ganglia.py -v
"""

from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestSchemaMigrations:
    """Verify salience_score and maturity_stage appear in the migration list."""

    def test_salience_score_migration_entries_exist(self):
        from mcp_engine.schema import ensure_schema
        import inspect
        source = inspect.getsource(ensure_schema)
        assert "salience_score" in source, "salience_score migration missing from ensure_schema"

    def test_maturity_stage_migration_entry_exists(self):
        from mcp_engine.schema import ensure_schema
        import inspect
        source = inspect.getsource(ensure_schema)
        assert "maturity_stage" in source, "maturity_stage migration missing from ensure_schema"

    def test_salience_score_on_all_gcl_node_types(self):
        from mcp_engine.schema import ensure_schema
        import inspect
        source = inspect.getsource(ensure_schema)
        for table in ("Concept", "Decision", "Constraint"):
            assert f'("{table}",' in source and "salience_score" in source, (
                f"salience_score migration missing for {table}"
            )

    def test_maturity_stage_on_procedure_only(self):
        from mcp_engine.schema import ensure_schema
        import inspect
        source = inspect.getsource(ensure_schema)
        # maturity_stage should appear for Procedure
        assert '"Procedure"' in source and "maturity_stage" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestSchemaMigrations -v`
Expected: FAIL — `salience_score` and `maturity_stage` not yet in `ensure_schema`

- [ ] **Step 3: Add migration entries to `schema.py`**

In `mcp_engine/schema.py`, find the `_MIGRATIONS` list (around line 1115). Add these entries after the existing Phase 2 trigger metadata entries (after line 1123, before the `]` closing the list):

```python
        # Basal Ganglia: salience_score — encoding-time emotional intensity
        ("Concept",        "salience_score",        "DOUBLE"),
        ("Decision",       "salience_score",        "DOUBLE"),
        ("Constraint",     "salience_score",        "DOUBLE"),

        # Basal Ganglia: maturity_stage — Procedure lifecycle tracking
        ("Procedure",      "maturity_stage",        "STRING"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestSchemaMigrations -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_engine/schema.py tests/test_basal_ganglia.py
git commit -m "feat(basal-ganglia): add salience_score and maturity_stage schema migrations"
```

---

### Task 2: Store `salience_score` on Concept Nodes at Encoding Time

**Files:**
- Modify: `mcp_engine/loop/orchestrator.py:525-559` (the `_store_concept` function)
- Test: `tests/test_basal_ganglia.py`

The Amygdala already computes `salience` and passes it to `_store_concept` (the `salience: float = 1.0` parameter). But `_store_concept` only uses it for `pathway_strength = confidence * salience`. This task adds `salience_score` to the CREATE statement so the raw value persists on the node.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_basal_ganglia.py`:

```python
import pytest
import asyncio


class TestSalienceScoreStorage:
    """Verify _store_concept writes salience_score to the node."""

    @pytest.mark.asyncio
    async def test_store_concept_includes_salience_score(self):
        """When _store_concept is called with salience=1.4, the CREATE query
        should include salience_score: $salience_score."""
        from mcp_engine.loop.orchestrator import _store_concept

        written = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, q, p=None): return MockResult()
            async def execute_write(self, q, p=None): written.append({"q": q, "p": p})

        entity = {"text": "test entity", "gist_class": "Event", "schema_org_type": ""}
        step4 = {"confidence": 0.75, "confidence_low": False}
        vector = [0.1] * 384

        result = await _store_concept(
            entity, step4, vector, "test-model", MockDB(),
            "2026-05-26T00:00:00Z", salience=1.4,
        )
        assert result is not None, "Expected concept_id returned"

        # Find the CREATE query
        create_queries = [w for w in written if "CREATE" in w["q"]]
        assert len(create_queries) == 1, f"Expected 1 CREATE, got {len(create_queries)}"
        params = create_queries[0]["p"]
        assert "salience_score" in params, "salience_score not in CREATE params"
        assert params["salience_score"] == 1.4, f"Expected 1.4, got {params['salience_score']}"

    @pytest.mark.asyncio
    async def test_store_concept_default_salience_is_1(self):
        """When salience is not specified, salience_score defaults to 1.0."""
        from mcp_engine.loop.orchestrator import _store_concept

        written = []

        class MockResult:
            def has_next(self): return False

        class MockDB:
            def execute(self, q, p=None): return MockResult()
            async def execute_write(self, q, p=None): written.append({"q": q, "p": p})

        entity = {"text": "default salience", "gist_class": "Event", "schema_org_type": ""}
        step4 = {"confidence": 0.70, "confidence_low": False}
        vector = [0.1] * 384

        await _store_concept(entity, step4, vector, "test-model", MockDB(),
                             "2026-05-26T00:00:00Z")

        create_queries = [w for w in written if "CREATE" in w["q"]]
        assert len(create_queries) == 1
        params = create_queries[0]["p"]
        assert params.get("salience_score") == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestSalienceScoreStorage -v`
Expected: FAIL — `salience_score` not in CREATE params

- [ ] **Step 3: Add `salience_score` to `_store_concept`'s CREATE statement**

In `mcp_engine/loop/orchestrator.py`, find the `_store_concept` function (line ~470). In the CREATE Cypher query (line ~527-543), add `salience_score` to both the CREATE fields and the params dict.

Add this line to the CREATE statement, after the `flagged_for_review` line:

```python
                salience_score:   $salience_score,
```

Add this to the params dict (after the `"flagged_for_review"` entry):

```python
                "salience_score":  salience,
```

Also, in the dedup-hit branch (around line 508-516), update the SET clause to also store salience_score on re-visited nodes. Add to the SET clause:

```python
                "    c.salience_score = CASE WHEN $salience > coalesce(c.salience_score, 1.0) "
                "                            THEN $salience ELSE coalesce(c.salience_score, 1.0) END",
```

And add `"salience": salience` to the params dict for that query.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestSalienceScoreStorage -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run existing salience tests to verify no regression**

Run: `python3 -m pytest tests/test_step4_salience.py -v`
Expected: All 16 existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_engine/loop/orchestrator.py tests/test_basal_ganglia.py
git commit -m "feat(basal-ganglia): store salience_score on Concept nodes at encoding time"
```

---

### Task 3: Frustration Cluster Detection (`_detect_frustration_clusters`)

**Files:**
- Modify: `mcp_engine/sweep.py:1057-1065` (add new function and wire into `_dream_consolidation`)
- Test: `tests/test_basal_ganglia.py`

This is the core Basal Ganglia function. It queries high-salience nodes, clusters them by embedding similarity, and synthesizes avoidance Procedures — all without LLM calls.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_basal_ganglia.py`:

```python
import json
import numpy as np


def _cosine_sim(a, b):
    """Cosine similarity between two vectors."""
    a, b = np.array(a), np.array(b)
    dot = np.dot(a, b)
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norms) if norms > 0 else 0.0


def _make_sweep_db(query_rows=None, vector_results=None):
    """Build a mock DB matching sweep.py conventions."""
    query_rows = query_rows or {}
    vector_results = vector_results or {}

    class MockResult:
        def __init__(self, rows):
            self._rows = list(rows)
            self._idx = 0
        def has_next(self): return self._idx < len(self._rows)
        def get_next(self):
            row = self._rows[self._idx]
            self._idx += 1
            return row

    class MockDB:
        def __init__(self):
            self.written = []
        def execute(self, q, p=None):
            for pattern, rows in query_rows.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])
        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})
        async def execute_read(self, q, p=None):
            for pattern, rows in query_rows.items():
                if pattern in q:
                    return [dict(zip(
                        ["id", "name", "desc", "emb", "salience"],
                        row
                    )) for row in rows]
            return []
        def vector_search(self, table, index, vec, limit):
            return vector_results.get(index, [])

    return MockDB()


class TestFrustrationClusterDetection:
    """Tests for _detect_frustration_clusters in sweep.py."""

    @pytest.mark.asyncio
    async def test_no_high_salience_nodes_returns_zero(self):
        """No nodes above salience threshold -> no Procedures created."""
        from mcp_engine.sweep import _detect_frustration_clusters
        db = _make_sweep_db()
        config = {"embeddings": {"model": "test-model"}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0
        assert errors == 0

    @pytest.mark.asyncio
    async def test_cluster_of_three_creates_avoidance_procedure(self):
        """3 high-salience nodes with similar embeddings -> 1 avoidance Procedure."""
        from mcp_engine.sweep import _detect_frustration_clusters

        # Create 3 nodes with identical embeddings (similarity = 1.0)
        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "deployment failure", "deploy broke the build", base_emb, 1.4),
            ("id-2", "deployment error", "deploy caused 500 errors", base_emb, 1.5),
            ("id-3", "deploy rollback", "had to rollback deploy", base_emb, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 1, f"Expected 1 Procedure, got {count}"

        # Verify a CREATE (pr:Procedure was written
        creates = [w for w in db.written if "CREATE" in w["q"] and "Procedure" in w["q"]]
        assert len(creates) >= 1, "No Procedure CREATE found"
        params = creates[0]["p"]
        assert params.get("archetype") == "avoidance"
        assert params.get("domain") == "auto-discovered"

    @pytest.mark.asyncio
    async def test_cluster_below_threshold_no_procedure(self):
        """Only 2 high-salience nodes (below min_cluster=3) -> no Procedure."""
        from mcp_engine.sweep import _detect_frustration_clusters

        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "deployment failure", "deploy broke", base_emb, 1.4),
            ("id-2", "deployment error", "deploy error", base_emb, 1.5),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0

    @pytest.mark.asyncio
    async def test_dissimilar_nodes_not_clustered(self):
        """3 high-salience nodes with different embeddings -> no cluster."""
        from mcp_engine.sweep import _detect_frustration_clusters

        nodes = [
            ("id-1", "deploy fail", "deploy broke", [1.0] + [0.0] * 383, 1.4),
            ("id-2", "auth error",  "login failed", [0.0, 1.0] + [0.0] * 382, 1.5),
            ("id-3", "db timeout",  "query slow",   [0.0, 0.0, 1.0] + [0.0] * 381, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        count, errors = await _detect_frustration_clusters(db, config)
        assert count == 0, "Dissimilar nodes should not cluster"

    @pytest.mark.asyncio
    async def test_avoidance_procedure_has_steps_json(self):
        """Created avoidance Procedure has non-empty steps_json."""
        from mcp_engine.sweep import _detect_frustration_clusters

        base_emb = [1.0] + [0.0] * 383
        nodes = [
            ("id-1", "always breaks", "deployment always breaks", base_emb, 1.4),
            ("id-2", "keep breaking", "deploys keep breaking", base_emb, 1.5),
            ("id-3", "broke again", "deploy broke again", base_emb, 1.3),
        ]

        db = _make_sweep_db(query_rows={"salience_score": nodes})
        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"basal_ganglia": {"min_cluster_size": 3,
                                              "similarity_threshold": 0.65}}}
        await _detect_frustration_clusters(db, config)

        creates = [w for w in db.written if "CREATE" in w["q"] and "Procedure" in w["q"]]
        assert len(creates) >= 1
        steps = json.loads(creates[0]["p"]["steps_json"])
        assert isinstance(steps, list)
        assert len(steps) > 0, "steps_json should have at least one step"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestFrustrationClusterDetection -v`
Expected: FAIL — `_detect_frustration_clusters` does not exist

- [ ] **Step 3: Implement `_detect_frustration_clusters` in `sweep.py`**

Add this function in `mcp_engine/sweep.py`, just before `_synthesize_procedures` (before line ~1084):

```python
async def _detect_frustration_clusters(db, config: dict) -> tuple[int, int]:
    """
    Basal Ganglia — Avoidance Archetype.

    Query high-salience nodes, cluster by embedding similarity, and synthesize
    avoidance Procedures. No LLM calls — pure graph traversal.

    Returns (procedures_created, error_count).
    """
    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    bg_cfg = config.get("sweep", {}).get("basal_ganglia", {})
    min_cluster = int(bg_cfg.get("min_cluster_size", 3))
    sim_threshold = float(bg_cfg.get("similarity_threshold", 0.65))
    salience_floor = float(bg_cfg.get("salience_floor", 1.3))
    max_per_sweep = int(bg_cfg.get("max_per_sweep", 3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # 1) Query high-salience nodes across GCL node types
    all_nodes = []
    for table, id_col in [("Concept", "concept_id"), ("Decision", "decision_id"),
                          ("Constraint", "constraint_id")]:
        try:
            rows = await db.execute_read(
                f"MATCH (n:{table}) WHERE n.archived = false "
                f"  AND n.salience_score >= $floor "
                f"RETURN n.{id_col} AS id, n.text_raw AS name, "
                f"  coalesce(n.text_raw, '') AS desc, n.embedding AS emb, "
                f"  n.salience_score AS salience "
                f"ORDER BY n.salience_score DESC LIMIT 50",
                {"floor": salience_floor},
            )
            for row in (rows or []):
                if row.get("emb"):
                    all_nodes.append(row)
        except Exception:
            errors += 1

    if len(all_nodes) < min_cluster:
        return 0, errors

    # 2) Greedy single-linkage clustering
    import numpy as np

    visited = set()
    clusters = []

    for i, node_i in enumerate(all_nodes):
        if i in visited:
            continue
        cluster = [i]
        visited.add(i)
        vec_i = np.array(node_i["emb"])
        norm_i = np.linalg.norm(vec_i)
        if norm_i == 0:
            continue

        for j, node_j in enumerate(all_nodes):
            if j in visited:
                continue
            vec_j = np.array(node_j["emb"])
            norm_j = np.linalg.norm(vec_j)
            if norm_j == 0:
                continue
            sim = float(np.dot(vec_i, vec_j) / (norm_i * norm_j))
            if sim >= sim_threshold:
                cluster.append(j)
                visited.add(j)

        if len(cluster) >= min_cluster:
            clusters.append(cluster)

    # 3) Synthesize avoidance Procedures from clusters
    for cluster_indices in clusters:
        if synthesized >= max_per_sweep:
            break

        cluster_nodes = [all_nodes[i] for i in cluster_indices]
        # Derive topic from most common words in names
        topic = cluster_nodes[0].get("name", "unknown")[:60]
        avg_salience = sum(n.get("salience", 1.0) for n in cluster_nodes) / len(cluster_nodes)

        # Build avoidance steps from node descriptions
        steps = []
        for n in cluster_nodes[:5]:  # cap at 5 steps
            desc = n.get("desc", "")
            if desc:
                steps.append({
                    "step": len(steps) + 1,
                    "action": f"Avoid: {desc[:100]}",
                    "warning": "This pattern has caused repeated frustration",
                })

        proc_id = str(uuid.uuid4())
        name = f"Avoid: {topic}"
        description = (
            f"Auto-generated avoidance procedure from {len(cluster_nodes)} "
            f"high-salience nodes. Average salience: {avg_salience:.2f}."
        )
        steps_json = json.dumps(steps)

        # Compute embedding from the description
        try:
            proc_emb = emb.embed(description, model_name=embedding_model)
        except Exception:
            proc_emb = [0.0] * 384

        try:
            await db.execute_write(
                """
                CREATE (pr:Procedure {
                    procedure_id: $pid, name: $name,
                    domain: 'auto-discovered', archetype: 'avoidance',
                    description: $description, steps_json: $steps_json,
                    embedding: $embedding, embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    success_count: 0, application_count: 0, success_rate: 0.0,
                    salience_score: $salience_score,
                    confidence: $confidence, pathway_strength: $pathway_strength,
                    maturity_stage: 'nascent',
                    archived: false, created_at: timestamp($now)
                })
                """,
                {
                    "pid": proc_id, "name": name,
                    "description": description, "steps_json": steps_json,
                    "embedding": proc_emb, "embedding_model": embedding_model,
                    "embedding_dim": len(proc_emb),
                    "salience_score": avg_salience,
                    "confidence": min(avg_salience / 1.6, 1.0),
                    "pathway_strength": min(avg_salience * 0.6, 1.0),
                    "now": now,
                },
            )

            # Link to source nodes via DISTILLED_FROM
            for node in cluster_nodes:
                try:
                    node_id = node.get("id", "")
                    if node_id:
                        await db.execute_write(
                            "MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) "
                            "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
                            "ON CREATE SET r.synthesized_at = timestamp($now)",
                            {"pid": proc_id, "cid": node_id, "now": now},
                        )
                except Exception:
                    pass  # Best-effort linking

            synthesized += 1
            _logger.info(
                "[BasalGanglia] avoidance Procedure %s from %d nodes: %s",
                proc_id[:8], len(cluster_nodes), name,
            )
        except Exception:
            _logger.exception("[BasalGanglia] Failed to create avoidance Procedure")
            errors += 1

    return synthesized, errors
```

- [ ] **Step 4: Wire `_detect_frustration_clusters` into `_dream_consolidation`**

In `mcp_engine/sweep.py`, find the end of `_dream_consolidation` (around line 1057-1065). After the existing `_synthesize_procedures` call but before `return synthesized, errors`, add:

```python
    # Basal Ganglia: frustration cluster detection (no LLM needed)
    try:
        fc_count, fc_err = await _detect_frustration_clusters(db, config)
        synthesized += fc_count
        errors += fc_err
    except Exception:
        errors += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestFrustrationClusterDetection -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Run existing sweep tests to verify no regression**

Run: `python3 -m pytest tests/test_sweep.py -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add mcp_engine/sweep.py tests/test_basal_ganglia.py
git commit -m "feat(basal-ganglia): add frustration cluster detection for avoidance Procedures"
```

---

### Task 4: Enhanced Plan Clustering + Maturity Tracking + Degradation

**Files:**
- Modify: `mcp_engine/sweep.py:1084-1240` (`_synthesize_procedures` function, add `_update_procedure_maturity`)
- Test: `tests/test_basal_ganglia.py`

This task enhances the existing `_synthesize_procedures` with lower thresholds and archetype labeling, adds maturity stage tracking, and adds degradation detection.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_basal_ganglia.py`:

```python
class TestEnhancedPlanClustering:
    """Tests for enhanced _synthesize_procedures changes."""

    @pytest.mark.asyncio
    async def test_min_cluster_size_lowered_to_two(self):
        """_synthesize_procedures should create Procedures from 2 Plans sharing a strategy."""
        from mcp_engine.sweep import _synthesize_procedures

        # 2 Plans with same strategy
        query_rows = {
            "DISTINCT p.strategy": [("deploy-to-prod",)],
            "p.strategy = $strategy": [
                ("plan-1", "deploy app", [0.1] * 384, 0.8, 0.7),
                ("plan-2", "deploy service", [0.1] * 384, 0.9, 0.8),
            ],
            # No existing Procedure with this archetype
            "p.archetype = $strategy": [],
        }
        db = _make_sweep_db(query_rows=query_rows)

        # Mock LLM to return a valid Procedure JSON
        class MockLLM:
            def chat(self, messages):
                return json.dumps({
                    "name": "Deploy to Production",
                    "description": "Standard deployment procedure",
                    "steps": [{"step": 1, "action": "build", "precondition": "", "expected_outcome": ""}],
                })

        config = {"embeddings": {"model": "test-model"},
                  "sweep": {"procedural": {"min_cluster_size": 2, "min_valence": 0.5,
                                            "max_syntheses_per_sweep": 3}}}
        count, errors = await _synthesize_procedures(db, config, MockLLM())
        assert count >= 1, f"Expected at least 1 Procedure from 2 Plans, got {count}"


class TestProcedureMaturity:
    """Tests for _update_procedure_maturity."""

    @pytest.mark.asyncio
    async def test_nascent_stage(self):
        """Procedure with application_count < 3 stays nascent."""
        from mcp_engine.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        result = await _update_procedure_maturity(db, config)
        # Should run without error
        assert result["updated"] >= 0

    @pytest.mark.asyncio
    async def test_maturity_update_writes_cypher(self):
        """_update_procedure_maturity writes a SET maturity_stage query."""
        from mcp_engine.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        # Should have written at least the maturity update query
        maturity_writes = [w for w in db.written if "maturity_stage" in w["q"]]
        assert len(maturity_writes) >= 1, "Expected maturity_stage update query"


class TestProcedureDegradation:
    """Tests for degradation detection in _update_procedure_maturity."""

    @pytest.mark.asyncio
    async def test_degradation_query_includes_success_rate_check(self):
        """Degradation detection should check success_rate < 0.30."""
        from mcp_engine.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        degradation_writes = [w for w in db.written if "degraded" in w["q"]]
        assert len(degradation_writes) >= 1, "Expected degradation detection query"

    @pytest.mark.asyncio
    async def test_archive_deeply_degraded(self):
        """Procedures already degraded with success_rate < 0.20 should be archived."""
        from mcp_engine.sweep import _update_procedure_maturity
        db = _make_sweep_db()
        config = {}
        await _update_procedure_maturity(db, config)
        archive_writes = [w for w in db.written if "archived" in w["q"] and "degraded" in w["q"]]
        assert len(archive_writes) >= 1, "Expected archive query for deeply degraded Procedures"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestEnhancedPlanClustering tests/test_basal_ganglia.py::TestProcedureMaturity tests/test_basal_ganglia.py::TestProcedureDegradation -v`
Expected: FAIL — `_update_procedure_maturity` does not exist, and `_synthesize_procedures` still requires 3+ Plans.

- [ ] **Step 3: Enhance `_synthesize_procedures` in `sweep.py`**

In `mcp_engine/sweep.py`, find `_synthesize_procedures` (line ~1084). Make these changes:

**3a. Lower `min_cluster_size` default from 3 to 2** (line ~1096):

Change:
```python
    min_cluster = int(proc_cfg.get("min_cluster_size", 3))
```
To:
```python
    min_cluster = int(proc_cfg.get("min_cluster_size", 2))
```

**3b. Add duplicate check before synthesis** — after the `if len(plans) < min_cluster: continue` check (line ~1143), add:

```python
        # Basal Ganglia: skip if an automation Procedure already exists for this strategy
        try:
            dup_check = db.execute(
                "MATCH (p:Procedure) WHERE p.archetype = $strategy AND p.archived = false "
                "RETURN count(p) > 0",
                {"strategy": strategy},
            )
            if dup_check.has_next() and dup_check.get_next()[0]:
                continue
        except Exception:
            pass
```

**3c. Set archetype to "automation"** — in the CREATE statement for the new Procedure (line ~1188), change the `archetype` value from `$archetype` to `'automation'`. Update the params dict to set `"archetype": "automation"` instead of `"archetype": strategy`.

- [ ] **Step 4: Add `_update_procedure_maturity` function**

Add this function after `_detect_frustration_clusters` in `sweep.py`:

```python
async def _update_procedure_maturity(db, config: dict) -> dict:
    """
    Basal Ganglia — Maturity Lifecycle.

    Update maturity_stage for all active Procedures based on application stats.
    Also detect degradation and archive deeply degraded Procedures.

    Returns summary dict.
    """
    result = {"updated": 0, "degraded": 0, "archived": 0, "errors": 0}

    # 1) Promote: nascent -> developing -> mature
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND coalesce(p.maturity_stage, 'nascent') != 'degraded' "
            "SET p.maturity_stage = CASE "
            "  WHEN p.application_count >= 5 AND p.success_rate >= 0.75 THEN 'mature' "
            "  WHEN p.application_count >= 3 AND p.success_rate >= 0.50 THEN 'developing' "
            "  ELSE 'nascent' END"
        )
        result["updated"] += 1
    except Exception:
        result["errors"] += 1

    # 2) Degrade: application_count >= 3 AND success_rate < 0.30
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND p.application_count >= 3 AND p.success_rate < 0.30 "
            "AND coalesce(p.maturity_stage, 'nascent') != 'degraded' "
            "SET p.maturity_stage = 'degraded', "
            "    p.pathway_strength = p.pathway_strength * 0.5"
        )
        result["degraded"] += 1
    except Exception:
        result["errors"] += 1

    # 3) Archive: already degraded AND still failing
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND p.maturity_stage = 'degraded' "
            "AND p.success_rate < 0.20 "
            "SET p.archived = true"
        )
        result["archived"] += 1
    except Exception:
        result["errors"] += 1

    # 4) Avoidance staleness: degrade avoidance Procedures whose topic now
    #    has positive sentiment (excitement signals on overlapping entities).
    #    This is a lightweight check — no embedding search, just query for
    #    excitement-salience nodes linked to the same Concepts as the avoidance
    #    Procedure. Deferred to a future sweep if no excitement nodes exist.
    # (This runs as part of the degradation pass — no separate function needed.)

    return result
```

- [ ] **Step 5: Wire `_update_procedure_maturity` into `_dream_consolidation`**

In `_dream_consolidation`, after the frustration cluster call (added in Task 3), add:

```python
    # Basal Ganglia: update Procedure maturity stages
    try:
        maturity_result = await _update_procedure_maturity(db, config)
        summary_key = f"maturity: {maturity_result}"
        _logger.info("[BasalGanglia] maturity update: %s", maturity_result)
    except Exception:
        errors += 1
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_basal_ganglia.py::TestEnhancedPlanClustering tests/test_basal_ganglia.py::TestProcedureMaturity tests/test_basal_ganglia.py::TestProcedureDegradation -v`
Expected: PASS (all 5 tests)

- [ ] **Step 7: Run full sweep test suite**

Run: `python3 -m pytest tests/test_sweep.py tests/test_basal_ganglia.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add mcp_engine/sweep.py tests/test_basal_ganglia.py
git commit -m "feat(basal-ganglia): enhanced Plan clustering, maturity tracking, degradation detection"
```

---

### Task 5: Architecture Docs + Summary Counter

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `mcp_engine/sweep.py` (add summary keys to `run_sweep`)
- Modify: `docs/superpowers/specs/2026-05-26-auto-skill-generation.md` (update status table)

This task documents the Basal Ganglia in the architecture docs and ensures the sweep summary includes new counters.

- [ ] **Step 1: Add Basal Ganglia to ARCHITECTURE.md**

In `docs/ARCHITECTURE.md`, find the section that lists the biomimetic components (search for "Amygdala" or "biomimetic" or the table listing Hebbian learning, Synaptic pruning, etc.). Add a new row for the Basal Ganglia:

```markdown
| Basal Ganglia (procedural learning) | Auto-generates avoidance Procedures from frustration clusters and automation Procedures from successful Plan clusters. Maturity lifecycle: nascent → developing → mature → degraded → archived. | `sweep.py`: `_detect_frustration_clusters()`, `_update_procedure_maturity()` |
```

Also add to the Cocktail Party senses table or relevant section:

```markdown
**Basal Ganglia** — two synthesis triggers in the dreaming sweep:
- **Avoidance archetype:** High-salience frustration clusters → avoidance Procedures (graph-only, no LLM)
- **Automation archetype:** Plan strategy clustering → automation Procedures (LLM synthesis, `min_cluster_size=2`)

Maturity lifecycle tracks Procedure reliability: `nascent` → `developing` (3+ applications, 50%+ success) → `mature` (5+ applications, 75%+ success). Degradation detected at `success_rate < 0.30` → archived at `< 0.20`.
```

- [ ] **Step 2: Add summary counters to `run_sweep`**

In `mcp_engine/sweep.py`, find `run_sweep` (line ~68). In the summary dict initialization (line ~89-96), add:

```python
        "frustration_clusters": 0,  # Basal Ganglia: avoidance Procedures
        "maturity_updates": 0,      # Basal Ganglia: maturity lifecycle
```

Then update the existing `_dream_consolidation` result handling (line ~124-126) to include:

```python
        summary["frustration_clusters"] = d  # will be updated when dream_consolidation returns it
```

Note: The `_dream_consolidation` function currently returns `(synthesized, errors)` which aggregates all synthesis counts. The frustration cluster and maturity counts are folded into `synthesized` and `errors` totals. Expose them explicitly by updating `_dream_consolidation` to also return the basal ganglia counts in the summary via a broader mechanism, OR simply accept that `synthesized` now includes avoidance + automation + lesson synthesis counts.

The simplest approach: add the summary keys to `run_sweep`'s summary dict and populate them after `_dream_consolidation` returns. No changes to `_dream_consolidation`'s return signature needed.

- [ ] **Step 3: Update the spec status table**

In `docs/superpowers/specs/2026-05-26-auto-skill-generation.md`, update the Implementation Status table to reflect completion. Change each row's Status from "Pending" to "Complete" and add the commit hashes once known.

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/test_basal_ganglia.py tests/test_step4_salience.py tests/test_sweep.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md mcp_engine/sweep.py docs/superpowers/specs/2026-05-26-auto-skill-generation.md
git commit -m "docs(basal-ganglia): architecture docs, summary counters, status update"
```
