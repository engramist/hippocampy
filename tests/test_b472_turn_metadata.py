"""B472 Phase 1: a turn's speaker and when it happened are data, not text.

Before, a caller that knew who spoke and when (an imported or replayed
history, a multi-party chat) had to write "[date] Name:" into `content`,
and Step 1 of the Loop extracted the prefix as concepts ("Speaker",
"1, 7 days"). notify_turn now takes `speaker` and `occurred_at`; the
Message stores them, the conversation stages rank and stamp by them, and a
call without them is unchanged.

Embeddings are hand-built (as in test_b459/test_b471), so the gateway tests
don't depend on the embedding model.
"""

from __future__ import annotations

import math

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import bundle_compiler
from campy.brain.thalamus.tools import capture
from campy.brain.thalamus.tools.capture import _parse_occurred_at

DIM = 384
QUERY_EMB = [1.0] + [0.0] * (DIM - 1)
NS = "https://campy.dev/ns#"


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "test_b472.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def _emb(n: int, cos: float) -> list[float]:
    v = [0.0] * DIM
    v[0], v[n] = cos, math.sqrt(1.0 - cos * cos)
    return v


async def _add(gw, n: int, text: str, cos: float, created: str, *, role="user", speaker=None, occurred=None):
    await gw.run(
        "capture.create_message",
        message_id=f"m{n}", text_raw=text, embedding=_emb(n, cos), embedding_model="m",
        embedding_dim=DIM, role=role, byte_end=len(text), created_at=created,
        speaker=speaker, occurred_at=occurred,
    )


def _props(db, message_id: str) -> dict:
    rows = db._execute_and_collect(
        f"SELECT ?p ?o WHERE {{ <https://campy.dev/id/Message/{message_id}> ?p ?o }}")
    return {str(r["p"]).rsplit("#", 1)[-1]: r["o"] for r in rows}


# --- the write -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_speaker_and_occurred_at_are_stored_on_the_message(gw, db):
    await _add(gw, 1, "I went to a support group yesterday.", 0.6, "2026-10-09T10:00:00+00:00",
               speaker="Caroline", occurred="2023-05-08T13:56:00+00:00")
    p = _props(db, "m1")
    assert p["speaker"] == "Caroline"
    assert str(p["occurred_at"]).startswith("2023-05-08T13:56")
    assert p["text_raw"] == "I went to a support group yesterday."  # no prefix in the text


@pytest.mark.asyncio
async def test_without_them_nothing_is_written(gw, db):
    await _add(gw, 2, "Plain turn.", 0.6, "2026-10-09T10:00:00+00:00")
    p = _props(db, "m2")
    assert "speaker" not in p and "occurred_at" not in p
    assert p["role"] == "user"


@pytest.mark.parametrize("raw, expected", [
    ("2023-05-08T13:56:00+00:00", "2023-05-08T13:56:00+00:00"),
    ("2023-05-08T13:56:00Z", "2023-05-08T13:56:00+00:00"),
    ("2023-05-08T07:56:00-06:00", "2023-05-08T13:56:00+00:00"),  # normalized to UTC
    ("2023-05-08 13:56", "2023-05-08T13:56:00+00:00"),  # no zone: UTC
    ("2023-05-08", "2023-05-08T00:00:00+00:00"),
    ("8 May 2023", None),  # not ISO: dropped, never fatal
    ("", None),
    (None, None),
])
def test_parse_occurred_at(raw, expected):
    assert _parse_occurred_at(raw) == expected


class _Recorder:
    """Captures what notify_turn writes and queues, without a daemon."""

    def __init__(self):
        self.created, self.queued = [], []

    async def run(self, name, **params):
        if name == "capture.create_message":
            self.created.append(params)
        return []

    def run_sync(self, name, **params):
        return []


class _Queue:
    def __init__(self, sink):
        self.sink = sink

    async def put(self, item):
        self.sink.append(item)


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(capture, "_gateway", lambda db: rec)
    monkeypatch.setattr(capture.emb, "embed", lambda text, model_name=None: list(QUERY_EMB))
    monkeypatch.setattr(capture, "get_loop_queue", lambda: _Queue(rec.queued))

    async def _route(*a, **k):
        class R:
            quest_id = ""
        return R()

    import campy.brain.hippocampus.hippocampus as hip
    monkeypatch.setattr(hip, "route_session", _route)
    return rec


@pytest.mark.asyncio
async def test_notify_turn_passes_them_through_and_queues_only_the_content(recorder):
    await capture.notify_turn({"role": "user", "content": "I adopted a puppy!", "session_id": "unknown",
                               "speaker": " Melanie ", "occurred_at": "2023-07-12T09:30:00Z"}, None, {})
    params = recorder.created[0]
    assert params["speaker"] == "Melanie"
    assert params["occurred_at"] == "2023-07-12T09:30:00+00:00"
    assert params["text_raw"] == "I adopted a puppy!"
    # the Loop (Step 1 NER) sees the content only, never the metadata
    assert recorder.queued[0][1] == "I adopted a puppy!"


@pytest.mark.asyncio
async def test_notify_turn_without_them_is_unchanged(recorder):
    await capture.notify_turn({"role": "user", "content": "hello there", "session_id": "unknown"}, None, {})
    params = recorder.created[0]
    assert params["speaker"] is None and params["occurred_at"] is None


@pytest.mark.asyncio
async def test_a_speaker_that_only_repeats_the_role_is_dropped(recorder):
    await capture.notify_turn({"role": "assistant", "content": "Sure.", "session_id": "unknown",
                               "speaker": "assistant", "occurred_at": "not a date"}, None, {})
    params = recorder.created[0]
    assert params["speaker"] is None and params["occurred_at"] is None


# --- the read --------------------------------------------------------------------

async def _chat(gw) -> None:
    # stored today, in reverse order of when they happened
    await _add(gw, 1, "Caroline: no wait, I moved to Denver in June.", 0.55, "2026-10-09T10:05:00+00:00",
               speaker="Caroline", occurred="2023-06-20T18:00:00+00:00")
    await _add(gw, 2, "I live in Austin and love it.", 0.62, "2026-10-09T10:00:00+00:00",
               speaker="Caroline", occurred="2023-05-08T13:56:00+00:00")
    await _add(gw, 3, "Where do you live these days?", 0.70, "2026-10-09T10:01:00+00:00",
               speaker="Melanie", occurred="2023-05-08T13:55:00+00:00")


@pytest.mark.asyncio
async def test_conversation_rows_carry_speaker_and_occurred_time(gw):
    await _chat(gw)
    rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text="Where does Caroline live?", limit=6)
    by_text = {r["text"]: r for r in rows}
    austin = by_text["I live in Austin and love it."]
    assert austin["speaker"] == "Caroline"
    assert str(austin["created_at"]).startswith("2023-05-08T13:56")
    # oldest first by when it happened, not by when it was stored
    texts = [r["text"] for r in rows]
    assert texts.index("I live in Austin and love it.") < texts.index(
        "Caroline: no wait, I moved to Denver in June.")


@pytest.mark.asyncio
async def test_a_message_without_metadata_still_uses_created_at(gw):
    await _add(gw, 4, "We picked PostgreSQL for the main store.", 0.6, "2026-10-09T10:00:00+00:00")
    rows = await gw.run("thalamus.bundle_conversation", query_embedding=QUERY_EMB,
                        query_text="Which database did we pick?", limit=6)
    assert rows and str(rows[0]["created_at"]).startswith("2026-10-09T10:00")
    assert rows[0].get("speaker") is None


class _FakeGateway:
    def __init__(self, rows):
        self.rows = rows

    async def run(self, name, **params):
        return self.rows


@pytest.fixture
def fake_rows(monkeypatch):
    from campy.brain.hippocampus.graph import embeddings

    def install(rows):
        monkeypatch.setattr(bundle_compiler, "get_gateway", lambda db: _FakeGateway(rows))
        monkeypatch.setattr(embeddings, "embed", lambda text, model_name=None: QUERY_EMB)
    return install


@pytest.mark.asyncio
async def test_the_bundle_stamps_the_speaker_and_the_time_it_happened(fake_rows):
    fake_rows([
        {"text": "I live in Austin.", "created_at": "2023-05-08T13:56:00+00:00", "speaker": "Caroline",
         "node_id": "m2"},
        {"text": "We picked PostgreSQL.", "created_at": "2026-10-09T10:00:00+00:00", "node_id": "m4"},
    ])
    section = await bundle_compiler._stage_conversation(None, "Where does Caroline live?", {})
    texts = [c["text"] for c in section.content]
    assert texts[0] == "[Caroline, 2023-05-08 13:56] I live in Austin."
    assert texts[1] == "[user, 2026-10-09 10:00] We picked PostgreSQL."  # unchanged without a speaker


@pytest.mark.asyncio
async def test_the_assistant_section_keeps_its_label(fake_rows):
    fake_rows([{"text": "Try trofie.", "created_at": "2023-05-10T12:00:00+00:00", "speaker": "Chef bot",
                "node_id": "m5"},
               {"text": "Linguine works too.", "created_at": "2023-05-10T12:01:00+00:00", "node_id": "m6"}])
    section = await bundle_compiler._stage_assistant_words(None, "Which pasta did you suggest?", {})
    texts = [c["text"] for c in section.content]
    assert texts[0] == "[Chef bot (assistant) said, 2023-05-10 12:00] Try trofie."
    assert texts[1] == "[assistant said, 2023-05-10 12:01] Linguine works too."
