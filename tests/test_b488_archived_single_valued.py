"""B488 -- archiving a Message leaves exactly one `archived` value, readers
treat any true value as archived, and the repair fixes already-affected stores."""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.cli.graph_repair import (
    find_double_archived_messages,
    repair_double_archived_messages,
)

ARCH = "https://campy.dev/ns#archived"
OLD = "memory_key: abc123\nPostgreSQL 14 is the production database."
NEW = "memory_key: abc123\nPostgreSQL 16 is the production database."
Q = "What is the production database?"


@pytest.fixture
def ox(tmp_path):
    return OxigraphClient(tmp_path / "b488.db")


@pytest.fixture
def gw(ox):
    return GraphGateway(ox, REGISTRY)


async def _add(gw, mid, text, created="2026-09-20T10:00:00+00:00", role="user"):
    await gw.run(
        "capture.create_message", message_id=mid, text_raw=text, embedding=emb.embed(text),
        embedding_model="m", embedding_dim=384, role=role, byte_end=len(text), created_at=created,
    )


def _values(ox, mid):
    rows = ox._execute_and_collect(
        f'SELECT ?a WHERE {{ ?m <https://campy.dev/ns#message_id> "{mid}" ; <{ARCH}> ?a }}'
    )
    return sorted(bool(r["a"]) for r in rows)


async def _inject_stale_false(ox, mid):
    """Reproduce a store written by the pre-B488 query."""
    ox.execute(
        f'INSERT {{ ?m <{ARCH}> false }} WHERE {{ ?m <https://campy.dev/ns#message_id> "{mid}" }}'
    )


async def _conversation(gw):
    return await gw.run("thalamus.bundle_conversation", query_embedding=emb.embed(Q),
                        query_text=Q, limit=5, order="time")


@pytest.mark.asyncio
async def test_archive_write_leaves_exactly_one_true_value(gw, ox):
    await _add(gw, "old", OLD)
    await gw.run("capture.archive_earlier_message_version", marker="memory_key: abc123")
    assert _values(ox, "old") == [True]


@pytest.mark.asyncio
async def test_archive_only_touches_live_messages_and_is_repeatable(gw, ox):
    await _add(gw, "old", OLD)
    await _add(gw, "other", "Unrelated message about Redis caching.")
    await gw.run("capture.archive_earlier_message_version", marker="memory_key: abc123")
    await gw.run("capture.archive_earlier_message_version", marker="memory_key: abc123")
    assert _values(ox, "old") == [True]
    assert _values(ox, "other") == [False]


@pytest.mark.asyncio
async def test_conversation_stage_never_returns_an_archived_turn(gw, ox):
    await _add(gw, "old", OLD)
    await _add(gw, "new", NEW, created="2026-09-21T10:00:00+00:00")
    await gw.run("capture.archive_earlier_message_version", marker="PostgreSQL 14")
    texts = [r["text"] for r in await _conversation(gw)]
    assert not any("PostgreSQL 14" in t for t in texts)
    assert any("PostgreSQL 16" in t for t in texts)


@pytest.mark.asyncio
async def test_readers_treat_a_double_valued_message_as_archived(gw, ox):
    await _add(gw, "old", OLD)
    await _add(gw, "new", NEW, created="2026-09-21T10:00:00+00:00")
    await gw.run("capture.archive_earlier_message_version", marker="PostgreSQL 14")
    await _inject_stale_false(ox, "old")
    assert _values(ox, "old") == [False, True]
    texts = [r["text"] for r in await _conversation(gw)]
    assert not any("PostgreSQL 14" in t for t in texts)
    rows = gw._hydrate_messages([str(r["s"]) for r in ox._execute_and_collect(
        'SELECT ?s WHERE { ?s <https://campy.dev/ns#message_id> "old" }')])
    assert len(rows) == 1 and bool(rows[0]["archived"])


@pytest.mark.asyncio
async def test_observation_evidence_lookup_sees_archived_on_double_value(gw, ox):
    await _add(gw, "old", OLD)
    await gw.run("capture.archive_earlier_message_version", marker="PostgreSQL 14")
    await _inject_stale_false(ox, "old")
    rows = await gw.run("observations.get_message", mid="old")
    assert bool(rows[0]["archived"])


@pytest.mark.asyncio
async def test_repair_fixes_double_valued_messages_and_is_idempotent(gw, ox):
    await _add(gw, "old", OLD)
    await _add(gw, "live", "Cache is Memcached on port 11211.")
    await gw.run("capture.archive_earlier_message_version", marker="PostgreSQL 14")
    await _inject_stale_false(ox, "old")

    dry = await repair_double_archived_messages(ox, apply=False)
    assert dry == ["old"] and _values(ox, "old") == [False, True]   # dry run writes nothing

    assert await repair_double_archived_messages(ox, apply=True) == ["old"]
    assert _values(ox, "old") == [True]
    assert _values(ox, "live") == [False]
    assert await find_double_archived_messages(ox) == []
    assert await repair_double_archived_messages(ox, apply=True) == []
    assert _values(ox, "old") == [True]
