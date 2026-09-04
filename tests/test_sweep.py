"""
Tests for mcp_engine/sweep.py — Background Sweep (H1 + H2 fixes).

Run with: python3 -m pytest tests/test_sweep.py -v
"""

from __future__ import annotations
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers / mock builders
# ---------------------------------------------------------------------------

def _make_db(rows_by_query=None, vector_results=None):
    """Build a mock DB that returns controlled data."""
    rows_by_query  = rows_by_query or {}
    vector_results = vector_results or {}

    class MockResult:
        def __init__(self, rows):
            self._rows = list(rows)
            self._idx  = 0
        def has_next(self): return self._idx < len(self._rows)
        def get_next(self): row = self._rows[self._idx]; self._idx += 1; return row

    class MockDB:
        def __init__(self):
            self.written = []

        def execute(self, q, p=None):
            for pattern, rows in rows_by_query.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])

        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})

        def vector_search(self, table_name, index_name, vec, limit):
            return vector_results.get(index_name, [])

    return MockDB()


def _make_llm(response_json):
    """Build a mock LLM client that returns a fixed JSON string."""
    class MockLLM:
        def chat(self, messages):
            return json.dumps(response_json)
    return MockLLM()


def _make_bad_llm():
    """LLM that returns non-JSON."""
    class BadLLM:
        def chat(self, messages):
            return "I cannot determine that"
    return BadLLM()


# ---------------------------------------------------------------------------
# run_sweep — integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_sweep_returns_summary_keys():
    from campy.brain.brainstem.sweep import run_sweep
    db = _make_db()
    config = {"pruning": {"sweep_interval_seconds": 300, "archive_threshold": 0.10,
                          "resurrection_threshold": 0.85, "decay_rate": {}}}
    result = await run_sweep(db, config, llm_client=None)
    assert "decayed" in result
    assert "archived" in result
    assert "resurrected" in result
    assert "promoted" in result
    assert "errors" in result
    assert "sweep_at" in result


@pytest.mark.asyncio
async def test_run_sweep_skips_hebbian_when_no_llm():
    from campy.brain.brainstem.sweep import run_sweep
    db = _make_db()
    config = {"pruning": {"sweep_interval_seconds": 300, "archive_threshold": 0.10,
                          "resurrection_threshold": 0.85, "decay_rate": {}},
              "hebbian": {"co_occurrence_threshold": 10}}
    result = await run_sweep(db, config, llm_client=None)
    assert result["promoted"] == 0


@pytest.mark.asyncio
async def test_run_sweep_empty_db_no_errors():
    from campy.brain.brainstem.sweep import run_sweep
    db = _make_db()
    config = {"pruning": {"sweep_interval_seconds": 300, "archive_threshold": 0.10,
                          "resurrection_threshold": 0.85, "decay_rate": {}}}
    result = await run_sweep(db, config, llm_client=None)
    assert result["errors"] == 0


# ---------------------------------------------------------------------------
# _decay_and_archive
# ---------------------------------------------------------------------------

# B282 batch-sweep-writes replaced the old two-query pattern (a
# "pathway_strength < $threshold" scan + a separate "count(n)") with one
# combined read: "MATCH (n:{table}) WHERE n.archived = false RETURN
# n.{pk_col}, n.pathway_strength" (campy/brain/brainstem/sweep.py:602-605).
# _decay_and_archive counts `decayed` by iterating that result set and
# derives archive candidates from each row's pathway_strength value
# in-process — it never issues a separate threshold-filter or count(n)
# query. The mocks below were never updated for that refactor: their
# registered patterns don't match the real query string, MockDB.execute
# falls through to an empty result every time, and decayed/archived always
# came out 0 regardless of what the test configured. "RETURN n." is present
# in the real read query (and absent from the atomic decay SET write), so
# it's a stable, unambiguous mock key.

@pytest.mark.asyncio
async def test_decay_updates_strength():
    from campy.brain.brainstem.sweep import _decay_and_archive
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", 0.9]],  # 1 active node, strength above archive_threshold=0.10
    })
    d, a, e = await _decay_and_archive(db, {"decision": 0.995}, 300/86400, 0.10)
    assert d >= 1  # at least one node was decayed
    assert a == 0
    assert e == 0
    # Verify atomic bulk decay write was issued
    assert any("pathway_strength" in w["q"] and "* $factor" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_decay_archives_node_below_threshold():
    from campy.brain.brainstem.sweep import _decay_and_archive
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", 0.05]],  # d1 below archive_threshold=0.10
    })
    d, a, e = await _decay_and_archive(db, {"decision": 0.5}, 1.0, 0.10)
    assert a >= 1
    assert any("archived = true" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_decay_uses_default_rate_when_missing():
    from campy.brain.brainstem.sweep import _decay_and_archive
    # No decay rate for "message" — should use default 0.99 and not crash
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", 0.9]],
    })
    d, a, e = await _decay_and_archive(db, {}, 300/86400, 0.10)
    assert e == 0  # no errors with missing rate


@pytest.mark.asyncio
async def test_decay_handles_zero_strength_node():
    from campy.brain.brainstem.sweep import _decay_and_archive
    # After atomic decay of 0.0 * factor = 0.0, node should be archived
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", 0.0]],
    })
    d, a, e = await _decay_and_archive(db, {"decision": 0.995}, 300/86400, 0.10)
    assert a >= 1
    assert e == 0


@pytest.mark.asyncio
async def test_decay_handles_none_strength_node():
    from campy.brain.brainstem.sweep import _decay_and_archive
    # A None pathway_strength must not crash the `< archive_threshold`
    # comparison and must not be archived (`row[1] is not None and ...`
    # guard in _decay_and_archive).
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", None]],
    })
    d, a, e = await _decay_and_archive(db, {"decision": 0.995}, 300/86400, 0.10)
    assert a == 0
    assert e == 0


@pytest.mark.asyncio
async def test_decay_node_above_threshold_not_archived():
    from campy.brain.brainstem.sweep import _decay_and_archive
    # High-strength node stays above threshold after small decay
    db = _make_db(rows_by_query={
        "RETURN n.": [["d1", 0.9]],  # above archive_threshold=0.10
    })
    d, a, e = await _decay_and_archive(db, {"decision": 0.995}, 300/86400, 0.10)
    assert a == 0
    assert d >= 1


# ---------------------------------------------------------------------------
# _resurrect_archived
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resurrect_un_archives_similar_node():
    from campy.brain.brainstem.sweep import _resurrect_archived
    embedding = [0.1] * 384
    active_node = {
        "decision_id": "d_active",
        "archived": False,
        "pathway_strength": 0.8,
    }
    db = _make_db(
        rows_by_query={"Decision": [["d_archived", embedding]]},
        vector_results={"decision_emb_idx": [{"node": active_node, "score": 0.92}]},
    )
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 1
    assert e == 0
    assert any("archived = false" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_resurrect_skips_self_match():
    from campy.brain.brainstem.sweep import _resurrect_archived
    embedding = [0.1] * 384
    # Vector search returns the same node (self-match, score=1.0)
    self_node = {"decision_id": "d_archived", "archived": True}
    db = _make_db(
        rows_by_query={"Decision": [["d_archived", embedding]]},
        vector_results={"decision_emb_idx": [{"node": self_node, "score": 1.0}]},
    )
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 0


@pytest.mark.asyncio
async def test_resurrect_skips_archived_neighbors():
    from campy.brain.brainstem.sweep import _resurrect_archived
    embedding = [0.1] * 384
    archived_neighbor = {"decision_id": "d_neighbor", "archived": True}
    db = _make_db(
        rows_by_query={"Decision": [["d_archived", embedding]]},
        vector_results={"decision_emb_idx": [{"node": archived_neighbor, "score": 0.95}]},
    )
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 0


@pytest.mark.asyncio
async def test_resurrect_below_threshold_not_resurrected():
    from campy.brain.brainstem.sweep import _resurrect_archived
    embedding = [0.1] * 384
    active_node = {"decision_id": "d_active", "archived": False}
    db = _make_db(
        rows_by_query={"Decision": [["d_archived", embedding]]},
        vector_results={"decision_emb_idx": [{"node": active_node, "score": 0.70}]},
    )
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 0


@pytest.mark.asyncio
async def test_resurrect_resets_strength_to_threshold():
    from campy.brain.brainstem.sweep import _resurrect_archived
    embedding = [0.1] * 384
    active_node = {"decision_id": "d_active", "archived": False}
    db = _make_db(
        rows_by_query={"Decision": [["d_archived", embedding]]},
        vector_results={"decision_emb_idx": [{"node": active_node, "score": 0.90}]},
    )
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 1
    write = next(w for w in db.written if "archived = false" in w["q"])
    assert write["p"]["strength"] == 0.85


@pytest.mark.asyncio
async def test_resurrect_no_archived_nodes_no_error():
    from campy.brain.brainstem.sweep import _resurrect_archived
    db = _make_db()  # empty DB
    r, e = await _resurrect_archived(db, resurrection_threshold=0.85)
    assert r == 0
    assert e == 0


@pytest.mark.asyncio
async def test_resurrect_applies_candidate_limit_to_the_query():
    """B373: the per-table scan is capped -- previously unbounded, which on
    a table with tens of thousands of archived rows meant that many
    synchronous vector_search calls in one sweep."""
    from campy.brain.brainstem.sweep import _resurrect_archived

    seen_queries = []

    seen_params = []

    class LimitCheckingDB:
        def execute(self, q, p=None):
            seen_queries.append(q)
            seen_params.append(p)
            class Empty:
                def has_next(self): return False
            return Empty()
        async def execute_write(self, q, p=None):
            pass
        def vector_search(self, *a, **kw):
            return []

    await _resurrect_archived(LimitCheckingDB(), resurrection_threshold=0.85, candidate_limit=7)
    assert any("LIMIT 7" in q or ("LIMIT $limit" in q and p and p.get("limit") == 7) for q, p in zip(seen_queries, seen_params))


@pytest.mark.asyncio
async def test_resurrect_does_not_block_the_event_loop():
    """B373: this is the actual incident's regression test. Before this
    fix, _resurrect_archived's per-node vector_search loop ran directly on
    the calling (event loop) thread -- a slow scan meant nothing else in
    the daemon's asyncio loop could run for the entire duration. Confirmed
    live via sample(1) during a real occurrence: the main thread was
    synchronously inside a single Kuzu call the whole time, and an
    independent 15s-interval task (the periodic checkpoint) went
    completely silent for 80+ seconds. Simulates the same shape here: a
    slow synchronous scan running concurrently with an independent
    "heartbeat" task, and asserts the heartbeat kept ticking throughout --
    proof the scan is off the event loop thread, not just "usually fast
    enough in practice."
    """
    import asyncio as _asyncio
    from campy.brain.brainstem.sweep import _resurrect_archived

    class SlowDB:
        def execute(self, q, p=None):
            import time
            time.sleep(0.05)  # simulates the real Kuzu scan cost
            class OneRow:
                def __init__(self):
                    self._done = False
                def has_next(self):
                    if self._done:
                        return False
                    self._done = True
                    return True
                def get_next(self):
                    return ["id1", [0.1] * 384]
            return OneRow()
        async def execute_write(self, q, p=None):
            pass
        def vector_search(self, *a, **kw):
            import time
            time.sleep(0.05)
            return []

    heartbeat_ticks = []

    async def heartbeat():
        while True:
            heartbeat_ticks.append(True)
            await _asyncio.sleep(0.01)

    hb_task = _asyncio.create_task(heartbeat())
    try:
        await _resurrect_archived(SlowDB(), resurrection_threshold=0.85)
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except _asyncio.CancelledError:
            pass

    # SWEEP_TABLES has 9 tables; SlowDB blocks ~0.1s (execute + one
    # vector_search) per table, so the whole call takes ~0.9s. If the
    # event loop were blocked the whole time, the heartbeat (10ms period)
    # would tick only once or twice; if it's genuinely concurrent, it
    # should tick dozens of times.
    assert len(heartbeat_ticks) >= 20, (
        f"only {len(heartbeat_ticks)} heartbeat ticks -- resurrection scan "
        "appears to be blocking the event loop"
    )


# ---------------------------------------------------------------------------
# _hebbian_promote
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hebbian_promote_writes_named_edge():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "Kùzu", "c2", "ChromaDB", 15]],
    })
    llm = _make_llm({"relation_type": "CHOSEN_OVER", "confidence": 0.88})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 1
    assert e == 0
    assert any("CHOSEN_OVER" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_hebbian_promote_skips_low_confidence():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "A", "c2", "B", 12]],
    })
    llm = _make_llm({"relation_type": "REQUIRES", "confidence": 0.45})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0
    assert len(db.written) == 0


@pytest.mark.asyncio
async def test_hebbian_promote_skips_null_relation():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "A", "c2", "B", 12]],
    })
    llm = _make_llm({"relation_type": None, "confidence": 0.0})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0


@pytest.mark.asyncio
async def test_hebbian_promote_skips_unknown_relation_type():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "A", "c2", "B", 12]],
    })
    llm = _make_llm({"relation_type": "INVENTED_TYPE", "confidence": 0.95})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0


@pytest.mark.asyncio
async def test_hebbian_promote_handles_bad_llm_json():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "A", "c2", "B", 12]],
    })
    llm = _make_bad_llm()
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0
    # Bad JSON should be silently swallowed, not counted as error
    assert e == 0


@pytest.mark.asyncio
async def test_hebbian_promote_skips_empty_text():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "", "c2", "B", 12]],
    })
    llm = _make_llm({"relation_type": "REQUIRES", "confidence": 0.9})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0


@pytest.mark.asyncio
async def test_hebbian_promote_empty_db_no_error():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db()
    llm = _make_llm({"relation_type": "REQUIRES", "confidence": 0.9})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 0
    assert e == 0


@pytest.mark.asyncio
async def test_hebbian_promote_writes_inferred_by_llm():
    from campy.brain.brainstem.sweep import _hebbian_promote
    db = _make_db(rows_by_query={
        "CO_OCCURS_WITH": [["c1", "FastAPI", "c2", "uvicorn", 20]],
    })
    llm = _make_llm({"relation_type": "REQUIRES", "confidence": 0.91})
    p, e = await _hebbian_promote(db, llm, co_occurrence_threshold=10)
    assert p == 1
    write = next(w for w in db.written if "REQUIRES" in w["q"])
    assert write["p"]["conf"] == 0.91


# ---------------------------------------------------------------------------
# _recompute_centroids (M4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompute_centroids_updates_gist_class():
    from campy.brain.brainstem.sweep import _recompute_centroids
    embedding = [1.0] + [0.0] * 383
    db = _make_db(rows_by_query={
        "DISTINCT e.gist_class": [["Decision"]],
        "GistExample": [[embedding]],
    })
    c, e = await _recompute_centroids(db)
    assert c == 1
    assert e == 0
    # Should write updated centroid to GistClass
    assert any("GistClass" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_recompute_centroids_empty_db_no_error():
    from campy.brain.brainstem.sweep import _recompute_centroids
    db = _make_db()
    c, e = await _recompute_centroids(db)
    assert c == 0
    assert e == 0


@pytest.mark.asyncio
async def test_recompute_centroids_mean_pools_multiple_examples():
    from campy.brain.brainstem.sweep import _recompute_centroids
    emb_a = [1.0, 0.0] + [0.0] * 382
    emb_b = [0.0, 1.0] + [0.0] * 382
    db = _make_db(rows_by_query={
        "DISTINCT e.gist_class": [["Restriction"]],
        "GistExample": [[emb_a], [emb_b]],
    })
    c, e = await _recompute_centroids(db)
    assert c == 1
    assert e == 0
    write = next(w for w in db.written if "GistClass" in w["q"])
    centroid = write["p"]["centroid"]
    # Mean of emb_a and emb_b: [0.5, 0.5, 0, ...], then normalized to unit vector
    # Both first two dims should be equal
    assert abs(centroid[0] - centroid[1]) < 1e-6


@pytest.mark.asyncio
async def test_run_sweep_summary_includes_centroids_updated():
    from campy.brain.brainstem.sweep import run_sweep
    db = _make_db()
    config = {"pruning": {"sweep_interval_seconds": 300, "archive_threshold": 0.10,
                          "resurrection_threshold": 0.85, "decay_rate": {}}}
    result = await run_sweep(db, config, llm_client=None)
    assert "centroids_updated" in result
