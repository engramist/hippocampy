"""B472 Phase 3c: the bundle's semantic section fed from Observations.

Real Oxigraph store, hand-built embeddings (each Observation sits at a chosen
cosine similarity to the question on its own orthogonal axis), no model, no LLM.
Pins:
- `[observations] retrieval` off (the default): the bundle is the one it was
  before, whatever Observations the store holds;
- on, with matches: the semantic section carries them, each with its speaker,
  date and verbatim quote, replacing the Concept/Decision preview;
- on, with no matches: the old semantic section is returned unchanged;
- ranking, the cap, the similarity floor, the concept path (a question that names
  a Concept finds its Observations without sharing a word or an embedding);
- negated / hypothetical / planned claims are spelled out;
- the compression path keeps every line, quote and the section variant.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import ask as ask_mod
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
QUESTION = "What support group did the singer attend?"


def _vec(cos: float, axis: int) -> list[float]:
    v = [0.0] * DIM
    v[0], v[axis] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b472p3c.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


CFG_ON = {"observations": {"retrieval": True, "observation_limit": 8}}


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text, emb=None, stype="Person"):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=emb or _vec(0.0, 300 + self.n), gist="Agent", stype=stype, now=T0)
        self.n += 1
        return cid

    async def observe(self, quote, *, cos=0.8, subject="I", predicate="did", obj="went to a support group",
                      polarity="asserted", time_text=None, subject_id=None, day=8, speaker="Caroline", text_raw=None):
        self.n += 1
        mid = f"m{self.n}"
        text = f"Filler words. {quote} More filler."
        await self.gw.run(
            "capture.create_message", message_id=mid, text_raw=text, embedding=None,
            embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
            created_at=f"2023-05-{day:02d}T12:00:00+00:00")
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker,
                          occurred_at=f"2023-05-{day:02d}T12:00:00+00:00")
        text_raw = text_raw or f"{speaker} - {predicate} - {obj}"
        res = await obs.record_observation(self.db, obs.ObservationDraft(
            evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate=predicate,
            object_text=obj, extraction_method="llm", confidence=0.9, polarity=polarity,
            time_text=time_text, subject_id=subject_id, speaker=speaker,
            text_raw=text_raw, embedding=_vec(cos, 10 + self.n)))
        assert res.ok, res
        return res.observation_id, mid


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


def _semantic(bundle):
    return [s for s in bundle.sections if s.section_type == "semantic"]


# --- flag off ----------------------------------------------------------------------

def test_defaults_are_off():
    assert _DEFAULT_CONFIG["observations"]["retrieval"] is False
    assert _DEFAULT_CONFIG["observations"]["observation_limit"] == 8
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_RETRIEVAL": "1"})["observations"]["retrieval"] is True
    assert "retrieval" not in apply_env_overrides({}, {}).get("observations", {})
    assert obs.observations_retrieval_enabled({}) is False
    assert obs.observations_retrieval_enabled(_DEFAULT_CONFIG) is False


async def test_flag_off_bundle_ignores_observations(db, store):
    await store.concept("c-sing", "singer", emb=Q, stype="Person")
    before = await bc.compile_bundle(QUESTION, db, {})
    await store.observe("I went to a LGBTQ support group yesterday", time_text="yesterday")
    for cfg in ({}, {"observations": {"enabled": True}}, {"observations": {"retrieval": False}}):
        after = await bc.compile_bundle(QUESTION, db, cfg)
        assert [(s.section_type, s.content, getattr(s, "variant", "")) for s in after.sections if s.section_type != "conversation"] \
            == [(s.section_type, s.content, "") for s in before.sections if s.section_type != "conversation"]
        assert all(getattr(s, "variant", "") == "" for s in after.sections)
    assert any("singer" in c["text"] for s in _semantic(before) for c in s.content)


# --- flag on -----------------------------------------------------------------------

async def test_flag_on_semantic_section_carries_observations_with_evidence(db, store):
    await store.concept("c-sing", "singer", emb=Q)
    oid, mid = await store.observe("I went to a LGBTQ support group yesterday", time_text="yesterday")
    bundle = await bc.compile_bundle(QUESTION, db, CFG_ON)
    (section,) = _semantic(bundle)
    assert section.variant == "observations"
    assert len(section.content) == 1
    item = section.content[0]
    assert item["text"] == ('[Caroline, 2023-05-08] did: went to a support group (when: yesterday) '
                            '("I went to a LGBTQ support group yesterday")')
    assert item["type"] == "Observation" and item["observation_id"] == oid and item["evidence_ref"] == mid
    assert section.source_node_ids == [oid]
    assert not any("singer" in c["text"] for c in section.content)   # replaced, not appended
    assert section.token_estimate > 0
    assert bundle.to_dict()["sections"][[s.section_type for s in bundle.sections].index("semantic")]["variant"] == "observations"


async def test_flag_on_without_matching_observations_falls_back(db, store):
    await store.concept("c-sing", "singer", emb=Q)
    await store.observe("I went to a LGBTQ support group yesterday", cos=0.05)   # under the 0.30 floor, no shared words
    cfg_off, cfg_on = {}, CFG_ON
    off = await bc.compile_bundle("Tell me about the singer", db, cfg_off)
    on = await bc.compile_bundle("Tell me about the singer", db, cfg_on)
    assert [(s.section_type, s.content) for s in on.sections] == [(s.section_type, s.content) for s in off.sections]
    assert all(getattr(s, "variant", "") == "" for s in on.sections)
    assert any("singer" in c["text"] for s in _semantic(on) for c in s.content)


async def test_empty_store_returns_none(db):
    assert await bc._stage_observations(db, "anything at all", CFG_ON) is None


# --- ranking, cap, floor -----------------------------------------------------------

async def _texts(gw, limit=8, concept_ids=(), query="what happened"):
    rows = await gw.run("thalamus.bundle_observations", query_embedding=Q, query_text=query,
                        concept_ids=list(concept_ids), limit=limit)
    return [r["evidence_text"] for r in rows]


async def test_ranked_by_similarity_capped_and_floored(gw, store):
    await store.observe("quote far", cos=0.10, obj="alpha")
    await store.observe("quote mid", cos=0.50, obj="beta")
    await store.observe("quote near", cos=0.90, obj="gamma")
    await store.observe("quote low", cos=0.35, obj="delta")
    assert await _texts(gw) == ["quote near", "quote mid", "quote low"]      # best first; 0.10 is under the floor
    assert await _texts(gw, limit=2) == ["quote near", "quote mid"]          # the cap
    assert await _texts(gw, limit=0) == []


async def test_stage_caps_at_observation_limit_and_orders_oldest_first(db, store):
    for i, cos in enumerate((0.9, 0.8, 0.7, 0.6, 0.5)):
        await store.observe(f"I did thing number {i}", cos=cos, obj=f"thing {i}", day=10 - i)
    cfg = {"observations": {"retrieval": True, "observation_limit": 3}}
    section = await bc._stage_observations(db, "what happened", cfg)
    assert len(section.content) == 3
    dates = [c["text"][10:20] for c in section.content]
    assert dates == sorted(dates)                                            # time order (default)
    rank = await bc._stage_observations(db, "what happened", {**cfg, "retrieval": {"conversation_order": "rank"}})
    assert [c["text"].split("did: ")[1][:7] for c in rank.content] == ["thing 0", "thing 1", "thing 2"]


async def test_lexical_only_hit_needs_two_question_words(gw, store):
    await store.observe("I adopted a retriever named Biscuit", cos=0.05, obj="adopted a retriever named Biscuit")
    await store.observe("I like Biscuit crackers", cos=0.05, obj="likes crackers")
    assert await _texts(gw, query="retriever Biscuit adopted") == ["I adopted a retriever named Biscuit"]
    assert await _texts(gw, query="Biscuit") != []        # a one-word question: that word is enough
    assert await _texts(gw, query="Biscuit parade") == []  # one of two words is not


async def test_question_naming_a_concept_finds_its_observations(db, store):
    await store.concept("c-dana", "Dana")
    await store.observe("My sister Dana is a nurse", cos=0.0, subject="my sister", predicate="has_attribute",
                        obj="job: nurse", subject_id="c-dana", speaker="Melanie")
    await store.observe("I like pottery", cos=0.0, obj="pottery", predicate="prefers", speaker="Melanie")
    section = await bc._stage_observations(db, "What does Dana do for work?", CFG_ON)
    assert [c["text"] for c in section.content] == [
        '[Melanie, 2023-05-08] my sister has attribute: job: nurse ("My sister Dana is a nurse")']
    assert await bc._stage_observations(db, "What does Eve do for work?", CFG_ON) is None


async def test_concept_path_matches_labels_and_possessive(db, gw, store):
    await store.concept("c-dana", "Dana")
    await store.observe("My sister Dana is a nurse", cos=0.0, subject="my sister", predicate="has_attribute",
                        obj="job: nurse", subject_id="c-dana")
    assert await bc._question_concept_ids(gw, "Where does Dana's family live, Dana?") == ["c-dana"]
    assert await bc._question_concept_ids(gw, "What is it?") == []


async def test_concept_and_vector_agree_rank_first(gw, store):
    await store.concept("c-dana", "Dana")
    await store.observe("Dana plays chess", cos=0.0, subject_id="c-dana", subject="Dana", obj="chess")
    await store.observe("Dana plays tennis", cos=0.7, subject_id="c-dana", subject="Dana", obj="tennis")
    await store.observe("Sam plays golf", cos=0.4, subject="Sam", obj="golf")
    got = await _texts(gw, concept_ids=["c-dana"], query="zzz")
    assert got[0] == "Dana plays tennis"                       # vector AND concept: first
    assert set(got) == {"Dana plays tennis", "Sam plays golf", "Dana plays chess"}


# --- polarity and rendering --------------------------------------------------------

def test_render_spells_out_polarity_and_hides_the_speakers_own_name():
    base = {"speaker": "Caroline", "observed_at": "2023-05-08T12:00:00+00:00", "subject_text": "Caroline",
            "predicate": "plans", "object_text": "sign up for pottery", "evidence_text": "I'm going to sign up for pottery"}
    asserted = bc.render_observation({**base, "polarity": "asserted"})
    planned = bc.render_observation({**base, "polarity": "planned"})
    negated = bc.render_observation({**base, "polarity": "negated", "predicate": "did"})
    hypo = bc.render_observation({**base, "polarity": "hypothetical", "subject_text": "my brother"})
    assert asserted == '[Caroline, 2023-05-08] plans: sign up for pottery ("I\'m going to sign up for pottery")'
    assert planned == '[Caroline, 2023-05-08] PLANNED (not yet done) plans: sign up for pottery ("I\'m going to sign up for pottery")'
    assert negated.startswith("[Caroline, 2023-05-08] NEGATED (this was not so) did:")
    assert hypo.startswith("[Caroline, 2023-05-08] HYPOTHETICAL (not a fact) my brother plans:")
    no_date = bc.render_observation({"subject_text": "the user", "predicate": "owns", "object_text": "a car",
                                     "polarity": "asserted", "evidence_text": ""})
    assert no_date == "[user] owns: a car"


async def test_stage_renders_planned_claim_explicitly(db, store):
    await store.observe("I will go camping next month", cos=0.9, predicate="plans", obj="go camping",
                        polarity="planned", time_text="next month")
    (item,) = (await bc._stage_observations(db, "camping", CFG_ON)).content
    assert item["text"].startswith("[Caroline, 2023-05-08] PLANNED (not yet done) plans: go camping (when: next month)")
    assert item["polarity"] == "planned"


# --- compression and the prompt ------------------------------------------------------

async def _section(db, store):
    for i in range(4):
        await store.observe(f"I did thing number {i} quietly", cos=0.9 - i * 0.1, obj=f"thing {i}",
                            polarity="negated" if i == 3 else "asserted", day=10 + i)
    return await bc._stage_observations(db, "what did I do", CFG_ON)


async def test_compression_keeps_every_observation_with_its_evidence(db, store):
    from campy.brain.thalamus.compression import build_default_registry
    section = await _section(db, store)
    cfg = {"compression": {"graph_prune_threshold": 0.99}}
    _, router = build_default_registry(cfg)
    out = router.compress_section(section, "what did I do", cfg)
    assert out.variant == "observations" and out.section_type == "semantic"
    lines = out.content[0]["compact"].split("\n")
    assert lines == [c["text"] for c in section.content]
    assert all('("I did thing number' in line for line in lines)
    assert "NEGATED (this was not so)" in lines[-1]


async def test_prompt_describes_the_observations_section_and_survives_compression(db, store):
    from campy.brain.thalamus.compression import build_default_registry
    section = await _section(db, store)
    bundle = bc.ContextBundle(query="q", sections=[section], total_token_estimate=1, token_budget=1, truncated=False)
    raw = ask_mod._bundle_to_prompt(bundle, "what did I do")
    assert "[semantic: claims the user made" in raw and "NEGATED, HYPOTHETICAL and PLANNED" in raw
    assert "related concepts" not in raw
    _, router = build_default_registry({})
    bundle.sections = [router.compress_section(section, "q", {})]
    packed = ask_mod._bundle_to_prompt(bundle, "what did I do")
    assert "[semantic: claims the user made" in packed
    for i in range(4):
        assert f'("I did thing number {i} quietly")' in packed


async def test_run_ask_over_budget_still_sends_the_evidence(db, store, monkeypatch):
    await _section(db, store)
    sent = {}

    class LLM:
        async def achat(self, messages):
            sent["prompt"] = messages[-1]["content"]
            return "ok"

    monkeypatch.setattr(ask_mod, "_get_llm", lambda cfg: LLM())
    cfg = {"observations": {"retrieval": True}, "retrieval": {"conversation_limit": 0}}
    assert await ask_mod.run_ask("what did I do", "s1", db, cfg, capture=False, budget_tokens=1) == "ok"
    assert "I did thing number 0 quietly" in sent["prompt"] and "NEGATED" in sent["prompt"]
