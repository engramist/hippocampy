"""Calibration regression tests for KuzuClient.vector_search.

Guards against drift between HNSW distance metric and the similarity
scores consumed by Step 5 dedup, quest routing, and analogical search.
"""

from __future__ import annotations

import math
import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


@pytest.fixture()
def calib_db():
    tmp = tempfile.mkdtemp(prefix="kuzu_calib_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(
        "CREATE NODE TABLE CalibNode("  # noqa: ISC003
        "id STRING, embedding FLOAT[4], PRIMARY KEY (id))"
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _insert(db: KuzuClient, node_id: str, vec: list[float]) -> None:
    db.execute(
        "CREATE (n:CalibNode {id: $id, embedding: $vec})",
        {"id": node_id, "vec": vec},
    )


def _raw_distances(db: KuzuClient) -> dict[str, float]:
    result = db.execute(
        "CALL QUERY_VECTOR_INDEX('CalibNode', 'calib_idx', $embedding, 3) "
        "YIELD node, distance RETURN node, distance",
        {"embedding": [1.0, 0.0, 0.0, 0.0]},
    )
    rows: dict[str, float] = {}
    while result.has_next():
        node, distance = result.get_next()
        rows[node["id"]] = float(distance)
    return rows


def test_vector_index_uses_cosine_distance(calib_db: KuzuClient) -> None:
    db = calib_db
    _insert(db, "identical", [1.0, 0.0, 0.0, 0.0])
    _insert(db, "deg45", [math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0])
    _insert(db, "orthogonal", [0.0, 1.0, 0.0, 0.0])
    db.create_vector_index("CalibNode", "embedding", "calib_idx")

    distances = _raw_distances(db)

    assert abs(distances["identical"] - 0.0) < 0.01
    assert abs(distances["deg45"] - (1.0 - math.sqrt(0.5))) < 0.02
    assert abs(distances["orthogonal"] - 1.0) < 0.02


def test_vector_search_returns_cosine(calib_db: KuzuClient) -> None:
    db = calib_db
    _insert(db, "identical", [1.0, 0.0, 0.0, 0.0])
    _insert(db, "deg45", [math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0])
    _insert(db, "orthogonal", [0.0, 1.0, 0.0, 0.0])
    db.create_vector_index("CalibNode", "embedding", "calib_idx")

    rows = db.vector_search("CalibNode", "calib_idx", [1.0, 0.0, 0.0, 0.0], 3)
    scores = {row["node"]["id"]: row["score"] for row in rows}

    assert abs(scores["identical"] - 1.0) < 0.01
    assert abs(scores["deg45"] - 0.7071) < 0.02
    assert abs(scores["orthogonal"] - 0.0) < 0.02