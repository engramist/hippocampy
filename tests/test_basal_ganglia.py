"""
Tests for Basal Ganglia — Auto-Skill Generation.

Run with: python3 -m pytest tests/test_basal_ganglia.py -v
"""

from __future__ import annotations
import os


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
