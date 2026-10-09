"""B472 Phase 2: one entity, one Concept.

On a LoCoMo-10 store (B472 Phase 0), "Caroline", "Caroline!", "Congrats
Caroline" and "Wow Caroline" were four Concepts: dedup was exact text only,
and nothing normalized the span spaCy returned. Phase 2:

- normalizes each entity's surface before anything is matched or stored
  (edge punctuation, quotes, a final possessive; greeting/interjection
  words at the edges of a PERSON span or one naming the speaker);
- resolves a surface recorded as one of a Concept's labels to that Concept;
- records a differently worded entity merged into a Concept as one of its
  alternative Labels (SKOS label accumulation);
- seeds a named speaker as a Person Concept;
- never merges two different people who share a first name.

The Loop worker also accepts every queue item shape its producers send:
ingest_document put a 4-tuple, which the 5-name unpack turned into the
same crash-loop B434 fixed for notify_turn.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop.step1_ner import normalize_entities, normalize_surface

DIM = 384
VEC = [1.0] + [0.0] * (DIM - 1)
NOW = "2026-10-09T10:00:00+00:00"
STEP4 = {"confidence": 0.7, "confidence_low": True}


# --- surface normalization -----------------------------------------------------------

@pytest.mark.parametrize("span, label, expected", [
    ("Caroline!", "PERSON", "Caroline"),
    ("Congrats Caroline", "PERSON", "Caroline"),
    ("Wow Caroline!!", "PERSON", "Caroline"),
    ("Thank you Caroline", "PERSON", "Caroline"),
    ("Hey Melanie,", "PERSON", "Melanie"),
    ("Caroline's", "PERSON", "Caroline"),
    ('"React"', "ORG", "React"),
    # internal punctuation and numbers are part of the name
    ("Node.js", "ORG", "Node.js"),
    ("C++", "LANGUAGE", "C++"),
    ("PostgreSQL 16", "PRODUCT", "PostgreSQL 16"),
    # names are never cut down, and a span is never normalized to nothing
    ("Sam Lee", "PERSON", "Sam Lee"),
    ("Will Smith", "PERSON", "Will Smith"),
    ("Hi", "PERSON", "Hi"),
    # greeting words are only stripped around a name
    ("good morning routine", "NOUN_CHUNK", "good morning routine"),
    ("ten years ago", "DATE", "ten years ago"),
])
def test_normalize_surface(span, label, expected):
    assert normalize_surface(span, label) == expected


def test_a_known_speaker_name_anchors_a_span_spacy_did_not_call_a_person():
    assert normalize_surface("Congrats Caroline", "NOUN_CHUNK", {"Caroline"}) == "Caroline"
    assert normalize_surface("Congrats Caroline", "NOUN_CHUNK") == "Congrats Caroline"


def test_normalize_entities_keeps_the_span_and_drops_repeats():
    ents = [{"text": "Congrats Caroline", "label": "PERSON"}, {"text": "Caroline!", "label": "PERSON"},
            {"text": "pottery class", "label": "NOUN_CHUNK"}]
    out = normalize_entities(ents)
    assert [e["text"] for e in out] == ["Caroline", "pottery class"]
    assert out[0]["surface"] == "Congrats Caroline"


@pytest.mark.parametrize("speaker, named", [
    ("Caroline", True), ("Dr. Ortiz", True), ("user", False), ("assistant", False),
    ("Speaker 1", False), ("speaker2", False), ("", False), (None, False), ("1234", False),
])
def test_is_named_speaker(speaker, named):
    assert orch._is_named_speaker(speaker) is named


# --- the graph -----------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(orch.emb, "embed", lambda text, model_name=None: list(VEC))
    return OxigraphClient(tmp_path / "b472p2.db")


def _concepts(db) -> dict:
    rows = db._execute_and_collect(
        "SELECT ?id ?t ?g ?s WHERE { ?c a <https://campy.dev/ns#Concept> ; <https://campy.dev/ns#concept_id> ?id ;"
        " <https://campy.dev/ns#text_raw> ?t . OPTIONAL { ?c <https://campy.dev/ns#gist_class> ?g }"
        " OPTIONAL { ?c <https://campy.dev/ns#schema_org_type> ?s } }")
    return {r["id"]: (r["t"], r.get("g"), r.get("s")) for r in rows}


async def _store(db, text: str) -> str:
    return await orch._store_concept({"text": text}, STEP4, list(VEC), "m", db, NOW)


@pytest.mark.asyncio
async def test_a_named_speaker_is_seeded_once_as_a_person(db):
    a = await orch._seed_speaker_concept("Caroline", "m", db, NOW)
    b = await orch._seed_speaker_concept("Caroline", "m", db, NOW)
    assert a and a == b
    assert _concepts(db) == {a: ("Caroline", "Agent", "Person")}
    # later mentions of the name resolve to the seeded Person
    assert await _store(db, "caroline") == a


@pytest.mark.asyncio
async def test_a_reworded_merge_becomes_an_alternative_label_once(db):
    cid = await _store(db, "PostgreSQL")
    top = {"concept_id": cid, "text_raw": "PostgreSQL"}
    summary: dict = {}
    await orch._attach_alt_label(top, "Postgres", VEC, db, NOW, summary)
    await orch._attach_alt_label(top, "postgres", VEC, db, NOW, summary)  # same wording, any case
    await orch._attach_alt_label(top, "PostgreSQL", VEC, db, NOW, summary)  # the canonical name itself
    assert summary == {"alt_labels_added": 1}
    gw = GraphGateway(db, REGISTRY)
    assert gw.run_sync("temporal_lobe.dict_find_alt_label", cid=cid, txt="Postgres")
    # and the next "Postgres" resolves to PostgreSQL, not a new Concept
    assert await _store(db, "Postgres") == cid
    assert len(_concepts(db)) == 1


@pytest.mark.asyncio
async def test_two_people_who_share_a_first_name_stay_two(db):
    lee = await _store(db, "Sam Lee")
    park = await _store(db, "Sam Park")
    assert lee != park
    assert await _store(db, "Sam Lee") == lee


# --- the Loop ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_loop_classifies_one_normalized_entity_for_three_spans(monkeypatch):
    spans = [{"text": "Congrats Caroline", "label": "PERSON", "start": 0, "end": 17},
             {"text": "Caroline!", "label": "PERSON", "start": 20, "end": 29},
             {"text": "Wow Caroline", "label": "PERSON", "start": 30, "end": 42}]
    monkeypatch.setattr(orch, "extract_entities", lambda text, model_name=None: (None, [dict(s) for s in spans]))
    monkeypatch.setattr(orch, "extract_relations", lambda doc, entities: [])
    seen = []

    def classify(text, *a, **k):
        seen.append(text)
        return {"system": "noise", "gist_class": None, "confidence": 0.0}

    monkeypatch.setattr(orch, "classify_concept", classify)
    seeded = AsyncMock(return_value="c1")
    monkeypatch.setattr(orch, "_seed_speaker_concept", seeded)
    summary = await orch.run_loop("m1", "Congrats Caroline! Caroline! Wow Caroline", None, None, {}, {},
                                  speaker="Melanie")
    assert summary["entities_found"] == 1
    assert seen == ["Caroline"]
    seeded.assert_awaited_once()
    assert seeded.await_args.args[0] == "Melanie"


@pytest.mark.asyncio
async def test_run_loop_does_not_seed_a_role_or_placeholder(monkeypatch):
    monkeypatch.setattr(orch, "extract_entities", lambda text, model_name=None: (None, []))
    seeded = AsyncMock()
    monkeypatch.setattr(orch, "_seed_speaker_concept", seeded)
    for speaker in (None, "user", "Speaker 1"):
        await orch.run_loop("m1", "hello", None, None, {}, {}, speaker=speaker)
    seeded.assert_not_awaited()


# --- the Loop worker's queue ---------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_worker_accepts_every_producer_shape_and_survives_a_bad_item(monkeypatch):
    import campy.brain_daemon as brain_daemon_mod
    from campy.brain_daemon import BrainDaemon

    fake_self = SimpleNamespace(db=object(), _llm_client=object(), config={}, _centroids={},
                                _loop_queue=asyncio.Queue())
    run_loop_mock = AsyncMock(return_value={"entities_found": 0, "concepts_stored": 0,
                                            "relations_found": 0, "noise_count": 0})
    monkeypatch.setattr(brain_daemon_mod, "run_loop", run_loop_mock)
    q = fake_self._loop_queue
    await q.put(("extract-1", "a document chunk", "user", "unknown"))              # ingest_document (old shape)
    await q.put(("m-5", "turn", "user", "s1", None))                                # B434 shape
    await q.put(("m-6", "turn", "user", "s1", None, "Caroline"))                    # notify_turn (B472)
    await q.put(("bad",))                                                           # malformed
    await q.put(("m-after", "turn", "user", "s1", None, None))                      # still processed
    worker = asyncio.create_task(BrainDaemon._loop_worker(fake_self))
    try:
        await asyncio.wait_for(q.join(), timeout=2.0)
    finally:
        worker.cancel()
    calls = {c.kwargs["message_id"]: c.kwargs for c in run_loop_mock.await_args_list}
    assert set(calls) == {"extract-1", "m-5", "m-6", "m-after"}
    assert calls["m-6"]["speaker"] == "Caroline"
    # no speaker: not passed, so run_loop stand-ins without the parameter still work
    assert "speaker" not in calls["extract-1"] and calls["extract-1"]["precomputed"] is None
