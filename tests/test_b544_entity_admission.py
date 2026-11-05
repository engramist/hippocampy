"""B544: entity admission. Real Oxigraph store and real spaCy, no model, no LLM.

Pins:
- flag: off by default (key-less config reads as off), env CAMPY_ENTITY_ADMISSION, in the
  packaged campy.toml;
- flag off: the Loop stores nothing for a turn whose entities step 2 drops (D6:8 text);
- flag on: "The Name of the Wind", "Nike", "Barcelona" are Concepts with their NER label and
  the turn MENTIONS them, whether step 2 or step 4 would have dropped them;
- no duplicate Concepts (admitted twice, and the steps 4-7 path finds the admitted one);
- a label outside the closed set (DATE, CARDINAL) admits nothing; assistant turns admit nothing;
- the kind guard: a named entity or a Person never becomes a kind, flag or no flag.
"""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import entity_admission as ea
from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.observations import entities as obs_entities

pytestmark = pytest.mark.asyncio

DIM = 384
T0 = datetime(2023, 8, 11, 12, 0, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
D6_8 = ('Thanks! "The Name of the Wind" is great. It\'s a fantasy novel with a great magician and '
        "musician protagonist. The world-building and character development are really good. "
        "Definitely worth a read if you're looking for something captivating!")
ON = {"loop": {"entity_admission": True}, "retrieval": {"graph_linking": False}}
OFF = {"loop": {"entity_admission": False}, "retrieval": {"graph_linking": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    # a distinct vector per text so step 5 never merges two different entities
    def fake(text, model_name=None):
        v = [0.0] * DIM
        v[hash(text.lower()) % DIM] = 1.0
        return v
    monkeypatch.setattr(embeddings_mod, "embed", fake)
    monkeypatch.setattr(orch.emb, "embed", fake)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b544.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def _step2_noise(monkeypatch):
    monkeypatch.setattr(orch, "classify_concept",
                        lambda *a, **k: {"system": "noise", "gist_class": None, "confidence": 0.1, "vector": None})


async def _message(gw, mid, text, role="user"):
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text),
                 created_at=T0.isoformat())


async def _loop(db, mid, text, config, role="user"):
    return await orch.run_loop(mid, text, db, None, config, {}, role=role, speaker=None)


def _concepts(db):
    rows = db._execute_and_collect(
        f"SELECT ?t ?l WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> ?t . OPTIONAL {{ ?c {NS}ner_label> ?l }} }}")
    return sorted((str(r["t"]), str(r["l"]) if r.get("l") else None) for r in rows)


def _mentions(db, mid):
    rows = db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?m {NS}message_id> \"{mid}\" ; {NS}MENTIONS> ?c . ?c {NS}text_raw> ?t }}")
    return sorted(str(r["t"]) for r in rows)


# --- the flag ---------------------------------------------------------------------------

async def test_flag_off_by_default_and_keyless():
    assert ea.entity_admission_enabled(_DEFAULT_CONFIG) is False
    assert ea.entity_admission_enabled({}) is False
    assert ea.entity_admission_enabled({"loop": {}}) is False


async def test_flag_env_override_and_packaged_toml():
    cfg = apply_env_overrides({"loop": {}}, {"CAMPY_ENTITY_ADMISSION": "1"})
    assert ea.entity_admission_enabled(cfg) is True
    cfg = apply_env_overrides({"loop": {"entity_admission": True}}, {"CAMPY_ENTITY_ADMISSION": "0"})
    assert ea.entity_admission_enabled(cfg) is False
    packaged = tomllib.loads((Path(orch.__file__).parents[3] / "data/config/campy.toml").read_text())
    # B545: the template leaves profile members unset, so profile "principled" can turn it on
    assert "entity_admission" not in packaged.get("loop", {})


def test_profile_principled_turns_admission_on_and_env_still_wins(tmp_path, monkeypatch):
    from campy.brain.brainstem.config import load_config
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "ollama"\n')
    monkeypatch.setenv("CAMPY_PROFILE", "principled")
    monkeypatch.delenv("CAMPY_ENTITY_ADMISSION", raising=False)
    assert ea.entity_admission_enabled(load_config(path)) is True
    monkeypatch.setenv("CAMPY_ENTITY_ADMISSION", "0")
    assert ea.entity_admission_enabled(load_config(path)) is False


# --- the Loop ---------------------------------------------------------------------------

async def test_flag_off_stores_no_concept_for_the_dropped_title(db, gw, monkeypatch):
    _step2_noise(monkeypatch)
    await _message(gw, "m1", D6_8)
    summary = await _loop(db, "m1", D6_8, OFF)
    assert _concepts(db) == []
    assert _mentions(db, "m1") == []
    assert "entities_admitted" not in summary


async def test_flag_on_admits_title_even_when_step2_drops_it(db, gw, monkeypatch):
    _step2_noise(monkeypatch)
    await _message(gw, "m1", D6_8)
    summary = await _loop(db, "m1", D6_8, ON)
    assert ("The Name of the Wind", "WORK_OF_ART") in _concepts(db)
    assert "The Name of the Wind" in _mentions(db, "m1")
    assert summary["entities_admitted"] >= 1


async def test_flag_on_admits_org_and_place_when_step4_drops_them(db, gw):
    text = "I just signed a deal with Nike and I am moving to Barcelona next month."
    await _message(gw, "m2", text)
    await _loop(db, "m2", text, ON)
    got = dict(_concepts(db))
    assert got.get("Nike") == "ORG"
    assert got.get("Barcelona") == "GPE"
    assert {"Nike", "Barcelona"} <= set(_mentions(db, "m2"))


async def test_no_duplicate_concepts(db, gw):
    text = "I just signed a deal with Nike and I am moving to Barcelona next month."
    for mid in ("a", "b"):
        await _message(gw, mid, text)
        await _loop(db, mid, text, ON)
    names = [t.lower() for t, _ in _concepts(db)]
    assert len(names) == len(set(names))
    assert _mentions(db, "a") == _mentions(db, "b")


async def test_existing_concept_is_reused_and_labelled(db, gw):
    await gw.run("temporal_lobe.dict_create_concept", cid="c-nike", text="Nike", emb=[0.0] * DIM,
                 gist="Entity", stype="Thing", now=T0)
    await _message(gw, "m3", "My new shoes are from Nike.")
    await _loop(db, "m3", "My new shoes are from Nike.", ON)
    assert [t for t, _ in _concepts(db)].count("Nike") == 1
    assert dict(_concepts(db))["Nike"] == "ORG"


async def test_labels_outside_the_closed_set_admit_nothing(db, gw):
    text = "We met on March 3rd and walked for two hours."
    await _message(gw, "m4", text)
    summary = await _loop(db, "m4", text, ON)
    assert _concepts(db) == []
    assert summary["entities_admitted"] == 0


async def test_assistant_turn_admits_nothing(db, gw):
    text = "You should visit Barcelona and see the Sagrada Familia."
    await _message(gw, "m5", text, role="assistant")
    summary = await _loop(db, "m5", text, ON, role="assistant")
    assert "entities_admitted" not in summary
    assert "Barcelona" not in dict(_concepts(db))


async def test_admission_writes_no_kind(db, gw):
    text = "I just signed a deal with Nike and I am moving to Barcelona next month."
    await _message(gw, "m6", text)
    await _loop(db, "m6", text, ON)
    assert db._execute_and_collect(f"SELECT ?c WHERE {{ ?c {NS}INSTANCE_OF> ?k }}") == []
    assert db._execute_and_collect(f"SELECT ?c WHERE {{ ?c {NS}kind_scheme> ?k }}") == []


# --- the kind guard (independent of the flag) -------------------------------------------

async def _concept(gw, cid, text, stype="Thing"):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=[0.0] * DIM,
                 gist="Entity", stype=stype, now=T0)


async def test_guard_named_entity_is_never_a_kind(gw):
    await _concept(gw, "tim", "Tim")
    await gw.run("entity_admission.set_ner_label", cid="tim", label="PERSON")
    assert await kinds_mod.mark_kind(gw, "tim") is False
    assert await gw.run("kinds.live_kinds") == []


async def test_guard_person_typed_concept_is_never_a_kind(gw):
    await _concept(gw, "ann", "Ann", stype="Person")
    assert await kinds_mod.mark_kind(gw, "ann") is False
    assert await gw.run("kinds.live_kinds") == []


async def test_guard_plain_concept_can_still_be_a_kind(gw):
    await _concept(gw, "mk", "model kit", stype="DefinedTerm")
    assert await kinds_mod.mark_kind(gw, "mk") is True
    assert [r["concept_id"] for r in await gw.run("kinds.live_kinds")] == ["mk"]


class _Stats:
    def __getattr__(self, name):
        return 0

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


async def test_guard_resolve_kind_refuses_a_person_name(gw):
    await _concept(gw, "tim", "Tim")
    await gw.run("entity_admission.set_ner_label", cid="tim", label="PERSON")
    index = {"tim": ["tim"]}
    kid = await obs_entities.resolve_kind(gw, "Tim", index, _Stats(), embedding_model="m")
    assert kid is None
    assert await gw.run("kinds.live_kinds") == []


async def test_named_entities_query_reads_what_admission_wrote(db, gw):
    text = "I just signed a deal with Nike and I am moving to Barcelona next month."
    await _message(gw, "m7", text)
    await _loop(db, "m7", text, ON)
    rows = await gw.run("entity_admission.named_entities")
    assert {(r["text_raw"], r["ner_label"]) for r in rows} >= {("Nike", "ORG"), ("Barcelona", "GPE")}


# --- extraction-time resolution (order independent) --------------------------------------

import json
from campy.brain.temporal_lobe.observations import extract as ex

XCFG_ON = {"loop": {"entity_admission": True}, "retrieval": {"graph_linking": True},
           "observations": {"enabled": True, "llm_enabled": True}}
XCFG_OFF = {"loop": {"entity_admission": False}, "retrieval": {"graph_linking": True},
            "observations": {"enabled": True, "llm_enabled": True}}


class _LLM:
    def __init__(self):
        self.reply = json.dumps([{
            "subject": "I", "predicate": "did", "object": "read The Name of the Wind", "time": None,
            "polarity": "asserted", "quote": '"The Name of the Wind" is great', "confidence": 0.9}])

    def chat(self, messages, **kwargs):
        return self.reply


async def _extract(db, gw, cfg, mid="x1"):
    await _message(gw, mid, D6_8)
    await gw.run("capture.set_message_source", message_id=mid, speaker="Tim",
                 occurred_at=T0.isoformat())
    st = ex.ObservationWorkerStats()
    n = await ex.process_turn(db, cfg, _LLM(), mid, st)
    return n


def _about(db):
    rows = db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?o a {NS}Observation> ; {NS}OBSERVATION_ABOUT> ?c . ?c {NS}text_raw> ?t }}")
    return {str(r["t"]) for r in rows}


async def test_extractor_links_to_title_when_run_loop_never_ran(db, gw):
    assert await _extract(db, gw, XCFG_ON) == 1
    assert "The Name of the Wind" in _about(db)
    assert dict(_concepts(db))["The Name of the Wind"] == "WORK_OF_ART"


async def test_extractor_links_to_title_when_run_loop_ran_first_without_duplicates(db, gw, monkeypatch):
    _step2_noise(monkeypatch)
    await _message(gw, "x1", D6_8)
    await _loop(db, "x1", D6_8, ON)
    await gw.run("capture.set_message_source", message_id="x1", speaker="Tim", occurred_at=T0.isoformat())
    created = await ex.process_turn(db, XCFG_ON, _LLM(), "x1", ex.ObservationWorkerStats())
    assert created == 1 and "The Name of the Wind" in _about(db)
    names = [t.lower() for t, _ in _concepts(db)]
    assert len(names) == len(set(names))


async def test_extractor_flag_off_unchanged(db, gw):
    assert await _extract(db, gw, XCFG_OFF) == 1
    assert "The Name of the Wind" not in _about(db)
    assert "The Name of the Wind" not in dict(_concepts(db))


async def test_names_in_is_whole_word():
    assert ea.names_in("Art", "I am an artist") is False
    assert ea.names_in("Nike", "signed with Nike's team") is True
    assert ea.names_in("The Name of the Wind", "read the name of the wind") is True
