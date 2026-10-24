"""B508: a SKOS vocabulary for kinds (flag CAMPY_SKOS_VOCAB, default off).

Fake LLM, real Oxigraph store, no model. Pins:
- the flag and its env override; flag off = B504 exactly (IS_A, no kind scheme, no new edges);
- consolidation (rule, no model): "kit", "model kit", "model kits", "Model Kit" end as one kind
  "model kit" (altLabel "model kits") narrower than "kit"; the order they arrive in does not matter;
- close match: a near-duplicate kind gets an advisory CLOSE_MATCH, is NOT merged, and the walk ignores it;
- instance-of and broader are different relations (entity -INSTANCE_OF-> kind, kind -BROADER-> kind),
  including for `is_a` claims;
- the walk reaches narrower kinds and their instances; flag off it does not;
- the SHACL shapes accept a conforming vocabulary and reject the broken ones;
- the structure report's kind metrics on a small fixture.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import concept_links as cl
from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.shapes import validator as sv
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.thalamus import bundle_compiler as bc

DIM = 384
NS = "<https://campy.dev/ns#"
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600,
                         "retrieval": False, "entities": True},
        "retrieval": {"conversation_token_budget": 0}}


def cfg(*, skos=True, linking=True, close=0.0):
    return {**BASE, "retrieval": {"graph_linking": linking, "graph_linking_limit": 12,
                                  "conversation_token_budget": 0,
                                  "skos_vocab": skos, "skos_closematch_threshold": close}}


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    """Every text gets its own axis (so nothing is a close match) unless a test overrides."""
    seen: dict[str, int] = {}

    def embed(text, model_name=None):
        return _unit(seen.setdefault(text.casefold(), len(seen) % DIM))

    monkeypatch.setattr(embeddings_mod, "embed", embed)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b508.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class LLM:
    def __init__(self, *items):
        self.reply = json.dumps(list(items))

    def chat(self, messages, **kwargs):
        return self.reply


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def message(self, text, *, day=3):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker="Sam", occurred_at=stamp)
        return mid

    async def label_of(self):
        return {r["concept_id"]: r["text_raw"] for r in await self.gw.run("concept_links.live_concepts")}

    async def edges(self, edge):
        """Edge pairs as (from label, to label)."""
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        names = await self.label_of()
        return {(names.get(str(r["s"]).rsplit("/", 1)[-1]), names.get(str(r["o"]).rsplit("/", 1)[-1])) for r in rows}

    async def kinds(self):
        return {k.pref: k for k in (await kinds_mod.load_kinds(self.gw)).values()}

    async def concepts(self):
        return set((await self.label_of()).values())


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


def claim(text, entity, kind, **extra):
    q = text.rstrip(".")
    return {"subject": "I", "predicate": "did", "object": q, "time": None, "polarity": "asserted",
            "quote": q, "confidence": 0.9, "object_entity": entity, "object_kind": kind, **extra}


async def feed(db, store, config, text, entity, kind, day=3):
    mid = await store.message(text, day=day)
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, config, LLM(claim(text, entity, kind)), mid, stats)
    return stats


# --- flag ---------------------------------------------------------------------------

def test_flag_default_off_env_on_and_closematch_default():
    assert _DEFAULT_CONFIG["retrieval"]["skos_vocab"] is True   # B514
    assert kinds_mod.skos_vocab_enabled(None) is False
    assert kinds_mod.skos_vocab_enabled({"retrieval": {"skos_vocab": True}}) is True
    assert kinds_mod.closematch_threshold(_DEFAULT_CONFIG) == 0.90
    assert kinds_mod.closematch_threshold({"retrieval": {"skos_closematch_threshold": 0}}) == 0.0
    on = apply_env_overrides({"retrieval": {}}, {"CAMPY_SKOS_VOCAB": "1"})
    assert on["retrieval"]["skos_vocab"] is True


# --- the rule (pure) -----------------------------------------------------------------

def _kinds(**labels):
    return {cid: kinds_mod.Kind(cid, pref) for cid, pref in labels.items()}


def test_plan_exact_by_normalised_label_case_plural_article():
    k = _kinds(a="model kit")
    for surface in ("Model Kit", "model kits", "a model kit", "the Model Kits"):
        p = kinds_mod.plan_kind(surface, k)
        assert p.exact == "a" and p.exact_via == "pref"


def test_plan_exact_by_altlabel():
    k = _kinds(a="model kit")
    k["a"].alts.append("scale kit")
    p = kinds_mod.plan_kind("scale kits", k)
    assert p.exact == "a" and p.exact_via == "alt"


def test_plan_head_noun_containment_picks_the_longest_suffix():
    k = _kinds(a="kit", b="model kit")
    p = kinds_mod.plan_kind("plastic model kit", k)
    assert p.exact is None and p.broader == ["b"]


def test_plan_new_short_kind_adopts_existing_longer_kinds():
    k = _kinds(b="model kit", c="plastic model kit")
    k["c"].broader.add("b")                     # already hangs under a more specific kind
    p = kinds_mod.plan_kind("kit", k)
    assert p.broader == [] and p.narrower == ["b"]


def test_plan_does_not_match_a_prefix_or_an_inner_word():
    k = _kinds(a="kit", b="model")
    p = kinds_mod.plan_kind("kit model", k)       # head noun is "model": suffix "model" matches b
    assert p.broader == ["b"] and p.exact is None
    p = kinds_mod.plan_kind("kitchen", k)
    assert p.exact is None and p.broader == [] and p.narrower == []


# --- consolidation through the write path ----------------------------------------------

TURNS = [("Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "kit"),
         ("Finished the Tamiya Spitfire.", "Tamiya Spitfire", "model kit"),
         ("Started a Tiger I tank.", "Tiger I", "model kits"),
         ("Bought a Hasegawa Zero.", "Hasegawa Zero", "Model Kit")]


async def test_four_spellings_end_as_a_kit_and_a_narrower_model_kit(db, store):
    for i, (text, ent, kind) in enumerate(TURNS):
        await feed(db, store, cfg(), text, ent, kind, day=3 + i)
    kinds = await store.kinds()
    assert set(kinds) == {"kit", "model kit"}
    assert kinds["model kit"].alts == ["model kits"]          # case-only "Model Kit" is not a wording
    assert await store.edges("BROADER") == {("model kit", "kit")}
    assert await store.edges("INSTANCE_OF") == {
        ("Revell F-15 Eagle", "kit"), ("Tamiya Spitfire", "model kit"),
        ("Tiger I", "model kit"), ("Hasegawa Zero", "model kit")}
    assert await store.edges("IS_A") == set()                 # the flag moves IS_A to the two relations
    assert await store.edges("CLOSE_MATCH") == set()


async def test_order_does_not_matter_the_short_kind_adopts_the_long_one(db, store):
    for i, (text, ent, kind) in enumerate(reversed(TURNS)):
        await feed(db, store, cfg(), text, ent, kind, day=3 + i)
    # the first wording seen is the prefLabel ("Model Kit" here); the rest accumulate as altLabels
    assert {k.casefold() for k in await store.kinds()} == {"kit", "model kit"}
    assert {(a.casefold(), b.casefold()) for a, b in await store.edges("BROADER")} == {("model kit", "kit")}


async def test_three_levels_chain_and_are_not_flattened(db, store):
    await feed(db, store, cfg(), "Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "plastic model kit")
    await feed(db, store, cfg(), "Finished the Tamiya Spitfire.", "Tamiya Spitfire", "model kit", day=4)
    await feed(db, store, cfg(), "Started a Tiger I tank.", "Tiger I", "kit", day=5)
    edges = await store.edges("BROADER")
    assert ("plastic model kit", "model kit") in edges and ("model kit", "kit") in edges


async def test_a_kind_is_a_skos_concept_in_the_scheme_and_the_entity_is_not(db, gw, store):
    await feed(db, store, cfg(), *TURNS[1])
    rows = db._execute_and_collect(f'SELECT ?t WHERE {{ ?c {NS}kind_scheme> "kind" ; {NS}text_raw> ?t }}')
    assert [str(r["t"]) for r in rows] == ["model kit"]
    assert "Tamiya Spitfire" not in {k for k in await store.kinds()}


async def test_a_kind_proposed_under_a_kind_is_broader_not_instance(db, store):
    await feed(db, store, cfg(), "Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "model kit")
    await feed(db, store, cfg(), "I love model kits.", "model kits", "hobby item", day=4)
    assert await store.edges("BROADER") == {("model kit", "hobby item")}
    assert ("model kit", "hobby item") not in await store.edges("INSTANCE_OF")


# --- close match is advisory ----------------------------------------------------------------

async def test_close_match_is_recorded_not_merged_and_not_walked(db, gw, store, monkeypatch):
    near = _unit(0)
    near2 = [0.0] * DIM
    near2[0], near2[1] = 0.97, 0.243            # cosine 0.97 to `near`
    vec = {"scale model": near, "plane replica": near2}
    monkeypatch.setattr(embeddings_mod, "embed",
                        lambda text, model_name=None: vec.get(text.casefold(), _unit(DIM - 1)))
    c = cfg(close=0.90)
    await feed(db, store, c, "Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "scale model")
    await feed(db, store, c, "Finished the Tamiya Spitfire.", "Tamiya Spitfire", "plane replica", day=4)
    assert set(await store.kinds()) == {"scale model", "plane replica"}      # two kinds, not merged
    assert await store.edges("CLOSE_MATCH") == {("plane replica", "scale model")}
    assert await store.edges("BROADER") == set()
    assert all(k.alts == [] for k in (await store.kinds()).values())
    # the walk from one kind does not reach the other kind's instance
    ids = {v: k for k, v in (await store.label_of()).items()}
    rows = await gw.run("thalamus.bundle_concept_walk", concept_ids=[ids["scale model"]],
                        limit=12, exclude=[], skos=True)
    texts = " ".join(str(r.get("text") or r.get("object_text") or "") for r in rows)
    assert "Revell" in texts and "Spitfire" not in texts


async def test_close_match_off_at_zero(db, store, monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: _unit(0))
    await feed(db, store, cfg(close=0.0), "Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "scale model")
    await feed(db, store, cfg(close=0.0), "Finished the Tamiya Spitfire.", "Tamiya Spitfire", "plane replica", day=4)
    assert await store.edges("CLOSE_MATCH") == set()


# --- is_a claims split by what the subject is ---------------------------------------------

async def _concept(gw, cid, text):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=_unit(len(cid)),
                 gist="Entity", stype="Thing", now="2023-05-01T00:00:00+00:00")


async def test_is_a_claim_instance_vs_subtype(db, gw, store):
    for cid, text in (("c-tiger", "Tiger I"), ("c-tank", "tank"), ("c-vehicle", "vehicle")):
        await _concept(gw, cid, text)
    await cl.link_observation_concepts(gw, "o1", None, subject_text="Tiger I", predicate="is_a",
                                       object_text="tank", skos=True)
    await cl.link_observation_concepts(gw, "o2", None, subject_text="tank", predicate="is_a",
                                       object_text="vehicle", skos=True)
    assert await store.edges("INSTANCE_OF") == {("Tiger I", "tank")}
    assert await store.edges("BROADER") == {("tank", "vehicle")}
    assert await store.edges("IS_A") == set()
    await cl.link_observation_concepts(gw, "o3", None, subject_text="Tiger I", predicate="is_a",
                                       object_text="tank", skos=False)
    assert await store.edges("IS_A") == {("Tiger I", "tank")}                # flag off: unchanged


# --- the walk -----------------------------------------------------------------------------

SESSIONS = [("Picked up a Revell F-15 Eagle.", "Revell F-15 Eagle", "plastic model kit"),
            ("Finished the Tamiya Spitfire.", "Tamiya Spitfire", "model kit"),
            ("Started a Tiger I tank.", "Tiger I", "kit"),
            ("Walked Rex by the lake.", "Rex", "pet")]


async def _texts(db, config, question):
    bundle = await bc.compile_bundle(question, db, config)
    sections = [s for s in bundle.sections if s.section_type == "linked"]
    if not sections:
        return []
    return [c["text"] for c in sections[0].content if c["type"] == "Message"]


async def _populate(db, store, config):
    for i, (text, ent, kind) in enumerate(SESSIONS):
        await feed(db, store, config, text, ent, kind, day=3 + 2 * i)


async def test_walk_from_a_broad_kind_reaches_every_narrower_kinds_instances(db, store):
    await _populate(db, store, cfg())
    turns = await _texts(db, cfg(), "How many kits do I own?")
    joined = " ".join(turns)
    assert "Revell" in joined and "Spitfire" in joined and "Tiger" in joined and "lake" not in joined


async def test_walk_from_a_middle_kind_reaches_the_narrower_one(db, store):
    await _populate(db, store, cfg())
    joined = " ".join(await _texts(db, cfg(), "How many model kits do I own?"))
    assert "Revell" in joined and "Spitfire" in joined and "lake" not in joined


async def test_flag_off_behaves_as_b504(db, store):
    off = cfg(skos=False)
    await _populate(db, store, off)
    assert await store.edges("INSTANCE_OF") == set() and await store.edges("BROADER") == set()
    assert await store.edges("CLOSE_MATCH") == set()
    # B504 kept its single IS_A and no kind scheme
    assert len(await store.edges("IS_A")) == 4
    assert (await store.kinds()) == {}
    # the walk from "kit" reaches only what hangs on it (Tiger), as before
    joined = " ".join(await _texts(db, off, "How many kits do I own?"))
    assert "Tiger" in joined and "Revell" not in joined


# --- shapes ---------------------------------------------------------------------------------

def _g(*triples_spec):
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, XSD

    campy, skos = Namespace(sv.NS), Namespace(sv.SKOS_NS)
    g = Graph()

    def c(name, label=None, kind=False, alts=()):
        u = URIRef(f"https://campy.dev/id/Concept/{name}")
        g.add((u, RDF.type, campy.Concept))
        g.add((u, campy.concept_id, Literal(name)))
        g.add((u, campy.archived, Literal(False, datatype=XSD.boolean)))
        g.add((u, skos.prefLabel, Literal(label if label is not None else name.replace("-", " "))))
        if kind:
            g.add((u, campy.kind_scheme, Literal("kind")))
        for a in alts:
            g.add((u, skos.altLabel, Literal(a)))
        return u

    return g, c, campy, skos, URIRef, Literal


def _fails(g):
    report, _ = sv.validate_graph(g)
    return {f.shape for f in report.failures if f.severity == "Violation"}, \
           {f.shape for f in report.failures if f.severity == "Warning"}


def test_shapes_accept_a_conforming_vocabulary():
    g, c, campy, skos, _, _ = _g()
    kit, mk, eagle = c("kit", kind=True), c("model-kit", kind=True, alts=["model kits"]), c("eagle")
    g.add((mk, campy.BROADER, kit))
    g.add((eagle, campy.INSTANCE_OF, mk))
    bad, warn = _fails(g)
    assert bad == set() and warn == set()


def test_shapes_accept_a_graph_already_written_in_skos():
    g, c, campy, skos, _, _ = _g()
    kit, mk = c("kit", kind=True), c("model-kit", kind=True)
    g.add((mk, skos.broader, kit))
    assert _fails(g) == (set(), set())


def test_shapes_reject_a_kind_outside_the_scheme():
    g, c, campy, *_ = _g()
    eagle, mk = c("eagle"), c("model-kit")                     # model-kit has no kind_scheme
    g.add((eagle, campy.INSTANCE_OF, mk))
    assert "kind in scheme" in _fails(g)[0]


def test_shapes_reject_broader_to_something_that_is_not_a_concept():
    g, c, campy, skos, URIRef, _ = _g()
    mk = c("model-kit", kind=True)
    g.add((mk, campy.BROADER, URIRef("https://campy.dev/id/Message/m1")))
    assert "broader" in _fails(g)[0]


def test_shapes_reject_self_broader_and_instance_and_broader_on_one_pair():
    g, c, campy, *_ = _g()
    a, b = c("a-kind", kind=True), c("b-kind", kind=True)
    g.add((a, campy.BROADER, a))
    assert "BroaderNotSelf" in _fails(g)[0]
    g2, c2, campy2, *_ = _g()
    x, y = c2("x-kind", kind=True), c2("y-kind", kind=True)
    g2.add((x, campy2.BROADER, y))
    g2.add((x, campy2.INSTANCE_OF, y))
    assert "InstanceOfAndBroader" in _fails(g2)[0]


def test_shapes_reject_bad_alt_labels():
    g, c, *_ = _g()
    c("model-kit", kind=True, alts=["Model Kit"])               # repeats the prefLabel
    c("scale-kit", kind=True, alts=["the"])                     # stopword-only
    bad, _ = _fails(g)
    assert {"AltLabelRepeatsPrefLabel", "altLabel content"} <= bad


def test_shapes_reject_a_concept_without_a_pref_label():
    g, c, campy, *_ = _g()
    from rdflib import URIRef
    from rdflib.namespace import RDF
    u = URIRef("https://campy.dev/id/Concept/none")
    g.add((u, RDF.type, campy.Concept))
    assert "prefLabel" in _fails(g)[0]


def test_an_instance_that_is_itself_a_kind_is_only_a_warning():
    g, c, campy, *_ = _g()
    a, b = c("spitfire", kind=True), c("model-kit", kind=True)
    g.add((a, campy.INSTANCE_OF, b))
    bad, warn = _fails(g)
    assert bad == set() and "instance is a kind" in warn


def test_the_alignment_file_matches_the_projection_and_the_schema():
    from rdflib import Namespace
    from rdflib.namespace import RDFS

    from campy.brain.hippocampus.schema import REL_TABLES
    campy, skos = Namespace(sv.NS), Namespace(sv.SKOS_NS)
    v = sv.load_vocab()
    assert (campy.BROADER, RDFS.subPropertyOf, skos.broader) in v
    assert (campy.CLOSE_MATCH, RDFS.subPropertyOf, skos.closeMatch) in v
    ddl = " ".join(REL_TABLES)
    for edge in ("INSTANCE_OF", "BROADER", "CLOSE_MATCH"):
        assert f"EXISTS {edge} (FROM Concept TO Concept" in ddl


# --- structure report -------------------------------------------------------------------------

def _load_report():
    path = Path(__file__).resolve().parent.parent / "scripts" / "graph_structure_report.py"
    spec = importlib.util.spec_from_file_location("graph_structure_report_b508", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _fixture_store(tmp_path, *, skos):
    home = tmp_path / ("on" if skos else "off")
    home.mkdir()
    client = OxigraphClient(home / "brain.db")
    store = Store(client, GraphGateway(client, REGISTRY))
    c = cfg(skos=skos)
    for i, (text, ent, kind) in enumerate(TURNS):
        await feed(client, store, c, text, ent, kind, day=3 + i)
    client.close()
    return home


async def test_report_kind_metrics_flag_on_and_off(tmp_path):
    rep = _load_report()
    on = rep.measure(await _fixture_store(tmp_path, skos=True), shacl=True)
    assert on["kinds"] == 2 and on["kinds_with_alt"] == 1 and on["kinds_duplicate"] == 0
    assert on["entities"] == 4 and on["entities_with_kind"] == 4
    assert on["shacl"]["Concept"]["nonconforming"] == 0
    off = rep.measure(await _fixture_store(tmp_path, skos=False), shacl=False)
    # B504: "kit" and "model kit" are two unrelated kinds, no altLabels, every entity under an IS_A
    assert off["kinds"] == 2 and off["kinds_with_alt"] == 0 and off["entities_with_kind"] == 4


async def test_report_counts_duplicate_kinds(tmp_path, gw=None):
    home = tmp_path / "dup"
    home.mkdir()
    client = OxigraphClient(home / "brain.db")
    gw = GraphGateway(client, REGISTRY)
    for cid, text in (("k1", "scale kit"), ("k2", "model kit"), ("e1", "Eagle")):
        await _concept(gw, cid, text)
    for cid in ("k1", "k2"):
        await kinds_mod.mark_kind(gw, cid)
    await kinds_mod.add_alt_label(gw, kinds_mod.Kind("k1", "scale kit"), "model kits")   # k1 also called "model kits"
    await kinds_mod.link_instance_of(gw, "e1", "k1")
    client.close()
    m = _load_report().measure(home, shacl=False)
    assert m["kinds"] == 2 and m["kinds_duplicate"] == 1 and m["kinds_with_alt"] == 1
