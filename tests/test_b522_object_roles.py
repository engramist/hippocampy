"""B522: each Observation records its subject and object Concepts as typed edges.

Real Oxigraph store, fake LLM, no model. Pins:
- the flag `[observations] object_roles` (default off; env CAMPY_OBSERVATIONS_OBJECT_ROLES);
- flag off writes no HAS_SUBJECT / HAS_OBJECT and no object_id; flag on writes them from the draft
  and from the entity write_entity resolves, filling an empty object_id;
- HAS_SUBJECT / HAS_OBJECT hold at most one Concept (first wins), writes are idempotent,
  an object equal to the subject is not an object;
- the backfill rule (object_id, else exactly one non-subject non-kind OBSERVATION_ABOUT Concept whose
  label appears in object_text; several fitting Concepts are skipped and counted);
- the reader `observations.objects_of_subject` (kinds via INSTANCE_OF + BROADER*, predicate filter,
  evidence message) and the report helpers that run the same NamedQuery on a read-only store.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import backfill as bf
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
NS = "<https://campy.dev/ns#"
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False,
                         "entities": True},
        "retrieval": {"conversation_token_budget": 0}}
ROLES = {**BASE, "observations": {**BASE["observations"], "object_roles": True}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b522.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def edges(db, edge):
    rows = db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
    return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}


async def message(gw, mid, text, day=3, speaker="Andrew"):
    stamp = f"2023-05-{day:02d}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
    return mid


async def concept(gw, cid, text):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing", now=T0)
    return cid


async def record(db, gw, mid, quote, *, subject_id=None, object_id=None, object_text="x", predicate="owns",
                 config=None, subject_text="Andrew", about=()):
    await message(gw, mid, quote)
    res = await obs.record_observation(
        db, obs.ObservationDraft(evidence_ref=mid, evidence_text=quote, subject_text=subject_text,
                                 predicate=predicate, object_text=object_text, extraction_method="pattern",
                                 confidence=0.8, rule_version="pattern-1", subject_id=subject_id,
                                 object_id=object_id),
        config=config or {})
    assert res.ok, res
    for cid in about:
        await gw.run("observations.link_about_concept", oid=res.observation_id, cid=cid)
    return res.observation_id


async def literal(gw, oid, col):
    rows = await gw.run("observations.get_observation", oid=oid)
    return dict(rows[0]).get(col)


# --- the flag -------------------------------------------------------------------------

def test_flag_default_off_env_on():
    assert _DEFAULT_CONFIG["observations"]["object_roles"] is False
    assert obs.object_roles_enabled({}) is False
    assert obs.object_roles_enabled(_DEFAULT_CONFIG) is False
    assert obs.object_roles_enabled(apply_env_overrides({}, {"CAMPY_OBSERVATIONS_OBJECT_ROLES": "1"})) is True
    assert obs.object_roles_enabled(
        apply_env_overrides({"observations": {"object_roles": True}}, {"CAMPY_OBSERVATIONS_OBJECT_ROLES": "0"})) is False


def test_shipped_toml_declares_the_flag_off():
    import tomllib

    path = Path(__file__).resolve().parents[1] / "campy" / "data" / "config" / "campy.toml"
    assert tomllib.loads(path.read_text())["observations"]["object_roles"] is False


# --- writes ---------------------------------------------------------------------------

async def test_flag_off_writes_no_roles(db, gw):
    await concept(gw, "c-andrew", "Andrew")
    await concept(gw, "c-toby", "Toby")
    oid = await record(db, gw, "m1", "Andrew owns Toby.", subject_id="c-andrew", object_id="c-toby",
                       object_text="Toby", config=BASE)
    assert edges(db, "HAS_SUBJECT") == edges(db, "HAS_OBJECT") == set()
    assert {c for _, c in edges(db, "OBSERVATION_ABOUT")} == {"c-andrew", "c-toby"}
    assert await literal(gw, oid, "object_id") == "c-toby"


async def test_flag_on_writes_subject_and_object_from_the_draft(db, gw):
    await concept(gw, "c-andrew", "Andrew")
    await concept(gw, "c-toby", "Toby")
    oid = await record(db, gw, "m1", "Andrew owns Toby.", subject_id="c-andrew", object_id="c-toby",
                       object_text="Toby", config=ROLES)
    assert edges(db, "HAS_SUBJECT") == {(oid, "c-andrew")}
    assert edges(db, "HAS_OBJECT") == {(oid, "c-toby")}
    assert {c for _, c in edges(db, "OBSERVATION_ABOUT")} == {"c-andrew", "c-toby"}     # unchanged


async def test_flag_on_without_known_concepts_writes_nothing(db, gw):
    await record(db, gw, "m1", "Andrew owns a couch.", object_text="a couch", config=ROLES)
    assert edges(db, "HAS_SUBJECT") == edges(db, "HAS_OBJECT") == set()


async def test_duplicate_draft_keeps_one_edge_each(db, gw):
    await concept(gw, "c-andrew", "Andrew")
    await concept(gw, "c-toby", "Toby")
    await message(gw, "m1", "Andrew owns Toby.")
    draft = obs.ObservationDraft(evidence_ref="m1", evidence_text="Andrew owns Toby.", subject_text="Andrew",
                                 predicate="owns", object_text="Toby", extraction_method="pattern",
                                 confidence=0.8, rule_version="pattern-1", subject_id="c-andrew",
                                 object_id="c-toby")
    first = await obs.record_observation(db, draft, config=ROLES)
    second = await obs.record_observation(db, draft, config=ROLES)
    assert second.status == "duplicate" and second.observation_id == first.observation_id
    assert len(edges(db, "HAS_SUBJECT")) == len(edges(db, "HAS_OBJECT")) == 1


async def test_at_most_one_subject_and_one_object_first_wins(db, gw):
    for cid, text in (("c-a", "Andrew"), ("c-b", "Buddy"), ("c-t", "Toby"), ("c-s", "Sam")):
        await concept(gw, cid, text)
    oid = await record(db, gw, "m1", "Andrew owns Toby.", object_text="Toby")
    for _ in range(2):                                   # idempotent
        await obs.write_roles(gw, oid, subject_id="c-a", object_id="c-t")
    await obs.write_roles(gw, oid, subject_id="c-s", object_id="c-b")        # a second, different pair
    assert edges(db, "HAS_SUBJECT") == {(oid, "c-a")}
    assert edges(db, "HAS_OBJECT") == {(oid, "c-t")}
    assert await literal(gw, oid, "object_id") == "c-t"


async def test_object_equal_to_subject_is_not_an_object(db, gw):
    await concept(gw, "c-a", "Andrew")
    oid = await record(db, gw, "m1", "Andrew owns Andrew.", object_text="Andrew")
    await obs.write_roles(gw, oid, subject_id="c-a", object_id="c-a")
    assert edges(db, "HAS_SUBJECT") == {(oid, "c-a")} and edges(db, "HAS_OBJECT") == set()


async def test_existing_object_id_is_not_overwritten(db, gw):
    await concept(gw, "c-a", "Andrew")
    await concept(gw, "c-t", "Toby")
    await concept(gw, "c-b", "Buddy")
    oid = await record(db, gw, "m1", "Andrew owns Toby.", subject_id="c-a", object_id="c-t", object_text="Toby")
    await gw.run("observations.link_object", oid=oid, cid="c-b")     # an object edge that disagrees
    await gw.run("observations.set_object_id_from_role", oid=oid)
    assert await literal(gw, oid, "object_id") == "c-t"


# --- the extraction path: the entity write_entity resolves ----------------------------

class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))

    def chat(self, messages, **kwargs):
        return self.reply


def claim(quote, obj, *, entity, subject="I", predicate="owns"):
    return {"subject": subject, "predicate": predicate, "object": obj, "time": None, "polarity": "asserted",
            "quote": quote, "confidence": 0.9, "object_entity": entity, "object_kind": "pet"}


@pytest.mark.parametrize("on", [False, True])
async def test_process_turn_records_the_resolved_entity_as_object(db, gw, on):
    await concept(gw, "c-andrew", "Andrew")
    mid = await message(gw, "m1", "I adopted a puppy named Toby.")
    cfg = ROLES if on else BASE
    created = await ex.process_turn(db, cfg, LLM(claim("I adopted a puppy named Toby", "a puppy named Toby",
                                                       entity="Toby")), mid, ex.ObservationWorkerStats())
    assert created == 1
    (toby,) = [r["concept_id"] for r in await gw.run("concept_links.live_concepts") if r["text_raw"] == "Toby"]
    ((oid, _),) = edges(db, "OBSERVATION_ABOUT") & {(o, c) for o, c in edges(db, "OBSERVATION_ABOUT") if c == toby}
    if on:
        assert edges(db, "HAS_SUBJECT") == {(oid, "c-andrew")}
        assert edges(db, "HAS_OBJECT") == {(oid, toby)}
        assert await literal(gw, oid, "object_id") == toby
    else:
        assert edges(db, "HAS_SUBJECT") == edges(db, "HAS_OBJECT") == set()
        assert await literal(gw, oid, "object_id") is None


# --- backfill -------------------------------------------------------------------------

async def seed_flag_off_store(db, gw):
    for cid, text in (("c-andrew", "Andrew"), ("c-toby", "Toby"), ("c-buddy", "Buddy"), ("c-pet", "pet")):
        await concept(gw, cid, text)
    await kinds.mark_kind(gw, "c-pet")
    a = dict(subject_id="c-andrew")
    ids = {
        "by_id": await record(db, gw, "m1", "Andrew owns Toby.", object_id="c-toby", object_text="Toby", **a),
        "by_text": await record(db, gw, "m2", "Andrew walks his dog Buddy.", object_text="his dog Buddy",
                                about=("c-buddy",), **a),
        "ambiguous": await record(db, gw, "m3", "Andrew has Toby and Buddy.", object_text="Toby and Buddy",
                                  about=("c-toby", "c-buddy"), **a),
        "none": await record(db, gw, "m4", "Andrew owns a couch.", object_text="a couch", **a),
        "no_subject": await record(db, gw, "m5", "Andrew knows Buddy.", object_text="Buddy",
                                   predicate="relates_to", about=("c-buddy",)),
    }
    return ids


async def test_backfill_roles_rule_and_counts(db, gw):
    ids = await seed_flag_off_store(db, gw)
    assert edges(db, "HAS_SUBJECT") == edges(db, "HAS_OBJECT") == set()
    about = edges(db, "OBSERVATION_ABOUT")
    stats = await bf.backfill_roles(db)
    assert (stats.observations, stats.subject_before, stats.object_before) == (5, 0, 0)
    assert (stats.subject_after, stats.object_after, stats.ambiguous) == (4, 3, 1)
    assert edges(db, "HAS_SUBJECT") == {(ids[k], "c-andrew") for k in ("by_id", "by_text", "ambiguous", "none")}
    assert edges(db, "HAS_OBJECT") == {(ids["by_id"], "c-toby"), (ids["by_text"], "c-buddy"),
                                       (ids["no_subject"], "c-buddy")}
    assert await literal(gw, ids["by_text"], "object_id") == "c-buddy"       # filled from the edge
    assert await literal(gw, ids["ambiguous"], "object_id") is None
    assert await literal(gw, ids["none"], "object_id") is None
    assert edges(db, "OBSERVATION_ABOUT") == about                           # untouched


async def test_backfill_is_idempotent(db, gw):
    await seed_flag_off_store(db, gw)
    await bf.backfill_roles(db)
    before = (edges(db, "HAS_SUBJECT"), edges(db, "HAS_OBJECT"))
    again = await bf.backfill_roles(db)
    assert (edges(db, "HAS_SUBJECT"), edges(db, "HAS_OBJECT")) == before
    assert (again.subject_before, again.object_before) == (4, 3) and again.object_after == 3


async def test_backfill_ignores_kind_concepts_and_short_or_partial_words(db, gw):
    await concept(gw, "c-a", "Andrew")
    await concept(gw, "c-kind", "dog")
    await concept(gw, "c-pup", "pup")
    await kinds.mark_kind(gw, "c-kind")
    oid = await record(db, gw, "m1", "Andrew owns a dog.", subject_id="c-a", object_text="a dog", about=("c-kind",))
    other = await record(db, gw, "m2", "Andrew owns a puppy.", subject_id="c-a", object_text="a puppy",
                         about=("c-pup",))                  # "pup" is not a whole word of "puppy"
    await bf.backfill_roles(db)
    assert edges(db, "HAS_OBJECT") == set() and oid and other


# --- the reader -----------------------------------------------------------------------

async def seed_reader_store(db, gw):
    for cid, text in (("c-andrew", "Andrew"), ("c-toby", "Toby"), ("c-hike", "hiking"), ("c-pet", "pet"),
                      ("c-animal", "animal")):
        await concept(gw, cid, text)
    await kinds.mark_kind(gw, "c-pet")
    await kinds.mark_kind(gw, "c-animal")
    await kinds.link_instance_of(gw, "c-toby", "c-pet")
    await kinds.link_broader(gw, "c-pet", "c-animal")
    owns = await record(db, gw, "m1", "Andrew owns Toby.", subject_id="c-andrew", object_id="c-toby",
                        object_text="Toby", config=ROLES)
    likes = await record(db, gw, "m2", "Andrew likes hiking.", subject_id="c-andrew", object_id="c-hike",
                         object_text="hiking", predicate="prefers", config=ROLES)
    return owns, likes


async def test_objects_of_subject_rows_kinds_and_predicate_filter(db, gw):
    owns, likes = await seed_reader_store(db, gw)
    rows = [dict(r) for r in await gw.run("observations.objects_of_subject", sid="c-andrew", predicate=None)]
    assert {r["object_label"] for r in rows} == {"Toby", "hiking"}
    toby = next(r for r in rows if r["object_label"] == "Toby")
    assert (toby["observation_id"], toby["predicate"], toby["object_id"], toby["evidence_message_id"]) == \
        (owns, "owns", "c-toby", "m1")
    assert set(toby["kinds"].split("|")) == {"pet", "animal"}                 # INSTANCE_OF then BROADER*
    assert toby["occurred_at"] is not None
    assert next(r for r in rows if r["object_label"] == "hiking")["kinds"] in (None, "")
    only = [dict(r) for r in await gw.run("observations.objects_of_subject", sid="c-andrew", predicate="owns")]
    assert [r["object_label"] for r in only] == ["Toby"]
    assert await gw.run("observations.objects_of_subject", sid="c-andrew", predicate="plans") == []
    assert await gw.run("observations.objects_of_subject", sid="c-toby", predicate=None) == []     # abstain: nothing


async def test_superseded_observation_is_not_listed(db, gw):
    owns, likes = await seed_reader_store(db, gw)
    await gw.run("observations.link_deprecated_by", oid=likes, by=owns)
    rows = [dict(r) for r in await gw.run("observations.objects_of_subject", sid="c-andrew", predicate=None)]
    assert {r["object_label"] for r in rows} == {"Toby"}


async def test_role_link_counts(db, gw):
    await seed_reader_store(db, gw)
    await record(db, gw, "m3", "Andrew owns a couch.", object_text="a couch", subject_id="c-andrew")
    row = dict((await gw.run("observations.role_link_counts"))[0])
    assert (row["observations"], row["with_subject"], row["with_object"]) == (3, 2, 2)


# --- the report helpers read the same NamedQueries from a read-only store -------------

def _report():
    spec = importlib.util.spec_from_file_location(
        "gsr_b522", Path(__file__).resolve().parents[1] / "scripts" / "graph_structure_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_report_role_share_and_objects_of_subject(tmp_path):
    path = tmp_path / "store.db"
    db = OxigraphClient(path)
    gw = GraphGateway(db, REGISTRY)
    await seed_reader_store(db, gw)
    del gw, db                                                     # release the writer before the read-only open
    import gc

    gc.collect()
    rep = _report()
    store = rep.open_store(path)
    assert rep.role_counts(store) == {"observations": 2, "with_subject_edge": 2, "with_object_edge": 2}
    rows = rep.objects_of_subject(store, "andrew")
    assert {r["object_label"] for r in rows} == {"Toby", "hiking"}
    assert [r["object_label"] for r in rep.objects_of_subject(store, "Andrew", "owns")] == ["Toby"]
    assert rep.objects_of_subject(store, "Nobody") == []
