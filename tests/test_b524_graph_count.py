"""B524: count and list questions answered by a subject-anchored graph query (flag, default off).

Real Oxigraph store, no model. Pins:
- routing: the count/list forms, the verb map to the closed predicate set, the "as of" bound, and every
  way a question declines (no form, unmapped verb, unparsable time phrase);
- resolution: subject and kind come from existing Concepts only, nothing is created, ambiguity declines;
- the queries: subject anchoring (two speakers, different pets, different counts), kind closure through
  BROADER, the time bound on the evidence turn, archived and DEPRECATED_BY excluded, one row per object
  with its earliest evidence, abstain when nothing matches;
- the bundle section: flag off = no section, flag on = the labelled section with the query's count and
  each item citing its turn;
- the B505 failure shape: a kind-only count (no subject, no relation) is NOT what this returns.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import graph_count as gc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
ON = {"retrieval": {"graph_count": True}}
ROLES = {"observations": {"enabled": True, "object_roles": True, "entities": True},
         "retrieval": {"conversation_token_budget": 0}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b524.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def message(gw, mid, text, day, speaker):
    stamp = f"2023-{day}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)


async def concept(gw, cid, text, kind=False):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing", now=T0)
    if kind:
        await kinds.mark_kind(gw, cid)


async def owns(db, gw, mid, day, speaker, subject_id, object_id, label, quote, predicate="owns"):
    await message(gw, mid, quote, day, speaker)
    res = await obs.record_observation(
        db, obs.ObservationDraft(evidence_ref=mid, evidence_text=quote, subject_text="I", predicate=predicate,
                                 object_text=label, extraction_method="pattern", confidence=0.9,
                                 rule_version="rule:first_person_possession", subject_id=subject_id,
                                 object_id=object_id),
        config=ROLES)
    assert res.ok, res
    return res.observation_id


async def seed(db, gw):
    """Andrew: Toby (dog), Buddy (dog), a bike. Audrey: Max (dog). pet > animal; dog under pet."""
    for cid, text, is_kind in (("c-andrew", "Andrew", False), ("c-audrey", "Audrey", False),
                               ("c-toby", "Toby", False), ("c-buddy", "Buddy", False), ("c-max", "Max", False),
                               ("c-bike", "bike", False), ("c-pet", "pet", True), ("c-dog", "dog", True),
                               ("c-animal", "animal", True), ("c-vehicle", "vehicle", True)):
        await concept(gw, cid, text, is_kind)
    await kinds.link_broader(gw, "c-dog", "c-pet")
    await kinds.link_broader(gw, "c-pet", "c-animal")
    await kinds.link_instance_of(gw, "c-toby", "c-dog")
    await kinds.link_instance_of(gw, "c-buddy", "c-pet")
    await kinds.link_instance_of(gw, "c-max", "c-dog")
    await kinds.link_instance_of(gw, "c-bike", "c-vehicle")
    ids = {
        "toby": await owns(db, gw, "m1", "05-03", "Andrew", "c-andrew", "c-toby", "Toby", "My pup Toby is great."),
        "buddy": await owns(db, gw, "m2", "07-10", "Andrew", "c-andrew", "c-buddy", "Buddy", "I adopted Buddy."),
        "bike": await owns(db, gw, "m3", "07-11", "Andrew", "c-andrew", "c-bike", "bike", "I bought a bike."),
        "max": await owns(db, gw, "m4", "06-01", "Audrey", "c-audrey", "c-max", "Max", "Max, my dog, is old."),
    }
    return ids


def params(sid, kind_id, before=None, predicate="owns"):
    return dict(sid=sid, kind_id=kind_id, predicate=predicate, before=before)


async def n_of(gw, **p):
    return (await gw.run("observations.count_objects_of_subject", **p))[0]["n"]


# --- routing -----------------------------------------------------------------------

@pytest.mark.parametrize("question,form", [
    ("How many pets does Andrew have?", "how many"),
    ("How much cats do they own", "how much"),
    ("What is the number of dogs Andrew owns?", "number of"),
    ("List the pets Andrew has", "list"),
    ("What pets does Andrew have?", "what-does-have"),
])
def test_count_and_list_forms_route(question, form):
    r = gc.route_question(question)
    assert r is not None and r.form == form and r.predicate == "owns" and r.before is None


@pytest.mark.parametrize("question", [
    "Does Andrew like dogs?",                              # no count form
    "How many pets did Andrew visit?",                     # verb not in the map: not guessed
    "How many pets did Andrew have by sometime soon?",     # time phrase that does not parse declines
    "",
])
def test_unrouted_questions_decline(question):
    assert gc.route_question(question) is None


def test_every_mapped_verb_is_a_predicate_of_the_closed_set():
    assert set(gc.RELATION_BY_VERB.values()) <= set(obs.PREDICATES)


def test_as_of_bound_is_the_day_after_the_resolved_date():
    r = gc.route_question("How many pets did Andrew have as of 1 August 2023?")
    assert r.before == datetime(2023, 8, 2, tzinfo=timezone.utc)
    r = gc.route_question("How many pets does Andrew have by 2024?")
    assert r.before == datetime(2025, 1, 1, tzinfo=timezone.utc)


# --- resolution --------------------------------------------------------------------

async def test_subject_and_kind_resolve_from_existing_concepts(db, gw):
    await seed(db, gw)
    res = await gc.resolve_question(gw, "How many pets does Andrew have?")
    assert (res.subject_id, res.kind_id, res.kind_label) == ("c-andrew", "c-pet", "pet")
    res = await gc.resolve_question(gw, "How many dogs does Audrey's family own?")
    assert (res.subject_id, res.kind_id) == ("c-audrey", "c-dog")


async def test_unknown_subject_unknown_kind_or_two_speakers_decline_and_create_nothing(db, gw):
    await seed(db, gw)
    before = db._execute_and_collect("SELECT (COUNT(?c) AS ?n) WHERE { ?c a <https://campy.dev/ns#Concept> }")
    assert await gc.resolve_question(gw, "How many pets does Zed have?") is None          # no such subject
    assert await gc.resolve_question(gw, "How many hats does Andrew have?") is None       # no such kind
    assert await gc.resolve_question(gw, "How many pets do Andrew and Audrey have?") is None   # two subjects
    assert db._execute_and_collect("SELECT (COUNT(?c) AS ?n) WHERE { ?c a <https://campy.dev/ns#Concept> }") == before


# --- the queries -------------------------------------------------------------------

async def test_subject_anchoring_two_speakers_give_different_counts(db, gw):
    await seed(db, gw)
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 2          # Toby (dog < pet) and Buddy
    assert await n_of(gw, **params("c-audrey", "c-pet")) == 1          # Max
    assert await n_of(gw, **params("c-andrew", "c-dog")) == 1          # Toby only: Buddy is a pet, not a dog
    assert await n_of(gw, **params("c-andrew", "c-vehicle")) == 1


async def test_kind_closure_goes_through_broader(db, gw):
    await seed(db, gw)
    assert await n_of(gw, **params("c-andrew", "c-animal")) == 2       # dog < pet < animal, and pet < animal
    rows = await gw.run("observations.objects_of_subject_kind", **params("c-andrew", "c-animal"))
    assert [r["object_label"] for r in rows] == ["Toby", "Buddy"]


async def test_time_bound_uses_the_evidence_turn_date(db, gw):
    await seed(db, gw)
    assert await n_of(gw, **params("c-andrew", "c-pet", before="2023-07-01T00:00:00+00:00")) == 1
    rows = await gw.run("observations.objects_of_subject_kind",
                        **params("c-andrew", "c-pet", before="2023-07-01T00:00:00+00:00"))
    assert [r["object_label"] for r in rows] == ["Toby"]
    assert await n_of(gw, **params("c-andrew", "c-pet", before="2023-01-01T00:00:00+00:00")) == 0   # abstain


async def test_archived_and_deprecated_observations_are_not_counted(db, gw):
    ids = await seed(db, gw)
    db.execute(f'DELETE {{ ?o <https://campy.dev/ns#archived> false }} INSERT {{ ?o <https://campy.dev/ns#archived> true }} '
               f'WHERE {{ ?o <https://campy.dev/ns#observation_id> "{ids["buddy"]}" ; <https://campy.dev/ns#archived> false }}')
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 1
    await gw.run("observations.link_deprecated_by", oid=ids["toby"], by=ids["max"])
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 0


async def test_one_row_per_object_with_its_earliest_evidence(db, gw):
    await seed(db, gw)
    await owns(db, gw, "m5", "09-01", "Andrew", "c-andrew", "c-toby", "Toby", "Toby and I went hiking.")
    rows = [dict(r) for r in await gw.run("observations.objects_of_subject_kind", **params("c-andrew", "c-pet"))]
    assert [(r["object_label"], r["evidence_message_id"]) for r in rows] == [("Toby", "m1"), ("Buddy", "m2")]
    assert rows[0]["quote"] == "My pup Toby is great." and rows[0]["occurred_at"].startswith("2023-05-03")
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 2


async def test_other_predicates_do_not_count(db, gw):
    await seed(db, gw)
    await owns(db, gw, "m6", "09-02", "Andrew", "c-andrew", "c-max", "Max", "I like Max.", predicate="prefers")
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 2
    assert await n_of(gw, **params("c-andrew", "c-pet", predicate="prefers")) == 1


async def test_b505_failure_shape_kind_only_count_is_not_what_this_returns(db, gw):
    """B505 counted every INSTANCE_OF member of the kind, ignoring the subject: 'How many pets will
    Andrew have?' answered with the store's whole pet population. The query here is anchored: a subject
    with nothing recorded gets 0 even though the store holds pets, and Andrew's count excludes Audrey's."""
    await seed(db, gw)
    everyone = db._execute_and_collect(
        "SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { ?x (<https://campy.dev/ns#INSTANCE_OF>)/<https://campy.dev/ns#BROADER>* "
        "?k . ?k <https://campy.dev/ns#concept_id> \"c-pet\" }")[0]["n"]
    assert everyone == 3                                                 # the B505 number: all pets in the store
    assert await n_of(gw, **params("c-andrew", "c-pet")) == 2 != everyone
    await concept(gw, "c-zed", "Zed")
    assert await n_of(gw, **params("c-zed", "c-pet")) == 0


# --- the bundle section ------------------------------------------------------------

async def test_flag_off_builds_no_section(db, gw):
    await seed(db, gw)
    assert await gc.build_graph_count_section(db, "How many pets does Andrew have?", {}) is None
    assert await gc.build_graph_count_section(db, "How many pets does Andrew have?", {"retrieval": {"graph_count": False}}) is None


async def test_flag_on_builds_a_cited_section_from_the_query(db, gw):
    await seed(db, gw)
    sec = await gc.build_graph_count_section(db, "How many pets does Andrew have?", ON)
    assert sec.section_type == "graph_count"
    text = sec.content[0]["text"]
    assert text.startswith("[graph count] Andrew owns 2 of kind pet")
    assert 'Toby (2023-05-03, m1, "My pup Toby is great.")' in text
    assert 'Buddy (2023-07-10, m2, "I adopted Buddy.")' in text
    assert "Max" not in text and "bike" not in text
    assert len(sec.source_node_ids) == 2


async def test_time_bound_in_the_question_reaches_the_query(db, gw):
    await seed(db, gw)
    sec = await gc.build_graph_count_section(db, "How many pets did Andrew have as of 1 July 2023?", ON)
    assert "owns 1 of kind pet" in sec.content[0]["text"] and "Buddy" not in sec.content[0]["text"]


async def test_nothing_recorded_or_unresolved_gives_no_section(db, gw):
    await seed(db, gw)
    await concept(gw, "c-zed", "Zed")
    for q in ("How many pets does Zed have?", "How many pets does Nobody have?", "How many hats does Andrew have?",
              "How many pets did Andrew visit?", "Tell me about Andrew"):
        assert await gc.build_graph_count_section(db, q, ON) is None, q


async def test_compile_bundle_carries_the_section_only_with_the_flag(db, gw):
    from campy.brain.thalamus.bundle_compiler import compile_bundle
    await seed(db, gw)
    base = {**ROLES, "retrieval": {"conversation_token_budget": 0}}
    off = await compile_bundle("How many pets does Andrew have?", db, base)
    assert "graph_count" not in [s.section_type for s in off.sections]
    on = await compile_bundle("How many pets does Andrew have?", db, {**base, "retrieval": {**base["retrieval"], "graph_count": True}})
    assert [s.section_type for s in on.sections][0] == "graph_count"


# --- the flag ----------------------------------------------------------------------

def test_flag_default_off_and_env_turns_it_on(monkeypatch):
    assert _DEFAULT_CONFIG["retrieval"]["graph_count"] is False
    monkeypatch.setenv("CAMPY_GRAPH_COUNT", "1")
    cfg = apply_env_overrides({"retrieval": {"graph_count": False}})
    assert gc.graph_count_enabled(cfg) is True
    assert gc.graph_count_enabled({}) is False
