"""Regression: every sweep NamedQuery binds against a real Kùzu schema.

The bug this guards against: sweep queries referenced hard-coded property
names (n.constraint_id, n.pref_id, n.req_id) that did not match the
GlobalConstraint / GlobalPreference / Requirement primary-key columns
declared in schema.py (global_constraint_id, global_preference_id,
requirement_id). Kùzu 0.11.3 raises a Binder exception on such refs,
which _decay_and_archive's broad except-Exception swallowed as a plain
error count — hiding a total archive/resurrect failure for three tables.

Mock-based sweep tests never bind the raw Cypher, so a real-Kùzu bind
pass is the only thing that catches this class of typo.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

import pytest

try:
    import kuzu  # noqa: F401
    KUZU_AVAILABLE = True
except ModuleNotFoundError:
    KUZU_AVAILABLE = False

pytestmark = pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")


def _new_db_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"sweep_bind_{int(time.time()*1000)}.db")


def _drop_db(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _load_schema_and_queries():
    from campy.brain.hippocampus import schema
    from campy.brain.hippocampus.graph.queries.sweep import SWEEP_QUERIES
    return schema.NODE_TABLES, SWEEP_QUERIES


@pytest.mark.parametrize(
    "table", ["GlobalConstraint", "GlobalPreference", "Requirement", "Constraint"]
)
def test_sweep_queries_bind_against_real_schema(table: str) -> None:
    """Each per-entity sweep query must bind cleanly against the real DDL.

    Reproducer for the property-name mismatch: instantiate the table via
    its NODE_TABLES DDL, then execute every SWEEP_QUERIES entry whose name
    ends in the table's lowercased suffix. A Binder exception here means
    a query references a property the schema does not declare.
    """
    import kuzu as _kuzu
    node_tables, sweep_queries = _load_schema_and_queries()
    suffix = f"_{table.lower()}"
    matching = [q for q in sweep_queries if q.name.endswith(suffix)]
    assert matching, f"no sweep queries found for {table}"

    db_path = _new_db_path()
    try:
        db = _kuzu.Database(db_path)
        conn = _kuzu.Connection(db)
        conn.execute(f"CREATE NODE TABLE {table} ({node_tables[table]})")

        # Stub params for the small set of param keys sweep uses.
        stub_params = {
            "factor": 0.99,
            "ids": ["nonexistent-id"],
            "limit": 1,
            "strength": 0.5,
        }

        for q in matching:
            params = {k: stub_params[k] for k in q.params if k in stub_params}
            # Any unresolved property or unknown label will raise here at
            # bind time — even with zero matching rows.
            conn.execute(q.cypher, params) if params else conn.execute(q.cypher)
    finally:
        _drop_db(db_path)
