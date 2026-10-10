"""B476 (M1.2) write path: every Message knows its position in its session.

The DMR conversations are mostly one speaker's turns from one session, all
stamped with the same speaker and time, so the answer model could not order
them. notify_turn now numbers each turn: `Message.turn_index` = the number of
Messages the session already held (0-based). A turn without a session, and any
store that predates the column, has none.
"""

from __future__ import annotations

import asyncio

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.schema import SCHEMA_MIGRATIONS, get_all_table_properties
from campy.brain.thalamus.tools import capture

DIM = 384
EMB = [1.0] + [0.0] * (DIM - 1)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "test_b476.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(capture.emb, "embed", lambda text, model_name=None: list(EMB))
    monkeypatch.setattr(capture, "get_loop_queue", lambda: None)

    async def _route(*a, **k):
        class R:
            quest_id = ""
        return R()

    import campy.brain.hippocampus.hippocampus as hip
    monkeypatch.setattr(hip, "route_session", _route)


async def _session(gw, sid):
    await gw.run("quests.merge_session_git_locked", sid=sid, now="2026-10-10T10:00:00+00:00")


async def _turn(db, sid, text):
    res = await capture.notify_turn({"role": "user", "content": text, "session_id": sid}, db, {})
    assert res.get("status") != "skipped", res
    return res


def _indices(db) -> dict[str, int | None]:
    rows = db._execute_and_collect(
        "SELECT ?t ?i WHERE { ?m a <https://campy.dev/ns#Message> ; "
        "<https://campy.dev/ns#text_raw> ?t . "
        "OPTIONAL { ?m <https://campy.dev/ns#turn_index> ?i } }")
    return {r["t"]: r.get("i") for r in rows}


def test_migration_declares_the_column():
    assert ("Message", "turn_index", "INT64") in SCHEMA_MIGRATIONS
    assert "turn_index" in get_all_table_properties()["Message"]


@pytest.mark.asyncio
async def test_an_old_message_without_the_column_has_none(gw, db):
    # a Message written by the pre-B476 path: nothing but create_message
    await gw.run("capture.create_message", message_id="old", text_raw="before the column",
                 embedding=EMB, embedding_model="m", embedding_dim=DIM, role="user",
                 byte_end=3, created_at="2026-10-01T10:00:00+00:00")
    assert _indices(db)["before the column"] is None


@pytest.mark.asyncio
async def test_indices_increase_within_a_session_and_are_independent_across_sessions(gw, db):
    await _session(gw, "s1")
    await _session(gw, "s2")
    for i in range(3):
        await _turn(db, "s1", f"s1 turn {i}")
    await _turn(db, "s2", "s2 turn 0")
    await _turn(db, "s1", "s1 turn 3")
    await _turn(db, "s2", "s2 turn 1")
    got = _indices(db)
    assert [got[f"s1 turn {i}"] for i in range(4)] == [0, 1, 2, 3]
    assert [got[f"s2 turn {i}"] for i in range(2)] == [0, 1]


@pytest.mark.asyncio
async def test_a_session_that_already_holds_messages_continues_the_count(gw, db):
    await _session(gw, "s3")
    for n in range(2):  # pre-existing, un-numbered (as in an old store)
        await gw.run("capture.create_message", message_id=f"o{n}", text_raw=f"old {n}",
                     embedding=EMB, embedding_model="m", embedding_dim=DIM, role="user",
                     byte_end=3, created_at="2026-10-01T10:00:00+00:00")
        await gw.run("capture.link_message_sent_in_session", session_id="s3", message_id=f"o{n}")
    await _turn(db, "s3", "new turn")
    got = _indices(db)
    assert got["new turn"] == 2 and got["old 0"] is None


@pytest.mark.asyncio
async def test_a_turn_without_a_session_has_no_index(db):
    await _turn(db, "unknown", "no session here")
    assert _indices(db)["no session here"] is None


@pytest.mark.asyncio
async def test_concurrent_turns_in_one_session_get_distinct_consecutive_indices(gw, db):
    await _session(gw, "s4")
    await asyncio.gather(*[_turn(db, "s4", f"c{i}") for i in range(8)])
    got = sorted(int(v) for v in _indices(db).values())
    assert got == list(range(8))


@pytest.mark.asyncio
async def test_the_lock_is_what_prevents_a_shared_index():
    """Count and link are separate awaits; without the per-session lock two
    callers both read the same count. A gateway that yields in between makes
    the race deterministic."""

    class Slow:
        def __init__(self):
            self.linked = 0
            self.assigned = []

        async def run(self, name, **p):
            if name == "capture.count_messages_in_session":
                n = self.linked
                await asyncio.sleep(0.01)
                return [{"n": n}]
            if name == "capture.link_message_sent_in_session":
                await asyncio.sleep(0.01)
                self.linked += 1
            if name == "capture.set_message_turn_index":
                self.assigned.append(p["turn_index"])
            return []

    async def number(gw):
        async with capture._session_turn_lock("sx"):
            idx = await capture._next_turn_index(gw, "sx")
            await gw.run("capture.link_message_sent_in_session")
            await gw.run("capture.set_message_turn_index", message_id="x", turn_index=idx)

    gw = Slow()
    await asyncio.gather(*[number(gw) for _ in range(5)])
    assert sorted(gw.assigned) == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_a_failing_count_never_fails_capture(monkeypatch, db, gw):
    await _session(gw, "s5")

    async def boom(gw_, sid):
        return None

    monkeypatch.setattr(capture, "_next_turn_index", boom)
    await _turn(db, "s5", "still captured")
    assert _indices(db)["still captured"] is None
