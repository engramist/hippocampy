"""Tests for Entity-Resolved Typed Capture (`[observations] entity_resolved_capture`)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, PROFILES, apply_env_overrides
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import entity_resolved as er
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
VEC = [1.0] + [0.0] * (DIM - 1)
NS = "<https://campy.dev/ns#"
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: VEC)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "entity_resolved.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class MockLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple[list[dict], dict]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.reply


def _edges(db: OxigraphClient, edge: str) -> set[tuple[str, str]]:
    rows = db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
    return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}


async def _seed_message(
    gw: GraphGateway,
    mid: str,
    text: str,
    *,
    speaker: str = "Caroline",
    day: int = 7,
    role: str = "user",
) -> str:
    stamp = f"2023-05-{day:02d}T12:00:00+00:00"
    await gw.run(
        "capture.create_message",
        message_id=mid,
        text_raw=text,
        embedding=None,
        embedding_model="m",
        embedding_dim=DIM,
        role=role,
        byte_end=len(text),
        created_at=stamp,
    )
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
    return mid


async def _seed_person(gw: GraphGateway, cid: str, name: str) -> str:
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid,
        text=name,
        emb=VEC,
        gist="Agent",
        stype="Person",
        now=T0,
    )
    return cid


# ---------------------------------------------------------------------------
# 1. Config flag, env override, and profile isolation
# ---------------------------------------------------------------------------

def test_config_default_env_override_and_absent_from_profiles():
    assert _DEFAULT_CONFIG["observations"]["entity_resolved_capture"] is False
    assert er.entity_resolved_capture_enabled(None) is False
    assert er.entity_resolved_capture_enabled({}) is False
    assert er.entity_resolved_capture_enabled(_DEFAULT_CONFIG) is False

    overridden = apply_env_overrides({}, {"CAMPY_ENTITY_RESOLVED_CAPTURE": "1"})
    assert overridden["observations"]["entity_resolved_capture"] is True
    assert er.entity_resolved_capture_enabled(overridden) is True

    disabled = apply_env_overrides(
        {"observations": {"entity_resolved_capture": True}},
        {"CAMPY_ENTITY_RESOLVED_CAPTURE": "0"},
    )
    assert disabled["observations"]["entity_resolved_capture"] is False
    assert er.entity_resolved_capture_enabled(disabled) is False

    for profile_name, profile_table in PROFILES.items():
        obs_table = profile_table.get("observations") or {}
        assert "entity_resolved_capture" not in obs_table, profile_name


# ---------------------------------------------------------------------------
# 2. Image caption stripping
# ---------------------------------------------------------------------------

def test_strip_image_captions_preserves_surrounding_prose():
    raw = "Hey! [shares an image: a golden retriever in a park] I adopted Buddy yesterday."
    assert er.strip_image_captions(raw) == "Hey! I adopted Buddy yesterday."

    leading = "[shares an image: sunset over mountains] That hike was unforgettable."
    assert er.strip_image_captions(leading) == "That hike was unforgettable."

    comma = "Look at this [SHARES AN IMAGE: oil painting], I painted it last week."
    assert er.strip_image_captions(comma) == "Look at this, I painted it last week."

    plain = "No captions here; just normal prose!"
    assert er.strip_image_captions(plain) == plain


# ---------------------------------------------------------------------------
# 3. Prompt builder: 3-turn coreference window & closed entity list
# ---------------------------------------------------------------------------

def test_build_entity_resolved_prompt_includes_window_and_closed_entities():
    recent = [
        ("Caroline", "Earlier turn 0 (should be trimmed)."),
        ("Melanie", "How is your dog doing?"),
        ("Caroline", "He was energetic this morning [shares an image: dog running]."),
        ("Melanie", "What did he chew on?"),
    ]
    prompt = er.build_entity_resolved_prompt(
        "Caroline",
        "He loves the red ball! [shares an image: red ball]",
        recent_turns=recent,
        known_entities=["Caroline", "Melanie", "Buddy (dog)"],
        occurred_at="2023-05-07",
    )
    assert "Earlier turn 0" not in prompt
    assert "- [Melanie]: How is your dog doing?" in prompt
    assert "- [Caroline]: He was energetic this morning." in prompt
    assert "- [Melanie]: What did he chew on?" in prompt
    assert "Caroline, Melanie, Buddy (dog)" in prompt
    assert "Speaker: Caroline" in prompt
    assert "Date: 2023-05-07" in prompt
    assert 'Message: """He loves the red ball!"""' in prompt
    assert "[shares an image:" not in prompt


# ---------------------------------------------------------------------------
# 4. Response parsing
# ---------------------------------------------------------------------------

def test_parse_entity_resolved_response_handles_clean_fenced_cut_and_malformed():
    clean = json.dumps([
        {
            "subject_entity": "I",
            "predicate": "owns",
            "object_entity": "Buddy",
            "object_kind": "dog",
            "object_text": "Buddy",
            "quote": "I adopted Buddy",
            "confidence": 0.95,
        }
    ])
    assert len(er.parse_entity_resolved_response(clean)) == 1

    fenced = f"```json\n{clean}\n```"
    assert len(er.parse_entity_resolved_response(fenced)) == 1

    cut = '[{"subject_entity": "I", "predicate": "did", "object_text": "ran", "quote": "I ran"}, {"subject_entity": "I"'
    salvaged = er.parse_entity_resolved_response(cut)
    assert len(salvaged) == 1
    assert salvaged[0]["object_text"] == "ran"

    assert er.parse_entity_resolved_response("Sorry, I cannot comply.") == []
    assert er.parse_entity_resolved_response("{not valid json") == []
    assert er.parse_entity_resolved_response("[1, 2, 3]") == []
    assert er.parse_entity_resolved_response("") == []


# ---------------------------------------------------------------------------
# 5. Subject grounding (P8)
# ---------------------------------------------------------------------------

def test_ground_subject_entity_speaker_first_person_and_rejects_non_person():
    persons = {"Caroline": "c-car", "Melanie": "c-mel", "Mel": "c-mel"}

    # subject == speaker sets is_first_person=True even with no literal "I" or speaker name in turn
    cid, is_fp = er.ground_subject_entity("Caroline", "Caroline", "Finished the painting yesterday!", persons)
    assert (cid, is_fp) == ("c-car", True)

    # Case-insensitive speaker match
    cid, is_fp = er.ground_subject_entity("caroline", "Caroline", "Adopted a puppy!", persons)
    assert (cid, is_fp) == ("c-car", True)

    # Literal first-person pronoun
    cid, is_fp = er.ground_subject_entity("I", "Caroline", "I love pottery.", persons)
    assert (cid, is_fp) == ("c-car", True)

    # Known third-person via coreference pronoun or alias in turn
    assert er.ground_subject_entity("Melanie", "Caroline", "She went to Denver.", persons) == ("c-mel", False)
    assert er.ground_subject_entity("Melanie", "Caroline", "Mel loves pottery.", persons) == ("c-mel", False)

    # Ungrounded non-person subjects are rejected
    assert er.ground_subject_entity("painting", "Caroline", "That painting is awesome.", persons) == (None, False)
    assert er.ground_subject_entity("life", "Caroline", "Life is unpredictable.", persons) == (None, False)
    assert er.ground_subject_entity("UnknownPerson", "Caroline", "UnknownPerson arrived.", persons) == (None, False)
    # Cross-turn bleed: known person neither named nor coreferenced in target turn
    assert er.ground_subject_entity("Melanie", "Caroline", "I like cats.", persons) == (None, False)


# ---------------------------------------------------------------------------
# 6. End-to-end against temp OxigraphClient + MockLLM
# ---------------------------------------------------------------------------

async def test_extract_entity_resolved_observations_noop_when_flag_off(db, gw):
    await _seed_person(gw, "c-car", "Caroline")
    mid = await _seed_message(gw, "m1", "I adopted Buddy yesterday.", speaker="Caroline")
    llm = MockLLM(json.dumps([
        {
            "subject_entity": "I",
            "predicate": "owns",
            "object_entity": "Buddy",
            "object_kind": "dog",
            "object_text": "Buddy",
            "time": "yesterday",
            "polarity": "asserted",
            "quote": "I adopted Buddy yesterday",
            "confidence": 0.95,
        }
    ]))

    created = await er.extract_entity_resolved_observations(
        db,
        llm,
        message_id=mid,
        speaker="Caroline",
        speaker_id="c-car",
        text="I adopted Buddy yesterday.",
        config={"observations": {"entity_resolved_capture": False}},
    )
    assert created == 0
    assert llm.calls == []
    assert await gw.run("observations.for_message", mid=mid) == []


async def test_extract_entity_resolved_observations_end_to_end(db, gw):
    await _seed_person(gw, "c-car", "Caroline")
    await _seed_person(gw, "c-mel", "Melanie")
    # Seed a broader kind "animal" so "dog" -> BROADER -> "animal" is tested too
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid="k-animal",
        text="animal",
        emb=VEC,
        gist="Category",
        stype="Thing",
        now=T0,
    )
    await gw.run("kinds.mark_kind", cid="k-animal", scheme="kind")
    # Seed a kind "pet dog" to verify narrower->broader linking or keep "dog" clean
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid="k-pet-dog",
        text="pet dog",
        emb=VEC,
        gist="Category",
        stype="Thing",
        now=T0,
    )
    await gw.run("kinds.mark_kind", cid="k-pet-dog", scheme="kind")

    m0 = await _seed_message(gw, "m0", "Did you get a pet?", speaker="Melanie", day=6)
    turn_text = "Adopted Buddy yesterday! [shares an image: a happy puppy] That painting is cool."
    m1 = await _seed_message(gw, "m1", turn_text, speaker="Caroline", day=7)
    await gw.run("capture.merge_followed_by", prev=m0, curr=m1, gap=60)

    llm_reply = json.dumps([
        # Third-person speaker reference on a turn with no literal "I" -> P8 grounds to speaker!
        {
            "subject_entity": "Caroline",
            "predicate": "owns",
            "object_entity": "Buddy",
            "object_kind": "dog",
            "object_text": "Buddy",
            "time": "yesterday",
            "polarity": "asserted",
            "quote": "Adopted Buddy yesterday!",
            "confidence": 0.95,
        },
        # Ungrounded non-person subject -> must be rejected!
        {
            "subject_entity": "painting",
            "predicate": "has_attribute",
            "object_entity": None,
            "object_kind": None,
            "object_text": "quality: cool",
            "time": None,
            "polarity": "asserted",
            "quote": "That painting is cool.",
            "confidence": 0.9,
        },
    ])
    llm = MockLLM(llm_reply)

    cfg = {"observations": {"entity_resolved_capture": True, "shacl_gate": True}}
    created = await er.extract_entity_resolved_observations(
        db,
        llm,
        message_id=m1,
        speaker="Caroline",
        speaker_id="c-car",
        text=turn_text,
        config=cfg,
    )
    assert created == 1
    assert len(llm.calls) == 1
    sent_messages, sent_kwargs = llm.calls[0]
    assert sent_kwargs.get("num_ctx") == 4096
    assert sent_kwargs.get("think") is False
    assert "Did you get a pet?" in sent_messages[1]["content"]
    assert "[shares an image:" not in sent_messages[1]["content"]

    obs_rows = await gw.run("observations.for_message", mid=m1)
    assert len(obs_rows) == 1
    row = obs_rows[0]
    oid = row["observation_id"]
    assert row["subject_id"] == "c-car"
    assert row["subject_text"] == "I"
    assert row["predicate"] == "owns"
    assert row["object_text"] == "Buddy"
    assert row["object_id"] is not None
    buddy_cid = row["object_id"]

    # Verify HAS_SUBJECT, HAS_OBJECT -> Concept, EVIDENCED_BY, MENTIONS, INSTANCE_OF, BROADER
    assert (oid, "c-car") in _edges(db, "HAS_SUBJECT")
    assert (oid, buddy_cid) in _edges(db, "HAS_OBJECT")
    assert (oid, m1) in _edges(db, "EVIDENCED_BY")
    assert (m1, buddy_cid) in _edges(db, "MENTIONS")

    inst_edges = _edges(db, "INSTANCE_OF")
    dog_kids = [k for e, k in inst_edges if e == buddy_cid]
    assert len(dog_kids) == 1
    assert ("k-pet-dog", dog_kids[0]) in _edges(db, "BROADER")


async def test_extract_process_turn_routes_when_enabled(db, gw):
    await _seed_person(gw, "c-car", "Caroline")
    mid = await _seed_message(gw, "m1", "I live in Denver now.", speaker="Caroline", day=7)
    llm = MockLLM(json.dumps([
        {
            "subject_entity": "I",
            "predicate": "located_in",
            "object_entity": "Denver",
            "object_kind": "city",
            "object_text": "Denver",
            "time": None,
            "polarity": "asserted",
            "quote": "I live in Denver now",
            "confidence": 0.92,
        }
    ]))
    stats = ex.ObservationWorkerStats()
    created = await ex.process_turn(
        db,
        {"observations": {"enabled": True, "llm_enabled": True, "entity_resolved_capture": True}},
        llm,
        mid,
        stats,
    )
    assert created == 1
    assert stats.created == 1
    assert llm.calls[0][1].get("num_ctx") == 4096
    assert llm.calls[0][1].get("think") is False
    rows = await gw.run("observations.for_message", mid=mid)
    assert len(rows) == 1
    assert rows[0]["object_text"] == "Denver"
    assert rows[0]["object_id"] is not None
