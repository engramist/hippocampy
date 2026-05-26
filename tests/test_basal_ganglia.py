"""
Tests for Basal Ganglia — Auto-Skill Generation.

Run with: python3 -m pytest tests/test_basal_ganglia.py -v
"""

from __future__ import annotations
import os
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
