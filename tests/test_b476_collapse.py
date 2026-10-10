"""B476 (M1.2) read path: the turn ordinal in the stamp, and near-duplicate
collapse in the conversation stage's pack step.

Embeddings are hand-built so cosines are exact: a turn is `cos*e0 + sin*e_n`,
so its similarity to the query (e0) is `cos` and two turns with different `n`
have similarity `cos_a * cos_b`.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway, _cosine
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
COLLAPSING = "thalamus.bundle_conversation_collapsing"


def _emb(n: int, cos: float) -> list[float]:
    v = [0.0] * DIM
    v[0], v[n] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "test_b476_collapse.db")


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


async def _rows(gw, *, limit, cosine, order="rank", name=COLLAPSING):
    return await gw.run(name, query_embedding=QUERY_EMB, query_text="what did I plan?",
                        limit=limit, order=order, collapse_cosine=cosine)


def _texts(rows):
    return [r["text"] for r in rows]


T = "2026-10-10T10:0{}:00+00:00"


# --- the pack step against a real store -------------------------------------------

@pytest.mark.asyncio
async def test_a_near_duplicate_is_dropped_keeping_the_better_ranked_and_the_slot_is_backfilled(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.97, T.format(1))
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2))  # 0.97*0.96 = 0.93
    await _add(gw, 3, "Also the roof needs new shingles.", 0.60, T.format(3))
    kept = _texts(await _rows(gw, limit=2, cosine=0.9))
    assert kept == ["I plan to repaint the garage in June.", "Also the roof needs new shingles."]
    # off: the duplicate takes the second slot
    off = _texts(await _rows(gw, limit=2, cosine=0.0))
    assert off == ["I plan to repaint the garage in June.", "I plan on repainting the garage this June."]


@pytest.mark.asyncio
async def test_the_better_ranked_is_kept_even_when_stored_later(gw):
    await _add(gw, 1, "I plan on repainting the garage this June.", 0.93, T.format(1))
    await _add(gw, 2, "I plan to repaint the garage in June.", 0.98, T.format(2))
    kept = _texts(await _rows(gw, limit=2, cosine=0.9))
    assert kept == ["I plan to repaint the garage in June."]


@pytest.mark.asyncio
async def test_different_speakers_or_sessions_are_not_collapsed(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.97, T.format(1))
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2), speaker="Speaker 2")
    await _add(gw, 3, "Repainting the garage is my June plan.", 0.96, T.format(3), session="s2")
    assert len(await _rows(gw, limit=6, cosine=0.9)) == 3


@pytest.mark.asyncio
async def test_a_turn_without_a_session_is_never_collapsed(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.97, T.format(1), session=None)
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2), session=None)
    assert len(await _rows(gw, limit=6, cosine=0.9)) == 2


@pytest.mark.asyncio
async def test_threshold_is_respected(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.97, T.format(1))
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2))  # pair cosine 0.931
    assert len(await _rows(gw, limit=6, cosine=0.9)) == 1
    assert len(await _rows(gw, limit=6, cosine=0.95)) == 2


@pytest.mark.asyncio
async def test_collapse_works_with_time_order(gw):
    await _add(gw, 1, "Late: the roof needs new shingles.", 0.60, T.format(1))
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2))
    await _add(gw, 3, "I plan to repaint the garage in June.", 0.97, T.format(3))
    kept = _texts(await _rows(gw, limit=6, cosine=0.9, order="time"))
    assert kept == ["Late: the roof needs new shingles.", "I plan to repaint the garage in June."]


@pytest.mark.asyncio
async def test_rows_carry_the_turn_index_and_old_messages_have_none(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.9, T.format(1), turn=4)
    await _add(gw, 2, "Also the roof needs new shingles.", 0.5, T.format(2))  # predates B476
    by = {r["text"]: r.get("turn_index") for r in await _rows(gw, limit=6, cosine=0.9)}
    assert by["I plan to repaint the garage in June."] == 4
    assert by["Also the roof needs new shingles."] is None


@pytest.mark.asyncio
async def test_the_original_query_is_unchanged_and_does_not_collapse(gw):
    await _add(gw, 1, "I plan to repaint the garage in June.", 0.97, T.format(1))
    await _add(gw, 2, "I plan on repainting the garage this June.", 0.96, T.format(2))
    rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text="what did I plan?", limit=6, order="rank")
    assert len(rows) == 2


# --- the pick, against a fake vector store -----------------------------------------

class _Vectors:
    def __init__(self, vecs):
        self.vecs, self.fetched = vecs, []

    def get_vector(self, uri):
        self.fetched.append(uri)
        return self.vecs.get(uri)


def _pick(vecs, cands, limit, cosine=0.9):
    g = GraphGateway.__new__(GraphGateway)
    g._vector_store = _Vectors(vecs)
    return g._pick_conversation(cands, limit, cosine), g._vector_store


def _c(uri, session="s", speaker="a"):
    return ("t", {"uri": uri, "session": session, "speaker": speaker})


def test_pick_collapses_in_rank_order_and_backfills():
    vecs = {"u1": [1.0, 0.0], "u2": [0.99, 0.14], "u3": [0.0, 1.0], "u4": [0.5, 0.5]}
    picked, _ = _pick(vecs, [_c("u1"), _c("u2"), _c("u3"), _c("u4")], limit=3)
    assert [kv[1]["uri"] for kv in picked] == ["u1", "u3", "u4"]


def test_pick_does_not_fetch_vectors_it_does_not_need():
    cands = [_c("u1", session="s1"), _c("u2", session="s2"), _c("u3", speaker="b")]
    picked, store = _pick({}, cands, limit=6)
    assert len(picked) == 3 and store.fetched == []


def test_pick_keeps_a_candidate_with_no_stored_vector():
    picked, _ = _pick({"u1": [1.0, 0.0]}, [_c("u1"), _c("u2")], limit=6)
    assert len(picked) == 2


def test_pick_off_is_a_plain_truncation():
    picked, store = _pick({}, [_c("u1"), _c("u2"), _c("u3")], limit=2, cosine=0.0)
    assert [kv[1]["uri"] for kv in picked] == ["u1", "u2"] and store.fetched == []


def test_cosine():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# --- the stamp and the stage's config ---------------------------------------------

def test_stamp_with_and_without_the_index():
    assert bundle_compiler._turn_stamp("Speaker 1", "2022-12-14 07:00", 5) == "[Speaker 1, 2022-12-14 07:00, turn 5] "
    assert bundle_compiler._turn_stamp("Speaker 1", "2022-12-14 07:00", 0) == "[Speaker 1, 2022-12-14 07:00, turn 0] "
    assert bundle_compiler._turn_stamp("Speaker 1", "2022-12-14 07:00", None) == "[Speaker 1, 2022-12-14 07:00] "
    assert bundle_compiler._turn_stamp("user", "", None) == "[user] "
    assert bundle_compiler._turn_stamp("user", "", 3) == "[user, turn 3] "
    assert bundle_compiler._turn_stamp("user", "x", "oops") == "[user, x] "


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
async def test_stage_stamps_the_ordinal_when_present(stage):
    stage([{"text": "a", "created_at": "2022-12-14T07:00:00+00:00", "speaker": "Speaker 1", "turn_index": 5,
            "node_id": "m1"},
           {"text": "b", "created_at": "2022-12-14T07:00:00+00:00", "speaker": "Speaker 1", "node_id": "m2"}])
    section = await bundle_compiler._stage_conversation(None, "q", {})
    assert [c["text"] for c in section.content] == [
        "[Speaker 1, 2022-12-14 07:00, turn 5] a", "[Speaker 1, 2022-12-14 07:00] b"]


@pytest.mark.asyncio
async def test_stage_config_defaults_and_overrides(stage):
    fake = stage([{"text": "a", "created_at": "2022-12-14T07:00:00+00:00", "node_id": "m1"}])
    await bundle_compiler._stage_conversation(None, "q", {})
    name, params = fake.calls[-1]
    assert name == COLLAPSING and params["collapse_cosine"] == 0.9

    await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"near_duplicate_cosine": 0.8}})
    assert fake.calls[-1][1]["collapse_cosine"] == 0.8

    await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"collapse_near_duplicates": False}})
    assert fake.calls[-1][1]["collapse_cosine"] == 0.0

    for bad in ("high", 0, 1.5, None):
        await bundle_compiler._stage_conversation(None, "q", {"retrieval": {"near_duplicate_cosine": bad}})
        assert fake.calls[-1][1]["collapse_cosine"] == 0.9
