"""B535: the vocabulary steward proposes kind links and entity kinds from closed choices; a rule promotes.

Real Oxigraph store, a scripted model (no network). Pins:
- flag off = nothing, and no model is even created; no model reachable = nothing;
- closed choices: an answer outside the numbered list (or unparsable) is rejected and counted, "none" writes
  nothing, the list holds only live kinds (never the kind itself or a kind below it);
- candidates are reifiers that assert nothing: the B524 count, the walk and the kind vocabulary do not see them
  until promoted;
- every promotion route (WordNet closure, recurrence over two evidence sets, a second model, a person), and
  no promotion without one;
- review of a WordNet link: keep stores nothing; one reject is "disputed" and the link stays in the walk; a
  second source retracts it, the record stays, and WordNet's backfill does not put it back;
- every decision and its sources are readable (`steward.proposals`, `steward.status_counts`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe import steward as st
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import entities as ent
from tests.test_b534_wordnet_kinds import fake_wordnet

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
ON = {"observations": {"vocab_steward": True}}
ROLES = {"observations": {"enabled": True, "object_roles": True, "entities": True},
         "retrieval": {"conversation_token_budget": 0}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b535.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


@pytest.fixture
def wn(monkeypatch):
    w = fake_wordnet()
    monkeypatch.setattr(wn_mod, "_wn", lambda: w)
    return w


@pytest.fixture
def no_wn(monkeypatch):
    monkeypatch.setattr(wn_mod, "_wn", lambda: None)


# --- a scripted model -----------------------------------------------------------------------

class Model:
    """Answers by reading the package: `pick` maps a subject label to the label to choose ("none" allowed);
    `verdicts` maps a "child -> parent" to keep/reject. Records every prompt."""

    def __init__(self, pick=None, verdicts=None, raw=None, fail=False):
        self.pick, self.verdicts, self.raw, self.fail = pick or {}, verdicts or {}, raw, False
        self.fail = fail
        self.prompts: list[str] = []

    async def achat(self, messages, **kw):
        if self.fail:
            raise ConnectionError("model down")
        text = messages[-1]["content"]
        self.prompts.append(text)
        if self.raw is not None:
            return self.raw
        claim = re.search(r'Claim: every "(.+?)" is a kind of "(.+?)"', text)
        if claim:
            v = self.verdicts.get(f"{claim.group(1)} -> {claim.group(2)}", "keep")
            return json.dumps({"verdict": v, "reason": "scripted"})
        subject = re.search(r'(?:Kind|Entity): "(.+?)"', text).group(1)
        want = self.pick.get(subject, "none")
        if want == "none":
            return json.dumps({"choice": "none", "reason": "scripted"})
        options = dict((label, int(n)) for n, label in re.findall(r"^(\d+)\. (.+)$", text, re.M))
        if want.startswith("#"):                       # a mis-indexed answer: the number of another kind, this name
            return json.dumps({"choice": options[want[1:]], "name": want[1:] + "?", "reason": "scripted"})
        return json.dumps({"choice": options.get(want, 99), "name": want, "reason": "scripted"})


async def concept(gw, cid, text, kind=False):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing", now=T0)
    if kind:
        await kinds_mod.mark_kind(gw, cid)


async def message(gw, mid, text, day, speaker):
    stamp = f"2023-{day}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)


async def owns(db, gw, mid, day, speaker, subject_id, object_id, label, quote):
    await message(gw, mid, quote, day, speaker)
    res = await obs.record_observation(
        db, obs.ObservationDraft(evidence_ref=mid, evidence_text=quote, subject_text="I", predicate="owns",
                                 object_text=label, extraction_method="pattern", confidence=0.9,
                                 rule_version="rule:first_person_possession", subject_id=subject_id,
                                 object_id=object_id), config=ROLES)
    assert res.ok, res


async def world(db, gw, dogs=3):
    """Andrew owns `dogs` dogs filed under the parentless kind "dog" and a bike; kinds pet, animal, vehicle."""
    await concept(gw, "c-andrew", "Andrew")
    for cid, label in (("c-dog", "dog"), ("c-pet", "pet"), ("c-animal", "animal"), ("c-vehicle", "vehicle")):
        await concept(gw, cid, label, kind=True)
    for i in range(dogs):
        await concept(gw, f"c-d{i}", f"Dog{i}")
        await kinds_mod.link_instance_of(gw, f"c-d{i}", "c-dog")
        await owns(db, gw, f"m{i}", f"05-0{i + 1}", "Andrew", "c-andrew", f"c-d{i}", f"Dog{i}", f"I adopted Dog{i}.")
    await concept(gw, "c-bike", "bike")
    await kinds_mod.link_instance_of(gw, "c-bike", "c-vehicle")


async def count(gw, kind_id, sid="c-andrew"):
    r = await gw.run("observations.count_objects_of_subject", sid=sid, kind_id=kind_id, predicate="owns", before=None)
    return int(r[0]["n"])


async def status_of(gw, child, parent):
    return {(r["child"], r["parent"]): (r["status"], r["source"], r["agreed_by"] or "", int(r["sets"]))
            for r in await gw.run("steward.proposals")}.get((child, parent))


async def broader(gw):
    return {(r["child"], r["parent"]): r["source"] for r in await gw.run("kinds.broader_links_detail")}


# --- off / unavailable ----------------------------------------------------------------------

async def test_flag_off_does_nothing_and_creates_no_model(db, gw, monkeypatch):
    await world(db, gw)
    monkeypatch.setattr(st, "create_clients", lambda cfg: (_ for _ in ()).throw(AssertionError("model created")))
    rep = await st.run_steward(gw, {})
    assert not rep.enabled and rep.calls == 0 and await gw.run("steward.proposals") == []
    assert st.steward_enabled({"observations": {}}) is False


async def test_no_model_reachable_writes_nothing(db, gw, monkeypatch):
    await world(db, gw)
    monkeypatch.setattr(st, "create_clients", lambda cfg: (None, None))
    rep = await st.run_steward(gw, ON)
    assert rep.llm_unavailable and rep.calls == 0 and await gw.run("steward.proposals") == []
    down = Model(fail=True)
    rep = await st.run_steward(gw, ON, client=down)
    assert rep.llm_unavailable and rep.calls == 0 and await gw.run("steward.proposals") == []


# --- closed choices -------------------------------------------------------------------------

async def test_an_answer_outside_the_list_is_rejected_and_counted(db, gw, no_wn):
    await world(db, gw)
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "not a listed kind"}))   # -> number 99
    assert rep.invalid >= 1 and rep.proposed == 0 and await gw.run("steward.proposals") == []
    junk = await st.run_steward(gw, ON, tasks=("parent",), client=Model(raw="I think dog is a pet"))
    assert junk.invalid >= 1 and junk.proposed == 0


@pytest.mark.parametrize("text,kind", [
    ('{"choice": 2, "name": "pet", "reason": "x"}', "choice"), ('{"choice": "none"}', "none"), ('{"choice": 0}', "none"),
    ('{"choice": 4, "name": "x"}', "invalid"), ('{"choice": -1}', "invalid"), ('{"choice": "pet"}', "invalid"),
    ('no json', "invalid"), ('{"reason": "x"}', "invalid"), ('```json\n{"choice": 3, "name": "Vehicle"}\n```', "choice"),
    ('{"choice": 1, "name": "pet"}', "mismatch"), ('{"choice": 2}', "mismatch"),
])
def test_parse_choice_is_closed(text, kind):
    assert st.parse_choice(text, ["animal", "pet", "vehicle"]).kind == kind


async def test_a_mis_indexed_answer_is_rejected_and_counted(db, gw, no_wn):
    await world(db, gw, dogs=1)
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "#pet"}), only={"dog"})
    assert rep.mismatch == 1 and rep.proposed == 0 and await gw.run("steward.proposals") == []


def test_parse_verdict_is_closed():
    assert st.parse_verdict('{"verdict": "Reject", "reason": "no"}').kind == "reject"
    assert st.parse_verdict('{"verdict": "maybe"}').kind == "invalid" and st.parse_verdict("keep").kind == "invalid"


async def test_none_writes_nothing_and_the_list_is_only_live_kinds(db, gw, no_wn):
    await world(db, gw)
    await concept(gw, "c-puppy", "puppy", kind=True)
    await kinds_mod.link_broader(gw, "c-puppy", "c-dog")
    model = Model()
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=model, only={"dog"})
    assert rep.none >= 1 and await gw.run("steward.proposals") == []
    listed = set(re.findall(r"^\d+\. (.+)$", model.prompts[0], re.M))
    assert listed == {"pet", "animal", "vehicle"}          # not "dog" itself, not "puppy" (below it: a cycle)


# --- candidates are invisible until promoted ------------------------------------------------

async def test_a_candidate_is_invisible_to_the_count_the_walk_and_the_vocabulary(db, gw, no_wn):
    await world(db, gw, dogs=1)
    assert await count(gw, "c-pet") == 0
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "pet"}), only={"dog"})
    assert rep.proposed == 1 and rep.promoted == 0
    assert await status_of(gw, "dog", "pet") == ("candidate", "steward", "", 1)
    assert await count(gw, "c-pet") == 0                                    # B524's count walk does not see it
    assert ("dog", "pet") not in await broader(gw)                          # nor the BROADER detail/report queries
    assert "c-pet" not in (await kinds_mod.load_kinds(gw))["c-dog"].broader
    assert db._execute_and_collect("ASK { ?a <https://campy.dev/ns#BROADER> ?b }") is False   # no triple at all
    by_source = {r["source"]: int(r["n"]) for r in await gw.run("kinds.broader_links_by_source")}
    assert "steward" not in by_source


async def test_a_second_run_does_not_ask_the_same_evidence_set_again(db, gw, no_wn):
    await world(db, gw, dogs=3)
    m = Model(pick={"dog": "pet"})
    await st.run_steward(gw, ON, tasks=("parent",), client=m, only={"dog"})
    first = len(m.prompts)
    await st.run_steward(gw, ON, tasks=("parent",), client=m, only={"dog"})
    assert len(m.prompts) == first                                           # the one set was recorded


# --- the promotion routes -------------------------------------------------------------------

async def test_route_wordnet_promotes_when_the_closure_contains_the_parent(db, gw, wn):
    await world(db, gw, dogs=1)
    # "animal" is an ancestor of "dog" in WordNet (dog > canine > animal) though not its nearest kind
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "animal"}), only={"dog"})
    assert rep.agreed["wordnet"] == 1 and rep.promoted == 1
    assert (await status_of(gw, "dog", "animal"))[:3] == ("promoted", "steward", "wordnet")
    assert await count(gw, "c-animal") == 1                                  # now the walk reaches it
    assert (await broader(gw))[("dog", "animal")] == "steward"


async def test_common_sense_link_wordnet_does_not_support_stays_a_candidate(db, gw, wn):
    await world(db, gw, dogs=1)
    await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "pet"}), only={"dog"})
    assert (await status_of(gw, "dog", "pet"))[0] == "candidate"
    assert await count(gw, "c-pet") == 0


async def test_route_recurrence_needs_two_different_evidence_sets(db, gw, no_wn):
    await world(db, gw, dogs=3)                                              # one set of three
    m = Model(pick={"dog": "pet"})
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=m, only={"dog"})
    assert rep.promoted == 0 and (await status_of(gw, "dog", "pet"))[0] == "candidate"
    await concept(gw, "c-d3", "Dog3")                                        # a fourth dog: a second set appears
    await kinds_mod.link_instance_of(gw, "c-d3", "c-dog")
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=m, only={"dog"})
    assert rep.agreed["recurrence"] == 1 and rep.promoted == 1
    status, source, agreed, sets = await status_of(gw, "dog", "pet")
    assert (status, agreed, sets) == ("promoted", "recurrence", 2)
    assert await count(gw, "c-pet") == 3


async def test_recurrence_in_one_run_asks_the_second_set_with_the_list_reversed(db, gw, no_wn):
    await world(db, gw, dogs=6)
    m = Model(pick={"dog": "pet"})
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=m, only={"dog"})
    assert rep.calls == 2 and rep.promoted == 1
    order = [re.findall(r"^\d+\. (.+)$", p, re.M) for p in m.prompts]
    assert order[0] == list(reversed(order[1]))


async def test_route_second_model_promotes_only_when_it_agrees(db, gw, no_wn):
    await world(db, gw, dogs=1)
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "pet"}),
                               second_client=Model(pick={"dog": "animal"}), only={"dog"})
    assert rep.second_calls == 1 and rep.promoted == 0 and (await status_of(gw, "dog", "pet"))[0] == "candidate"


async def test_second_model_agreement_promotes_and_is_recorded(db, gw, no_wn):
    await world(db, gw, dogs=1)
    rep = await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "pet"}),
                               second_client=Model(pick={"dog": "pet"}), only={"dog"})
    assert rep.agreed["second_model"] == 1 and rep.promoted == 1
    assert (await status_of(gw, "dog", "pet"))[:3] == ("promoted", "steward", "second_model")
    assert await count(gw, "c-pet") == 1


async def test_the_second_model_is_off_unless_configured(db, gw):
    assert st.second_model_configured({"llm": {"max_tokens": 5}}) is False
    assert st.second_model_configured({"llm": {"steward_second": {"model": "other"}}}) is True


async def test_route_person(db, gw, no_wn):
    await world(db, gw, dogs=1)
    await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"dog": "pet"}), only={"dog"})
    assert await count(gw, "c-pet") == 0
    await st.agree(gw, "BROADER", "c-dog", "c-pet", "person")
    await st.apply_promotion_rule(gw, None)
    assert (await status_of(gw, "dog", "pet"))[:3] == ("promoted", "steward", "person")
    assert await count(gw, "c-pet") == 1
    with pytest.raises(ValueError):
        await st.agree(gw, "BROADER", "c-dog", "c-pet", "gut feeling")


async def test_no_source_no_promotion_and_a_cycle_is_never_promoted(db, gw, no_wn):
    await world(db, gw, dogs=1)
    await kinds_mod.link_broader(gw, "c-pet", "c-dog")                        # pet is already below dog
    await gw.run("steward.propose_broader", cid="c-dog", pid="c-pet", reason="x")
    await st.agree(gw, "BROADER", "c-dog", "c-pet", "person")
    await st.apply_promotion_rule(gw, None)
    assert (await status_of(gw, "dog", "pet")) is None                         # the propose guard refused the cycle


# --- task b: the kind of an owned entity ----------------------------------------------------

async def test_an_owned_entity_without_a_kind_gets_a_candidate_kind(db, gw, no_wn):
    await world(db, gw, dogs=0)
    await concept(gw, "c-scout", "Scout")
    await owns(db, gw, "m9", "06-01", "Andrew", "c-andrew", "c-scout", "Scout", "My dog Scout loves the beach.")
    m = Model(pick={"Scout": "dog"})
    rep = await st.run_steward(gw, ON, tasks=("kind",), client=m)
    assert rep.proposed == 1 and "loves the beach" in m.prompts[0]
    assert await status_of(gw, "Scout", "dog") == ("candidate", "steward", "", 1)
    assert await count(gw, "c-dog") == 0                                      # no INSTANCE_OF yet
    rows = await gw.run("steward.owned_without_kind")
    assert [r["label"] for r in rows] == ["Scout"]
    await st.agree(gw, "INSTANCE_OF", "c-scout", "c-dog", "person")
    await st.apply_promotion_rule(gw, None)
    assert await count(gw, "c-dog") == 1 and await gw.run("steward.owned_without_kind") == []


# --- task c: review of a WordNet link -------------------------------------------------------

async def wordnet_link(db, gw, dogs=3):
    await world(db, gw, dogs=dogs)
    await kinds_mod.link_broader_sourced(gw, "c-dog", "c-pet", "wordnet")


async def test_keep_stores_nothing(db, gw, no_wn):
    await wordnet_link(db, gw)
    rep = await st.run_steward(gw, ON, tasks=("review",), client=Model())
    assert rep.kept == 1 and await gw.run("steward.proposals") == [] and ("dog", "pet") in await broader(gw)


async def test_one_reject_is_disputed_and_the_link_stays(db, gw, no_wn):
    await wordnet_link(db, gw)
    rep = await st.run_steward(gw, ON, tasks=("review",), client=Model(verdicts={"dog -> pet": "reject"}))
    assert rep.proposed == 1 and rep.rejected == 0
    assert (await status_of(gw, "dog", "pet"))[:2] == ("disputed", "wordnet")
    assert (await broader(gw))[("dog", "pet")] == "wordnet" and await count(gw, "c-pet") == 3


async def test_a_second_source_retracts_the_link_and_the_record_stays(db, gw, wn):
    await wordnet_link(db, gw, dogs=1)
    rep = await st.run_steward(gw, ON, tasks=("review",), client=Model(verdicts={"dog -> pet": "reject"}),
                               second_client=Model(verdicts={"dog -> pet": "reject"}))
    assert rep.rejected == 1
    assert (await status_of(gw, "dog", "pet"))[:3] == ("rejected", "wordnet", "second_model")
    assert ("dog", "pet") not in await broader(gw) and await count(gw, "c-pet") == 0
    await ent.propose_wordnet_links(gw)
    assert ("dog", "pet") not in await broader(gw)                              # WordNet's backfill does not put it back


async def test_recurrence_retracts_a_disputed_link_and_a_disagreeing_second_model_does_not(db, gw, no_wn):
    await wordnet_link(db, gw, dogs=6)
    rep = await st.run_steward(gw, ON, tasks=("review",), client=Model(verdicts={"dog -> pet": "reject"}),
                               second_client=Model())                           # the second model says keep
    assert rep.calls == 2 and rep.rejected == 1                                  # two evidence sets recur
    assert (await status_of(gw, "dog", "pet"))[2] == "recurrence" and ("dog", "pet") not in await broader(gw)


async def test_a_disagreeing_second_model_leaves_it_disputed(db, gw, no_wn):
    await wordnet_link(db, gw, dogs=1)
    rep = await st.run_steward(gw, ON, tasks=("review",), client=Model(verdicts={"dog -> pet": "reject"}),
                               second_client=Model())
    assert rep.rejected == 0 and (await status_of(gw, "dog", "pet"))[0] == "disputed"
    assert ("dog", "pet") in await broader(gw)


# --- decisions are readable -----------------------------------------------------------------

async def test_status_counts_report_source_and_status(db, gw, no_wn):
    await wordnet_link(db, gw, dogs=1)
    await st.run_steward(gw, ON, tasks=("review",), client=Model(verdicts={"dog -> pet": "reject"}))
    await concept(gw, "c-cat", "cat", kind=True)
    await st.run_steward(gw, ON, tasks=("parent",), client=Model(pick={"cat": "animal"}), only={"cat"})
    got = {(r["relation"], r["source"], r["status"]): int(r["n"]) for r in await gw.run("steward.status_counts")}
    assert got == {("BROADER", "wordnet", "disputed"): 1, ("BROADER", "steward", "candidate"): 1}
