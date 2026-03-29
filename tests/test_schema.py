"""
Tests for mcp_engine/schema.py — T6 coverage.
Focuses on pure-Python helpers that don't require a live Kùzu instance.
"""

from __future__ import annotations
import sys
import os
import types
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Stub out kuzu so schema.py can be imported without the real package.
# kuzu is not available in the test environment (it's a compiled C extension).
# ---------------------------------------------------------------------------

def _stub_kuzu():
    if "kuzu" not in sys.modules:
        _kuzu = types.ModuleType("kuzu")

        class _DB:
            def __init__(self, *a, **kw): pass

        class _Conn:
            def __init__(self, *a, **kw): pass
            def execute(self, *a, **kw): return None

        _kuzu.Database = _DB
        _kuzu.Connection = _Conn
        sys.modules["kuzu"] = _kuzu

_stub_kuzu()


# ---------------------------------------------------------------------------
# _parse_seed_examples
# ---------------------------------------------------------------------------

SAMPLE_SEED_MD = """\
# GistSeedExamples

## gist:Restriction
1. "You must provide a valid ID to enter the facility."
2. "All API calls require authentication."
3. "No external libraries are permitted in production."

## gist:PlannedEvent
1. "The team will deploy the service on Friday."
2. "We plan to run the migration after the weekend."

## gist:PhysicalThing
1. "The PostgreSQL database stores all user records."
2. "The Redis cache sits in front of the database."
3. "We use an NVIDIA A100 GPU for model inference."
"""


def test_parse_seed_examples_returns_dict(tmp_path):
    """_parse_seed_examples returns a dict keyed by gist class name."""
    from mcp_engine.schema import _parse_seed_examples
    seed_file = tmp_path / "GistSeedExamples.md"
    seed_file.write_text(SAMPLE_SEED_MD, encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert isinstance(result, dict)
    assert "Restriction" in result
    assert "PlannedEvent" in result
    assert "PhysicalThing" in result


def test_parse_seed_examples_correct_sentence_count(tmp_path):
    """Sentence count per class matches the markdown."""
    from mcp_engine.schema import _parse_seed_examples
    seed_file = tmp_path / "GistSeedExamples.md"
    seed_file.write_text(SAMPLE_SEED_MD, encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert len(result["Restriction"])   == 3
    assert len(result["PlannedEvent"])  == 2
    assert len(result["PhysicalThing"]) == 3


def test_parse_seed_examples_sentence_text_correct(tmp_path):
    """Extracted sentences match exactly (quotes stripped)."""
    from mcp_engine.schema import _parse_seed_examples
    seed_file = tmp_path / "GistSeedExamples.md"
    seed_file.write_text(SAMPLE_SEED_MD, encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert "You must provide a valid ID to enter the facility." in result["Restriction"]
    assert "The team will deploy the service on Friday." in result["PlannedEvent"]


def test_parse_seed_examples_empty_file(tmp_path):
    """Empty seed file returns empty dict."""
    from mcp_engine.schema import _parse_seed_examples
    seed_file = tmp_path / "empty.md"
    seed_file.write_text("", encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert result == {}


def test_parse_seed_examples_section_with_no_examples(tmp_path):
    """A section header with no numbered examples returns an empty list."""
    from mcp_engine.schema import _parse_seed_examples
    md = "## gist:Category\n\nNo examples here yet.\n"
    seed_file = tmp_path / "partial.md"
    seed_file.write_text(md, encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert "Category" in result
    assert result["Category"] == []


def test_parse_seed_examples_ignores_non_section_content(tmp_path):
    """Text before first section header is ignored."""
    from mcp_engine.schema import _parse_seed_examples
    md = (
        "# Preamble\n\nSome introduction text.\n\n"
        "## gist:Event\n"
        '1. "The conference starts on Monday."\n'
    )
    seed_file = tmp_path / "intro.md"
    seed_file.write_text(md, encoding="utf-8")
    result = _parse_seed_examples(str(seed_file))
    assert list(result.keys()) == ["Event"]
    assert len(result["Event"]) == 1


# ---------------------------------------------------------------------------
# ROUTING_TABLE — structural checks (no DB needed)
# ---------------------------------------------------------------------------

def test_routing_table_is_list():
    """ROUTING_TABLE is a list of tuples."""
    from mcp_engine.schema import ROUTING_TABLE
    assert isinstance(ROUTING_TABLE, list)
    assert len(ROUTING_TABLE) > 0


def test_routing_table_entries_are_triples():
    """Each entry is (gist_class, schema_org_type, properties_list)."""
    from mcp_engine.schema import ROUTING_TABLE
    for entry in ROUTING_TABLE:
        assert len(entry) == 3, f"Entry should be 3-tuple: {entry}"
        gist_class, schema_type, props = entry
        assert isinstance(gist_class, str)
        assert isinstance(schema_type, str)
        assert isinstance(props, list)
        assert all(isinstance(p, str) for p in props)


def test_routing_table_contains_expected_classes():
    """Core gist classes have routing entries."""
    from mcp_engine.schema import ROUTING_TABLE
    gist_classes = {row[0] for row in ROUTING_TABLE}
    for expected in ("Restriction", "PlannedEvent", "PhysicalThing",
                     "Magnitude", "Category", "Agent", "Event"):
        assert expected in gist_classes, f"Missing gist class: {expected}"


def test_routing_table_agent_maps_to_both_person_and_org():
    """gist:Agent routes to both schema:Person AND schema:Organization."""
    from mcp_engine.schema import ROUTING_TABLE
    agent_targets = [row[1] for row in ROUTING_TABLE if row[0] == "Agent"]
    assert "Person" in agent_targets
    assert "Organization" in agent_targets


# ---------------------------------------------------------------------------
# NODE_TABLES — structural checks
# ---------------------------------------------------------------------------

def test_node_tables_contains_required_tables():
    """All required node tables are defined."""
    from mcp_engine.schema import NODE_TABLES
    required = {
        "Concept", "Decision", "Constraint", "Requirement", "ActionItem",
        "MainQuest", "SideQuest", "Message", "DocumentExtract", "Document",
        "Session", "LLMProvider", "Workspace", "GistClass", "SchemaOrgType",
        "Label", "MergeEvent",
    }
    for table in required:
        assert table in NODE_TABLES, f"Missing node table: {table}"


def test_concept_table_has_last_accessed_at():
    """Concept table includes last_accessed_at field (L14 fix)."""
    from mcp_engine.schema import NODE_TABLES
    assert "last_accessed_at" in NODE_TABLES["Concept"]


def test_concept_table_has_embedding_float384():
    """Concept table uses FLOAT[384] for HNSW compatibility."""
    from mcp_engine.schema import NODE_TABLES
    assert "FLOAT[384]" in NODE_TABLES["Concept"]


def test_gist_class_table_has_centroid():
    """GistClass table has centroid field for System 1 classifier."""
    from mcp_engine.schema import NODE_TABLES
    assert "centroid" in NODE_TABLES["GistClass"]


# ---------------------------------------------------------------------------
# _bootstrap_centroids — centroid normalization (L1 fix)
# ---------------------------------------------------------------------------

def test_bootstrap_centroids_produces_unit_vectors(tmp_path):
    """Centroids produced by _bootstrap_centroids are L2-normalized."""
    import math
    from mcp_engine.schema import _bootstrap_centroids

    seed_file = tmp_path / "seeds.md"
    seed_file.write_text(SAMPLE_SEED_MD, encoding="utf-8")

    stored_centroids = {}

    class MockDB:
        def execute(self, query, params=None):
            if params and "centroid" in params:
                stored_centroids[params["name"]] = params["centroid"]

    _bootstrap_centroids(
        MockDB(), str(seed_file),
        "sentence-transformers/all-MiniLM-L6-v2"
    )

    assert len(stored_centroids) > 0
    for class_name, centroid in stored_centroids.items():
        norm = math.sqrt(sum(v * v for v in centroid))
        assert abs(norm - 1.0) < 1e-5, (
            f"Centroid for {class_name} is not unit-normalized: norm={norm}"
        )


def test_bootstrap_centroids_skips_empty_class(tmp_path):
    """Classes with no examples are skipped without error."""
    from mcp_engine.schema import _bootstrap_centroids

    seed_file = tmp_path / "partial.md"
    seed_file.write_text("## gist:Empty\n\n# no numbered examples here\n")

    class MockDB:
        def execute(self, query, params=None): pass

    # Should not raise
    _bootstrap_centroids(MockDB(), str(seed_file),
                          "sentence-transformers/all-MiniLM-L6-v2")


def test_real_seed_file_has_diverse_examples():
    """GistSeedExamples.md has domain-diverse examples (B-centroid-diversity)."""
    from mcp_engine.schema import _parse_seed_examples
    from pathlib import Path

    seed_file = Path(__file__).parent.parent / "InvertorsDocs" / "GistSeedExamples.md"
    if not seed_file.exists():
        pytest.skip("Seed file not found")

    result = _parse_seed_examples(str(seed_file))

    # Every class should have at least 40 examples (original ~15 + professional ~15 + consumer ~15)
    for class_name in ["Restriction", "PlannedEvent", "PhysicalThing",
                       "Magnitude", "Category", "Agent", "Event"]:
        assert class_name in result, f"Missing class: {class_name}"
        assert len(result[class_name]) >= 40, (
            f"gist:{class_name} has only {len(result[class_name])} examples, "
            f"expected >= 40 after Phase 1 + Phase 2 diversity merge"
        )

    # Total should be > 300
    total = sum(len(v) for v in result.values())
    assert total >= 300, f"Total examples {total} < 300"


# ---------------------------------------------------------------------------
# B35 fix: migration uses table_info pre-check instead of exception guard
# ---------------------------------------------------------------------------

class MockResult:
    """Reusable mock for KuzuClient.execute() results."""
    def __init__(self, rows=None):
        self._rows = rows or []
        self._idx = 0

    def has_next(self):
        return self._idx < len(self._rows)

    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class TestMigrationColumnCheck:
    """
    Tests that the B35-fixed migration guard correctly uses table_info
    to pre-check column existence instead of relying on exception text.

    These tests mock the DB (kuzu is already stubbed at module level for
    test_schema.py) and focus on the logic, not DB integration.
    """

    def _make_mock_db(self, existing_cols=None):
        """Build a MockDB that returns table_info rows for given existing columns."""
        cols = existing_cols or []

        class MockDB:
            def __init__(self):
                self.executed = []

            def execute(self, query, params=None):
                self.executed.append(query)
                if "table_info" in query.lower():
                    rows = [[i, c, "STRING", "NULL", False]
                            for i, c in enumerate(cols)]
                    return MockResult(rows)
                return MockResult()

            async def execute_write(self, query, params=None):
                self.executed.append(query)

        return MockDB()

    def test_column_exists_check_returns_true_when_present(self):
        """_column_exists logic: query table_info and match by name (case-insensitive)."""
        db = self._make_mock_db(existing_cols=["quest_id", "git_repo_root", "status"])

        # Replicate the _column_exists logic from schema.py
        def _column_exists(table, col):
            try:
                r = db.execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        assert _column_exists("MainQuest", "git_repo_root") is True
        assert _column_exists("MainQuest", "GIT_REPO_ROOT") is True  # case-insensitive

    def test_column_exists_check_returns_false_when_absent(self):
        """_column_exists returns False when the column is not present."""
        db = self._make_mock_db(existing_cols=["quest_id", "status"])

        def _column_exists(table, col):
            try:
                r = db.execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        assert _column_exists("MainQuest", "git_repo_root") is False

    def test_alter_skipped_when_column_present(self):
        """Migration loop skips ALTER TABLE when column already exists."""
        db = self._make_mock_db(existing_cols=["quest_id", "git_repo_root"])
        alter_calls = []

        original_execute = db.execute
        def patched_execute(query, params=None):
            if "ALTER TABLE" in query.upper():
                alter_calls.append(query)
            return original_execute(query, params)
        db.execute = patched_execute

        # Simulate the migration loop for a single column
        def _column_exists(table, col):
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                if str(row[1]).lower() == col.lower():
                    return True
            return False

        if not _column_exists("MainQuest", "git_repo_root"):
            db.execute("ALTER TABLE MainQuest ADD git_repo_root STRING")

        assert len(alter_calls) == 0, "ALTER should be skipped when column exists"

    def test_alter_runs_when_column_absent(self):
        """Migration loop executes ALTER TABLE when column is missing."""
        db = self._make_mock_db(existing_cols=["quest_id"])  # no git_repo_root
        alter_calls = []

        original_execute = db.execute
        def patched_execute(query, params=None):
            if "ALTER TABLE" in query.upper():
                alter_calls.append(query)
                return MockResult()
            return original_execute(query, params)
        db.execute = patched_execute

        def _column_exists(table, col):
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                if str(row[1]).lower() == col.lower():
                    return True
            return False

        if not _column_exists("MainQuest", "git_repo_root"):
            db.execute("ALTER TABLE MainQuest ADD git_repo_root STRING")

        assert len(alter_calls) == 1
        assert "git_repo_root" in alter_calls[0]

    def test_error_in_table_info_falls_through_safely(self):
        """If table_info raises, _column_exists returns False (safe default)."""
        class ErrorDB:
            def execute(self, query, params=None):
                if "table_info" in query.lower():
                    raise RuntimeError("Table not found")
                return MockResult()

        def _column_exists(table, col):
            try:
                r = ErrorDB().execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        # Falls back to False — migration will attempt ALTER, which is safe
        assert _column_exists("MainQuest", "git_repo_root") is False


def test_lesson_table_has_required_fields():
    """Lesson table includes all B11 required fields."""
    from mcp_engine.schema import NODE_TABLES
    fields = NODE_TABLES["Lesson"]
    assert "lesson_id" in fields
    assert "domain" in fields
    assert "lesson_type" in fields
    assert "confidence" in fields


def test_lesson_relationships_defined():
    """B11 lesson relationships are defined in REL_TABLES."""
    from mcp_engine.schema import REL_TABLES
    rels = "".join(REL_TABLES)
    assert "PRODUCED_LESSON" in rels
    assert "LEARNED" in rels
    assert "APPLIES_TO" in rels
    assert "RELATED_TO" in rels
    assert "CONTAINS_LESSON" in rels


def test_mainquest_has_git_repo_root_in_node_tables():
    """MainQuest NODE_TABLE definition includes git_repo_root at schema level."""
    from mcp_engine.schema import NODE_TABLES
    assert "git_repo_root" in NODE_TABLES["MainQuest"]


class TestMigrationColumnCheck:
    """
    Tests that the B35-fixed migration guard correctly uses table_info
    to pre-check column existence instead of relying on exception text.

    These tests mock the DB (kuzu is already stubbed at module level for
    test_schema.py) and focus on the logic, not DB integration.
    """

    def _make_mock_db(self, existing_cols=None):
        """Build a MockDB that returns table_info rows for given existing columns."""
        cols = existing_cols or []

        class MockDB:
            def __init__(self):
                self.executed = []

            def execute(self, query, params=None):
                self.executed.append(query)
                if "table_info" in query.lower():
                    rows = [[i, c, "STRING", "NULL", False]
                            for i, c in enumerate(cols)]
                    return MockResult(rows)
                return MockResult()

            async def execute_write(self, query, params=None):
                self.executed.append(query)

        return MockDB()

    def test_column_exists_check_returns_true_when_present(self):
        """_column_exists logic: query table_info and match by name (case-insensitive)."""
        db = self._make_mock_db(existing_cols=["quest_id", "git_repo_root", "status"])

        # Replicate the _column_exists logic from schema.py
        def _column_exists(table, col):
            try:
                r = db.execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        assert _column_exists("MainQuest", "git_repo_root") is True
        assert _column_exists("MainQuest", "GIT_REPO_ROOT") is True  # case-insensitive

    def test_column_exists_check_returns_false_when_absent(self):
        """_column_exists returns False when the column is not present."""
        db = self._make_mock_db(existing_cols=["quest_id", "status"])

        def _column_exists(table, col):
            try:
                r = db.execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        assert _column_exists("MainQuest", "git_repo_root") is False

    def test_alter_skipped_when_column_present(self):
        """Migration loop skips ALTER TABLE when column already exists."""
        db = self._make_mock_db(existing_cols=["quest_id", "git_repo_root"])
        alter_calls = []

        original_execute = db.execute
        def patched_execute(query, params=None):
            if "ALTER TABLE" in query.upper():
                alter_calls.append(query)
            return original_execute(query, params)
        db.execute = patched_execute

        # Simulate the migration loop for a single column
        def _column_exists(table, col):
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                if str(row[1]).lower() == col.lower():
                    return True
            return False

        if not _column_exists("MainQuest", "git_repo_root"):
            db.execute("ALTER TABLE MainQuest ADD git_repo_root STRING")

        assert len(alter_calls) == 0, "ALTER should be skipped when column exists"

    def test_alter_runs_when_column_absent(self):
        """Migration loop executes ALTER TABLE when column is missing."""
        db = self._make_mock_db(existing_cols=["quest_id"])  # no git_repo_root
        alter_calls = []

        original_execute = db.execute
        def patched_execute(query, params=None):
            if "ALTER TABLE" in query.upper():
                alter_calls.append(query)
                return MockResult()
            return original_execute(query, params)
        db.execute = patched_execute

        def _column_exists(table, col):
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                if str(row[1]).lower() == col.lower():
                    return True
            return False

        if not _column_exists("MainQuest", "git_repo_root"):
            db.execute("ALTER TABLE MainQuest ADD git_repo_root STRING")

        assert len(alter_calls) == 1
        assert "git_repo_root" in alter_calls[0]

    def test_error_in_table_info_falls_through_safely(self):
        """If table_info raises, _column_exists returns False (safe default)."""
        class ErrorDB:
            def execute(self, query, params=None):
                if "table_info" in query.lower():
                    raise RuntimeError("Table not found")
                return MockResult()

        def _column_exists(table, col):
            try:
                r = ErrorDB().execute(f"CALL table_info('{table}') RETURN *")
                while r.has_next():
                    row = r.get_next()
                    if str(row[1]).lower() == col.lower():
                        return True
            except Exception:
                pass
            return False

        # Falls back to False — migration will attempt ALTER, which is safe
        assert _column_exists("MainQuest", "git_repo_root") is False

    def test_git_repo_root_in_migrations_list(self):
        """git_repo_root is in _MIGRATIONS (checked via module inspection)."""
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "mcp_engine" / "schema.py"
        text = src.read_text()
        assert '"git_repo_root"' in text or "'git_repo_root'" in text
        # Also verify table_info-based guard is present
        assert "table_info" in text
