"""
tests/patent_claims/conftest.py — Shared test infrastructure for Patent Claim Verification Suite (B380).

Loads the canonical fixture `tests/fixtures/patent_conformance_graph.jsonl` into an
in-memory / isolated temporary Kuzu instance with standard schema and centroids.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.export import _parse_column_types
from campy.brain.hippocampus.schema import NODE_TABLES, REL_TABLES, init_schema
from campy.brain.hippocampus.table_registry import pk_for
from campy.brain.temporal_lobe.loop.step2_gist import load_centroids

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "patent_conformance_graph.jsonl"
)
SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent / "campy" / "data" / "GistSeedExamples.md"
)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _parse_datetime(value: Any) -> Any:
    if isinstance(value, datetime) or value is None:
        return value
    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return value
    return value


def load_patent_conformance_graph(
    db: KuzuClient, fixture_path: Path | str = FIXTURE_PATH
) -> dict[str, int]:
    """Load canonical patent conformance graph fixture into the database."""
    path = Path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f"Patent conformance fixture not found at {path}")

    nodes_by_table: dict[str, list[dict[str, Any]]] = {}
    rels_by_table: dict[str, list[dict[str, Any]]] = {}

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            is_rel = (
                item.get("_type") == "rel"
                or "_from_table" in item
                or "_from_pk" in item
            )
            table = item.get("_table") or item.get("_label")
            if not table:
                continue

            if is_rel:
                rels_by_table.setdefault(table, []).append(item)
            else:
                nodes_by_table.setdefault(table, []).append(item)

    node_count = 0
    for table_name, rows in nodes_by_table.items():
        if not rows or table_name not in NODE_TABLES:
            continue
        valid_cols = set(_parse_column_types(NODE_TABLES[table_name]).keys())
        first = rows[0]
        prop_cols = [k for k in first.keys() if k in valid_cols]
        assignments = ", ".join(f"{col}: ${col}" for col in prop_cols)
        query = f"CREATE (n:{table_name} {{{assignments}}})"

        for r in rows:
            params = {}
            for col in prop_cols:
                val = r.get(col)
                if isinstance(val, str) and ("T" in val or "-" in val and len(val) >= 10):
                    val = _parse_datetime(val)
                params[col] = val
            db.execute(query, params)
            node_count += 1

    rel_count = 0
    # Map relation DDLs to rel_table names and their valid property columns
    rel_valid_cols: dict[str, set[str]] = {}
    for ddl in REL_TABLES:
        import re
        m = re.search(r"CREATE REL TABLE(?: IF NOT EXISTS)?\s+(\w+)", ddl, re.I)
        if m:
            rname = m.group(1)
            rel_valid_cols[rname] = set(_parse_column_types(ddl).keys())

    rels_by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for table, rows in rels_by_table.items():
        for r in rows:
            rels_by_group.setdefault((table, r["_from_table"], r["_to_table"]), []).append(r)

    for (rel_table, from_table, to_table), rows in rels_by_group.items():
        if not rows:
            continue
        first = rows[0]
        from_pk = pk_for(from_table)
        to_pk = pk_for(to_table)
        if not from_pk or not to_pk:
            raise ValueError(f"Missing PK for {from_table} or {to_table}")

        valid_props = rel_valid_cols.get(rel_table, set())
        rel_props = [
            k
            for k in first.keys()
            if k in valid_props
        ]
        rel_assignment = ", ".join(f"{key}: ${key}" for key in rel_props)
        if rel_assignment:
            query = (
                f"MATCH (a:{from_table} {{{from_pk}: $_from_pk}}), "
                f"(b:{to_table} {{{to_pk}: $_to_pk}}) "
                f"CREATE (a)-[r:{rel_table} {{{rel_assignment}}}]->(b)"
            )
        else:
            query = (
                f"MATCH (a:{from_table} {{{from_pk}: $_from_pk}}), "
                f"(b:{to_table} {{{to_pk}: $_to_pk}}) "
                f"CREATE (a)-[r:{rel_table}]->(b)"
            )

        for r in rows:
            params = {
                "_from_pk": r["_from_pk"],
                "_to_pk": r["_to_pk"],
            }
            for k in rel_props:
                val = r.get(k)
                if isinstance(val, str) and ("T" in val or "-" in val and len(val) >= 10):
                    val = _parse_datetime(val)
                params[k] = val
            db.execute(query, params)
            rel_count += 1

    return {"nodes_loaded": node_count, "rels_loaded": rel_count}


@pytest.fixture
def patent_config() -> dict[str, Any]:
    """Default runtime configuration for claim tests."""
    return {
        "embeddings": {
            "model": EMBEDDING_MODEL,
        },
        "nlp": {
            "spacy_model": "en_core_web_md",
        },
        "hebbian": {
            "co_occurrence_threshold": 10,
        },
        "context_window": {
            "default_token_limit": 128000,
            "bloat_warning_threshold": 0.75,
            "dedup_demotion_factor": 0.3,
            "chars_per_token": 3,
        },
    }


@pytest.fixture
def patent_db(tmp_path: Path) -> Iterable[KuzuClient]:
    """Provide a Kùzu client pre-seeded with the patent conformance graph."""
    db_path = tmp_path / "patent_claims.db"
    db = KuzuClient(str(db_path))
    try:
        init_schema(db, str(SEED_PATH), EMBEDDING_MODEL)
        load_patent_conformance_graph(db, FIXTURE_PATH)
        yield db
    finally:
        db.close()


@pytest.fixture
def gateway(patent_db: KuzuClient) -> GraphGateway:
    """Provide GraphGateway connected to patent_db."""
    return GraphGateway(patent_db, REGISTRY)


@pytest.fixture
def patent_centroids(patent_db: KuzuClient) -> dict[str, list[float]]:
    """Load centroids from the pre-initialized patent_db."""
    return load_centroids(patent_db)
