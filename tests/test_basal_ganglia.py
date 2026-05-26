"""
Tests for Basal Ganglia — Auto-Skill Generation.

Run with: python3 -m pytest tests/test_basal_ganglia.py -v
"""

from __future__ import annotations
import os
import pytest
import asyncio
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


class TestSchemaMigrations:
    """Verify salience_score and maturity_stage appear in the migration list."""

    def _read_schema_source(self):
        """Read schema.py source to check for migration entries."""
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "mcp_engine",
            "schema.py"
        )
        with open(schema_path, "r") as f:
            return f.read()

    def test_salience_score_migration_entries_exist(self):
        source = self._read_schema_source()
        assert "salience_score" in source, "salience_score migration missing from ensure_schema"

    def test_maturity_stage_migration_entry_exists(self):
        source = self._read_schema_source()
        assert "maturity_stage" in source, "maturity_stage migration missing from ensure_schema"

    def test_salience_score_on_all_gcl_node_types(self):
        source = self._read_schema_source()
        for table in ("Concept", "Decision", "Constraint"):
            assert f'("{table}",' in source and "salience_score" in source, (
                f"salience_score migration missing for {table}"
            )

    def test_maturity_stage_on_procedure_only(self):
        source = self._read_schema_source()
        # maturity_stage should appear for Procedure
        assert '"Procedure"' in source and "maturity_stage" in source
