"""M4.1: graph expansion of the Observation section (`[observations] expand_hops`).

Real Oxigraph store, hand-built embeddings, no model, no LLM. Pins: hop 0 is
byte-identical to before; hop 1 adds Observations about the entities the first
pass reached (dedupe, caps, similarity order), groups the section by entity,
keeps dates and quotes; nothing changes when the conversation is the full
history; the config and env plumbing.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import ask as ask_mod
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
QUESTION = "What might her political leaning be?"


def _vec(cos: float, axis: int) -> list[float]:
    v = [0.0] * DIM
    v[0], v[axis] = cos, math.sqrt(1.0 - cos * cos)
    return v


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    # Looked up at fixture time, as the code under test does: tests/test_b68, b69
    # and b195 swap campy...graph.embeddings in sys.modules, so a module-level
    # import here can be a stale object by the time this runs in a full suite.
    from campy.brain.hippocampus.graph import embeddings as embeddings_mod
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "m41.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def cfg(hops=0, limit=8, expand_limit=6, **extra):
    return {"observations": {"retrieval": True, "observation_limit": limit,
                             "expand_hops": hops, "expand_limit": expand_limit},
            "retrieval": {"conversation_token_budget": 0, **extra}}


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=_vec(0.0, 300 + self.n), gist="Agent", stype="Person", now=T0)
        self.n += 1

    async def observe(self, quote, *, cos, obj, subject="I", subject_id=None, object_id=None,
                      day=8, speaker="Caroline", predicate="did"):
        self.n += 1
        mid = f"m{self.n}"
        text = f"Filler. {quote} More."
        await self.gw.run(
            "capture.create_message", message_id=mid, text_raw=text, embedding=None,
            embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
            created_at=f"2023-05-{day:02d}T12:00:00+00:00")
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker,
                          occurred_at=f"2023-05-{day:02d}T12:00:00+00:00")
        res = await obs.record_observation(self.db, obs.ObservationDraft(
            evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate=predicate,
            object_text=obj, extraction_method="llm", confidence=0.9, subject_id=subject_id,
            object_id=object_id, speaker=speaker, text_raw=f"{subject} - {predicate} - {obj}",
            embedding=_vec(cos, 10 + self.n)))
        assert res.ok, res
        return res.observation_id


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


async def _world(store):
    """Caroline (named in the question) and Melanie; one first-pass hit about Caroline;
    further Caroline facts far from the question; a Melanie fact not reachable."""
    await store.concept("c-car", "Caroline")
    await store.concept("c-mel", "Melanie")
    first = await store.observe("I volunteer at the LGBTQ center", cos=0.8, obj="volunteers at the LGBTQ center",
                                subject_id="c-car", day=8)
    near = await store.observe("I marched at the pride rally", cos=0.2, obj="marched at pride", subject_id="c-car", day=20)
    far = await store.observe("I support equal rights for all", cos=0.1, obj="supports equal rights",
                              subject_id="c-car", day=25)
    other = await store.observe("I paint on weekends", cos=0.25, obj="paints", 
                                subject_id="c-mel", speaker="Melanie", day=9)
    return first, near, far, other


def _ids(section):
    return section.source_node_ids


async def _stage(db, c, q=QUESTION):
    return await bc._stage_observations(db, q, c)


# --- hop 0 ---------------------------------------------------------------------------

async def test_hop0_is_byte_identical_to_a_store_without_the_keys(db, store):
    await _world(store)
    base = {"observations": {"retrieval": True, "observation_limit": 8},
            "retrieval": {"conversation_token_budget": 0}}
    a, b = await _stage(db, base), await _stage(db, cfg(hops=0))
    assert a.content == b.content and a.source_node_ids == b.source_node_ids and a.token_estimate == b.token_estimate
    assert all("About " not in c["text"] for c in a.content)
    assert len(a.content) == 1                                   # only the first-pass hit


# --- hop 1 ---------------------------------------------------------------------------

async def test_hop1_adds_observations_about_the_first_pass_entities(db, store):
    first, near, far, other = await _world(store)
    s = await _stage(db, cfg(hops=1))
    assert set(_ids(s)) == {first, near, far}                    # Melanie's is not reached
    assert other not in _ids(s)
    (item,) = s.content                                          # one entity -> one group
    assert item["entity"] == "Caroline"
    assert item["text"].startswith("About Caroline: [Caroline, 2023-05-08] did: volunteers at the LGBTQ center")
    assert " | [Caroline, 2023-05-20] did: marched at pride" in item["text"]
    assert ' ("I support equal rights for all")' in item["text"]  # quotes kept
    assert item["text"].index("2023-05-08") < item["text"].index("2023-05-20") < item["text"].index("2023-05-25")
    assert item["observation_ids"] == [first, near, far]
    assert s.variant == "observations" and s.token_estimate > 0


async def test_expansion_is_ranked_by_similarity_and_capped(db, store):
    first, near, far, _ = await _world(store)
    s = await _stage(db, cfg(hops=1, expand_limit=1))
    assert set(_ids(s)) == {first, near}                         # nearest of the two extras wins
    s0 = await _stage(db, cfg(hops=1, expand_limit=0))
    assert _ids(s0) == [first] and "About" in s0.content[0]["text"]


async def test_total_never_exceeds_limit_plus_expand_limit(db, store):
    await store.concept("c-car", "Caroline")
    for i in range(14):
        await store.observe(f"I did thing {i} today", cos=0.9 - i * 0.01, obj=f"thing {i}", subject_id="c-car", day=1 + i)
    s = await _stage(db, cfg(hops=1, limit=3, expand_limit=2))
    assert len(_ids(s)) == 5 and len(set(_ids(s))) == 5          # deduped
    assert len(s.content) == 1


async def test_first_pass_observations_are_not_repeated(db, store):
    first, *_ = await _world(store)
    s = await _stage(db, cfg(hops=1))
    assert s.content[0]["text"].count("volunteers at the LGBTQ center") == 1
    assert len(_ids(s)) == len(set(_ids(s)))


async def test_groups_by_entity_and_standalone_observations_stay_alone(db, store):
    await store.concept("c-car", "Caroline")
    await store.concept("c-mel", "Melanie")
    a = await store.observe("I volunteer at the center", cos=0.9, obj="volunteers", subject_id="c-car", day=8)
    b = await store.observe("I paint on weekends", cos=0.8, obj="paints", 
                            subject_id="c-mel", speaker="Melanie", day=9)
    c = await store.observe("The weather was nice", cos=0.7, obj="nice weather", subject="the weather", day=10)
    d = await store.observe("I rallied for equal rights", cos=0.2, obj="rallied", subject_id="c-car", day=21)
    s = await _stage(db, cfg(hops=1))
    texts = [i["text"] for i in s.content]
    assert texts[0].startswith("About Caroline: ") and "rallied" in texts[0] and "volunteers" in texts[0]
    assert texts[1].startswith("About Melanie: ") and "paints" in texts[1]
    assert texts[2].startswith("[Caroline, 2023-05-10]") and "About" not in texts[2]
    assert set(_ids(s)) == {a, b, c, d}


async def test_object_concepts_are_hop_one_entities_too(db, store):
    await store.concept("c-car", "Caroline")
    await store.concept("c-grp", "LGBTQ center")
    a = await store.observe("I volunteer at the LGBTQ center", cos=0.9, obj="volunteers", subject_id="c-car",
                            object_id="c-grp", day=8)
    b = await store.observe("The LGBTQ center hosts a book club", cos=0.2, obj="hosts a book club", subject="LGBTQ center",
                            subject_id="c-grp", speaker="Melanie", day=9)
    s = await _stage(db, cfg(hops=1))
    assert set(_ids(s)) == {a, b}


async def test_rank_order_inside_a_group(db, store):
    first, near, far, _ = await _world(store)
    s = await _stage(db, cfg(hops=1, conversation_order="rank"))
    assert s.content[0]["observation_ids"] == [first, near, far]  # first pass, then similarity
    late = await _stage(db, cfg(hops=1))
    assert late.content[0]["observation_ids"] == [first, near, far]


async def test_hop1_with_no_entities_is_hop0(db, store):
    await store.observe("I volunteer at the center", cos=0.9, obj="volunteers", day=8)
    await store.observe("I paint on weekends", cos=0.8, obj="paints", day=3)
    a, b = await _stage(db, cfg(hops=0)), await _stage(db, cfg(hops=1))
    assert a.content == b.content and a.source_node_ids == b.source_node_ids


async def test_archived_and_superseded_are_skipped(db, store):
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    first, near, far, _ = await _world(store)
    ns = "https://campy.dev/ns#"
    st = db._store if hasattr(db, "_store") else db.store
    st.update(f"DELETE {{ <{mint_uri('Observation', near)}> <{ns}archived> false }} "
              f"INSERT {{ <{mint_uri('Observation', near)}> <{ns}archived> true }} WHERE {{}}")
    st.update(f"INSERT DATA {{ <{mint_uri('Observation', far)}> <{ns}superseded_by> \"x\" }}")
    s = await _stage(db, cfg(hops=1))
    assert _ids(s) == [first]


# --- gateway queries ----------------------------------------------------------------

async def test_entity_query_and_empty_inputs(gw, store):
    first, near, far, other = await _world(store)
    rows = await gw.run("thalamus.bundle_observation_entities", observation_ids=[first, other])
    got = {(r["observation_id"], r["concept_id"], r["concept_text"]) for r in rows}
    assert got == {(first, "c-car", "Caroline"), (other, "c-mel", "Melanie")}
    assert await gw.run("thalamus.bundle_observation_entities", observation_ids=[]) == []
    assert await gw.run("thalamus.bundle_observations_expand", query_embedding=Q, entity_ids=[],
                        exclude_ids=[], limit=5) == []
    rows = await gw.run("thalamus.bundle_observations_expand", query_embedding=Q, entity_ids=["c-car"],
                        exclude_ids=[first], limit=5)
    assert [r["observation_id"] for r in rows] == [near, far]


# --- full history, bundle, prompt --------------------------------------------------

async def test_full_history_bundle_unchanged_by_expansion(db, gw, store):
    await _world(store)
    on = {"observations": {"retrieval": True, "expand_hops": 1}}   # default budget: tiny store fits
    off = {"observations": {"retrieval": True, "expand_hops": 0}}
    b1, b0 = await bc.compile_bundle(QUESTION, db, on), await bc.compile_bundle(QUESTION, db, off)
    assert [(s.section_type, s.content, s.variant) for s in b1.sections] == \
           [(s.section_type, s.content, s.variant) for s in b0.sections]


async def test_compile_bundle_uses_expansion_when_history_is_partial(db, store):
    first, near, far, _ = await _world(store)
    b = await bc.compile_bundle(QUESTION, db, cfg(hops=1))
    (sem,) = [s for s in b.sections if s.section_type == "semantic"]
    assert sem.variant == "observations" and set(sem.source_node_ids) == {first, near, far}


async def test_group_survives_compression_and_prompt(db, store):
    from campy.brain.thalamus.compression import build_default_registry
    await _world(store)
    s = await _stage(db, cfg(hops=1))
    _, router = build_default_registry({})
    packed = router.compress_section(s, "q", {"compression": {"graph_prune_threshold": 0.99}})
    bundle = bc.ContextBundle(query="q", sections=[packed], total_token_estimate=1, token_budget=1, truncated=False)
    prompt = ask_mod._bundle_to_prompt(bundle, "q")
    assert "About Caroline: [Caroline, 2023-05-08]" in prompt and "'About X:' gathers" in prompt
    assert '("I support equal rights for all")' in prompt
    s0 = await _stage(db, cfg(hops=0))
    p0 = ask_mod._bundle_to_prompt(bc.ContextBundle(query="q", sections=[s0], total_token_estimate=1,
                                                   token_budget=1, truncated=False), "q")
    assert "'About X:' gathers" not in p0


# --- config -------------------------------------------------------------------------

def test_config_defaults_and_env():
    assert _DEFAULT_CONFIG["observations"]["expand_hops"] == 0
    assert _DEFAULT_CONFIG["observations"]["expand_limit"] == 6
    assert obs.observation_expand_hops({}) == 0 and obs.observation_expand_hops(_DEFAULT_CONFIG) == 0
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_EXPAND_HOPS": "1"})["observations"]["expand_hops"] == 1
    assert obs.observation_expand_hops({"observations": {"expand_hops": 5}}) == 1
    assert obs.observation_expand_hops({"observations": {"expand_hops": "x"}}) == 0
    assert obs.observation_expand_limit({"observations": {"expand_limit": 3}}) == 3
