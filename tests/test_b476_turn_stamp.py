"""B476 (M1.2) read path: bundle_conversation rows carry the turn ordinal and,
in "time" order, use it to break timestamp ties. The stamp does NOT render it
(gate R39g: a `turn N` stamp cost DMR 0.600 -> 0.540).

(The near-duplicate collapse originally in this card was removed after gate
R37 -- it never fired on the golden stores -- so only the ordinal remains.)
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)


def _emb(n: int, cos: float) -> list[float]:
    import math
    v = [0.0] * DIM
    v[0], v[n] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "test_b476_turn_stamp.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _add(gw, n, text, cos, created, *, session="s1", speaker="Speaker 1", turn=None):
    await gw.run("capture.create_message", message_id=f"m{n}", text_raw=text, embedding=_emb(n, cos),
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=created)
    if speaker:
        await gw.run("capture.set_message_source", message_id=f"m{n}", speaker=speaker, occurred_at=None)
    if session:
        await gw.run("quests.merge_session_git_locked", sid=session, now=created)
        await gw.run("capture.link_message_sent_in_session", session_id=session, message_id=f"m{n}")
    if turn is not None:
        await gw.run("capture.set_message_turn_index", message_id=f"m{n}", turn_index=turn)


async def _rows(gw, *, limit, order="rank"):
    return await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text="what did I plan?", limit=limit, order=order)


T = "2026-10-10T10:0{}:00+00:00"


@pytest.mark.asyncio
async def test_rows_carry_the_turn_index_and_old_messages_have_none(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.9, T.format(1), turn=4)
    await _add(gw, 2, "Also the roof needs new shingles.", 0.5, T.format(2))  # predates B476
    by = {r["text"]: r.get("turn_index") for r in await _rows(gw, limit=6)}
    assert by["I plan to repaint the garage in June."] == 4
    assert by["Also the roof needs new shingles."] is None


# --- the stamp and the stage's config ---------------------------------------------

async def test_same_timestamp_turns_come_out_in_turn_order_in_time_mode(gw):
    # insertion order deliberately scrambled relative to turn_index
    await _add(gw, 1, "third thing I said.", 0.9, T.format(1), turn=2)
    await _add(gw, 2, "first thing I said.", 0.9, T.format(1), turn=0)
    await _add(gw, 3, "second thing I said.", 0.9, T.format(1), turn=1)
    rows = await _rows(gw, limit=6, order="time")
    assert [r["text"] for r in rows] == [
        "first thing I said.", "second thing I said.", "third thing I said."]


@pytest.mark.asyncio
async def test_time_still_wins_over_turn_index(gw):
    await _add(gw, 1, "later but low ordinal.", 0.9, T.format(2), turn=0)
    await _add(gw, 2, "earlier but high ordinal.", 0.9, T.format(1), turn=9)
    rows = await _rows(gw, limit=6, order="time")
    assert [r["text"] for r in rows] == ["earlier but high ordinal.", "later but low ordinal."]


@pytest.mark.asyncio
async def test_none_turn_index_does_not_crash_and_sorts_after_numbered(gw):
    await _add(gw, 1, "old turn without ordinal.", 0.9, T.format(1))
    await _add(gw, 2, "numbered turn.", 0.9, T.format(1), turn=3)
    await _add(gw, 3, "other old turn.", 0.9, T.format(2))
    rows = await _rows(gw, limit=6, order="time")
    assert [r["text"] for r in rows] == [
        "numbered turn.", "old turn without ordinal.", "other old turn."]


@pytest.mark.asyncio
async def test_all_none_rows_keep_the_pre_b476_order(gw):
    # sort is stable: equal timestamps and no ordinals -> same order as sorting on created alone
    for n in (1, 2, 3):
        await _add(gw, n, f"row {n} says something.", 0.9, T.format(1))
    rows = await _rows(gw, limit=6, order="time")
    with_key = sorted(rows, key=lambda r: (r["created_at"], r.get("turn_index") is None))
    assert [r["text"] for r in rows] == [r["text"] for r in with_key]
    assert all(r.get("turn_index") is None for r in rows)


@pytest.mark.asyncio
async def test_rank_mode_ignores_turn_index(gw):
    await _add(gw, 1, "best match here.", 0.95, T.format(1), turn=5)
    await _add(gw, 2, "weaker match here.", 0.6, T.format(1), turn=0)
    rows = await _rows(gw, limit=6, order="rank")
    assert [r["text"] for r in rows][0] == "best match here."


class _Capturing:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def run(self, name, **params):
        self.calls.append((name, params))
        return self.rows


@pytest.fixture
def stage(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    def install(rows):
        fake = _Capturing(rows)
        monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: fake)
        monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
        return fake
    return install


@pytest.mark.asyncio
async def test_stage_stamp_is_mains_format_even_with_an_ordinal(stage):
    stage([{"text": "a", "created_at": "2022-12-14T07:00:00+00:00", "speaker": "Speaker 1", "turn_index": 5,
            "node_id": "m1"},
           {"text": "b", "created_at": "2022-12-14T07:00:00+00:00", "speaker": "Speaker 1", "node_id": "m2"},
           {"text": "c", "created_at": "", "node_id": "m3"}])
    section = await bundle_compiler._stage_conversation(None, "q", {})
    assert [c["text"] for c in section.content] == [
        "[Speaker 1, 2022-12-14 07:00] a", "[Speaker 1, 2022-12-14 07:00] b", "[user] c"]
    assert not hasattr(bundle_compiler, "_turn_stamp")
