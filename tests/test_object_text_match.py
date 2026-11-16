"""Object-text matching: question words matched by vector to the object text of the subject's own live facts.

Made-up store from tests/test_query_hits.py plus a few extra facts (real capture writes, no model, no benchmark data;
the embedder is a deterministic table). Pins: the flag; that the four facts queries with no texts return exactly the
rows of their frozen pre-change copies (tests/legacy_query_hits_sparql.py), including a fact with two object edges;
the term filter; the constants and the top-k / threshold rule; the union query (text-only rows, no double rows, count,
latest, exists); archived and superseded facts never matching; both subject anchors; the section firing on a text
match alone; more than MAX_FACTS giving no section; the bounded cache; nothing written.
"""

from __future__ import annotations

import importlib
import math
from types import SimpleNamespace

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus.graph.gateway import GraphGateway, NamedQuery, QueryRegistry
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.query_hits import question_terms
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.thalamus import graph_facts as gf
from campy.brain.thalamus import object_text_match as otm
from tests import legacy_query_hits_sparql as legacy
from tests.b564_helpers import NS, World
from tests.test_query_hits import build, fact

ON = {"retrieval": {"graph_facts": True, "object_text_match": True}}
GF_ONLY = {"retrieval": {"graph_facts": True}}
DIM = 384


def _embeddings():
    """The embeddings module as the code under test imports it now (another test file may have swapped the module
    in sys.modules, so a reference taken when this file was collected could be a different object)."""
    return importlib.import_module("campy.brain.hippocampus.graph.embeddings")


def unit(*head):
    v = list(head) + [0.0] * (DIM - len(head))
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def at(cos, axis=1):
    """A unit vector whose cosine with the first basis vector is `cos`."""
    v = [0.0] * DIM
    v[0], v[axis] = cos, math.sqrt(1 - cos * cos)
    return v


class Embedder:
    """Texts in `table` get their vector; any other text gets its own orthogonal basis vector (cosine 0 with the
    table's first axis and with every other text)."""

    def __init__(self, table):
        self.table, self.calls, self.next_axis = dict(table), [], 200

    def __call__(self, texts, model_name=None):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            if t not in self.table:
                v = [0.0] * DIM
                v[self.next_axis] = 1.0
                self.next_axis += 1
                self.table[t] = v
            out.append(self.table[t])
        return out


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    otm._cache.clear()
    monkeypatch.setattr(_embeddings(), "embed", lambda text, model_name=None: unit(1))
    monkeypatch.setattr(_embeddings(), "embed_batch", Embedder({}))
    yield
    otm._cache.clear()


def stub(monkeypatch, table):
    emb = Embedder(table)
    monkeypatch.setattr(_embeddings(), "embed_batch", emb)
    return emb


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "otm.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def update(db, body):
    db.store.update(body)


async def extra(db, gw):
    """The base store plus: a literal-only fact (no object Concept), a fact with TWO object edges, a superseded
    fact, a fact reached only by subject_id, one reached only by HAS_SUBJECT, another speaker's matching text."""
    mids, facts = await build(db, gw)
    w = World(db, gw)
    w.n = 100
    await w.concept("c-tabby", "Tabby")                     # a pet-like object that is of no kind
    spec = {  # key: (speaker, day, quote, object text, object id, predicate)
        "tea": ("Nora", 10, "I drink green tea daily", "green tea", None, "prefers"),
        "twin": ("Nora", 11, "I got a cat and a guitar case", "cat and case", "c-tabby", "owns"),
        "old": ("Nora", 12, "I drank herbal tea", "herbal tea", None, "owns"),
        "new": ("Nora", 13, "Now I drink mint tea", "mint tea", None, "owns"),
        "bysid": ("Nora", 14, "I own an old tent", "old tent", None, "owns"),
        "bysubj": ("Nora", 15, "I own a red kayak", "red kayak", None, "owns"),
        "theo": ("Theo", 16, "I drink green tea too", "green tea", None, "prefers"),
    }
    for key, (speaker, d, quote, text, oid, pred) in spec.items():
        mid = await w.message(quote, day=d, speaker=speaker)
        facts[key] = await fact(db, mid, quote, text, oid, subject_id="c-theo" if key == "theo" else "c-nora",
                                predicate=pred)
    update(db, f"INSERT DATA {{ <{mint_uri('Observation', facts['twin'])}> {NS}HAS_OBJECT> "
               f"<{mint_uri('Concept', 'c-guitar')}> }}")
    update(db, f"INSERT DATA {{ <{mint_uri('Observation', facts['old'])}> {NS}DEPRECATED_BY> "
               f"<{mint_uri('Observation', facts['new'])}> }}")
    # bysid: only the literal subject_id (drop its HAS_SUBJECT); bysubj: only HAS_SUBJECT (drop its subject_id)
    update(db, f"DELETE WHERE {{ <{mint_uri('Observation', facts['bysid'])}> {NS}HAS_SUBJECT> ?s }}")
    update(db, f"DELETE WHERE {{ <{mint_uri('Observation', facts['bysubj'])}> {NS}subject_id> ?s }}")
    return mids, facts


def legacy_gw(db):
    reg = QueryRegistry()
    for name, text in (("facts", legacy.LEGACY_FACTS), ("facts_count", legacy.LEGACY_FACTS_COUNT),
                       ("facts_latest", legacy.LEGACY_FACTS_LATEST), ("facts_exist", legacy.LEGACY_FACTS_EXIST)):
        reg.register(NamedQuery(name="legacy." + name, cypher="MATCH (o:Observation) RETURN o", params=("sid", "kids"),
                                mutating=False, description="frozen pre-change copy", sparql=text))
    return GraphGateway(db, reg)


def observation_ids(rows):
    return [str(r["observation_id"]) for r in rows]


# --- flag ------------------------------------------------------------------------------------------

def test_flag_default_off_and_env():
    assert _DEFAULT_CONFIG["retrieval"]["object_text_match"] is False
    assert not otm.object_text_match_enabled(_DEFAULT_CONFIG)
    cfg = apply_env_overrides({"retrieval": {}}, environ={"CAMPY_OBJECT_TEXT_MATCH": "1"})
    assert otm.object_text_match_enabled(cfg)
    assert "object_text_match" not in {k for p in _DEFAULT_CONFIG.get("profiles", {}).values()
                                       for k in (p.get("retrieval") or {})}


def test_constants_are_not_config_keys():
    assert otm.THRESHOLD == 0.75 and otm.TOP_K == 3 and otm._CACHE_MAX == 4096
    assert not {"threshold", "top_k", "object_text_threshold"} & set(_DEFAULT_CONFIG["retrieval"])


# --- flag off: the existing queries and section are unchanged --------------------------------------

@pytest.mark.parametrize("kids", [["k-pet"], ["k-dog"], ["c-guitar"], ["k-pet", "c-guitar"], ["c-tabby", "c-guitar"], ["k-fish"], []])
async def test_queries_without_texts_equal_the_frozen_copies(db, gw, kids):
    await extra(db, gw)
    old = legacy_gw(db)
    for sid in ("c-nora", "c-theo"):
        for texts in ({}, {"texts": []}):
            assert await gw.run("query_hits.facts", sid=sid, kids=kids, **texts) == \
                await old.run("legacy.facts", sid=sid, kids=kids)
            assert await gw.run("query_hits.facts_latest", sid=sid, kids=kids, **texts) == \
                await old.run("legacy.facts_latest", sid=sid, kids=kids)
            assert await gw.run("query_hits.facts_count", sid=sid, kids=kids, **texts) == \
                await old.run("legacy.facts_count", sid=sid, kids=kids)
            assert await gw.run("query_hits.facts_exist", sid=sid, kids=kids, **texts) == \
                await old.run("legacy.facts_exist", sid=sid, kids=kids)


async def test_two_object_fact_keeps_one_row_per_object(db, gw, ):
    mids, facts = await extra(db, gw)
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=["c-tabby", "c-guitar"])
    twin = [(r["object_id"], r["object_text"]) for r in rows if str(r["observation_id"]) == facts["twin"]]
    assert sorted(twin) == [("c-guitar", "guitar"), ("c-tabby", "Tabby")]   # an id with its own text, never crossed
    assert rows == await legacy_gw(db).run("legacy.facts", sid="c-nora", kids=["c-tabby", "c-guitar"])


async def test_section_flag_off_and_flag_without_matches_are_identical(db, gw, monkeypatch):
    await extra(db, gw)
    stub(monkeypatch, {})                                        # every text orthogonal: nothing matches
    q = "What pets does Nora have?"
    base = await gf.build_graph_facts_section(db, q, GF_ONLY, analysis=SimpleNamespace(shape="list"))
    on = await gf.build_graph_facts_section(db, q, ON, analysis=SimpleNamespace(shape="list"))
    assert base.content == on.content and base.source_node_ids == on.source_node_ids


# --- the term filter ---------------------------------------------------------------------------------

def test_filtered_terms():
    pairs = [("Nora", 0), ("nora", 0), ("What", 1), ("what is", 1), ("go", 2), ("Green  Tea", 3), ("green tea", 3),
             ("of the", 4), ("Hiking trip", 5), ("hiking", 5)]
    assert otm.filtered_terms(pairs, "Nora") == ["green tea", "hiking trip", "hiking"]
    assert otm.filtered_terms(pairs, None) == ["nora", "green tea", "hiking trip", "hiking"]
    assert otm.filtered_terms([("x", 0)], "Nora") == []


async def test_labels_in(db, gw):
    mids, facts = await extra(db, gw)
    w = World(db, gw)
    await w.concept("c-nyc", "NYC")
    await w.concept("c-old", "Old Town")
    update(db, f"INSERT DATA {{ <{mint_uri('Concept', 'c-old')}> {NS}archived> true }}")
    lab = mint_uri("Label", "big-apple")
    update(db, f'INSERT DATA {{ <{lab}> {NS}text> "Big Apple" . <{mint_uri("Concept", "c-nyc")}> {NS}HAS_ALT_LABEL> <{lab}> }}')
    got = await gw.run("query_hits.labels_in", terms=["nyc", "old town", "big apple", "green tea", "biscuit", "tent"])
    assert [str(r["term"]) for r in got] == ["big apple", "biscuit", "nyc", "old town"]


async def test_a_term_that_is_a_label_is_not_matched(db, gw, monkeypatch):
    await extra(db, gw)
    World(db, gw).n = 0
    w = World(db, gw)
    w.n = 200
    await w.concept("c-gt", "Green Tea")             # a Concept with that label: the exact-label read owns the term
    stub(monkeypatch, {"green tea": unit(1), "tea": unit(0, 1)})
    assert await otm.resolve_object_texts(gw, "c-nora", question_terms("Green Tea?"), "Nora") == []


# --- vector rule ---------------------------------------------------------------------------------------

async def test_top_k_threshold_and_ties(db, gw, monkeypatch):
    await extra(db, gw)
    # pool texts of Nora: Biscuit, guitar, pottery class, Mochi, green tea, mint tea, cat and case, old tent,
    # red kayak (Goldie is archived, herbal tea superseded). Term "snack" has these cosines:
    stub(monkeypatch, {"snack": unit(1), "green tea": at(0.80), "mint tea": at(0.75), "old tent": at(0.7499),
                       "red kayak": at(0.90, 2), "Mochi": at(0.78, 3), "guitar": at(0.77, 4), "Biscuit": at(0.76, 5)})
    got = await otm.resolve_object_texts(gw, "c-nora", [("snack", 0)], "Nora")
    # sorted by cosine: kayak .90, green tea .80, Mochi .78 | guitar .77, Biscuit .76, mint tea .75 are cut by TOP_K
    assert got == ["red kayak", "green tea", "Mochi"]
    stub(monkeypatch, {"snack": unit(1), "green tea": at(0.80), "mint tea": at(0.75), "old tent": at(0.7499)})
    otm._cache.clear()
    assert await otm.resolve_object_texts(gw, "c-nora", [("snack", 0)], "Nora") == ["green tea", "mint tea"]
    # equal cosines: the larger text sorts first (tuple sort, reversed)
    stub(monkeypatch, {"snack": unit(1), "green tea": at(0.8, 2), "mint tea": at(0.8, 3)})
    otm._cache.clear()
    assert await otm.resolve_object_texts(gw, "c-nora", [("snack", 0)], "Nora") == ["mint tea", "green tea"]


async def test_resolver_pool_is_the_subjects_live_facts_only(db, gw, monkeypatch):
    await extra(db, gw)
    texts = [str(r["object_text"]) for r in await gw.run("query_hits.object_texts_of_subject", sid="c-nora")]
    assert "Goldie" not in texts and "herbal tea" not in texts            # archived, superseded
    assert "old tent" in texts and "red kayak" in texts                    # both subject anchors
    assert texts == sorted(texts) and len(texts) == len(set(texts))
    assert "pottery class" in texts


# --- the union query -----------------------------------------------------------------------------------

async def test_union_text_only_rows_and_aggregates(db, gw):
    mids, facts = await extra(db, gw)
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=[], texts=["green tea", "pottery class"])
    assert observation_ids(rows) == [facts["pottery"], facts["tea"]]            # oldest first
    tea = rows[1]
    assert tea["object_id"] is None and tea["object_text"] == "green tea" and tea["kinds"] in ("", None)
    assert tea["predicate"] == "prefers" and tea["quote"] == "I drink green tea daily"
    assert str(tea["occurred_at"]).startswith("2023-05-10") and tea["evidence_message_id"] == mids_of(facts, tea)
    count = (await gw.run("query_hits.facts_count", sid="c-nora", kids=[], texts=["green tea", "pottery class"]))[0]
    assert (int(count["objects"]), int(count["facts"])) == (2, 2)
    latest = (await gw.run("query_hits.facts_latest", sid="c-nora", kids=[], texts=["green tea", "pottery class"]))[0]
    assert str(latest["observation_id"]) == facts["tea"]
    assert (await gw.run("query_hits.facts_exist", sid="c-nora", kids=[], texts=["green tea"]))[0]["exists"] is True
    assert (await gw.run("query_hits.facts_exist", sid="c-nora", kids=[], texts=["nope"]))[0]["exists"] is False


def mids_of(facts, row):
    return row["evidence_message_id"]


async def test_union_does_not_double_a_fact_both_branches_reach(db, gw):
    mids, facts = await extra(db, gw)
    both = await gw.run("query_hits.facts", sid="c-nora", kids=["k-pet"], texts=["Biscuit", "Mochi"])
    alone = await gw.run("query_hits.facts", sid="c-nora", kids=["k-pet"])
    assert both == alone
    count = (await gw.run("query_hits.facts_count", sid="c-nora", kids=["k-pet"], texts=["Biscuit"]))[0]
    assert (int(count["objects"]), int(count["facts"])) == (2, 2)
    # a text match on a fact that has an object Concept renders the Concept's text and kinds
    row = (await gw.run("query_hits.facts", sid="c-nora", kids=[], texts=["Biscuit"]))[0]
    assert (row["object_id"], row["object_text"], row["kinds"]) == ("c-biscuit", "Biscuit", "dog")


async def test_union_never_returns_archived_superseded_or_other_subjects(db, gw):
    mids, facts = await extra(db, gw)
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=[], texts=["Goldie", "herbal tea", "mint tea"])
    assert observation_ids(rows) == [facts["new"]]                                # archived and superseded excluded
    theo = await gw.run("query_hits.facts", sid="c-theo", kids=[], texts=["green tea"])
    nora = await gw.run("query_hits.facts", sid="c-nora", kids=[], texts=["green tea"])
    assert observation_ids(theo) == [facts["theo"]] and observation_ids(nora) == [facts["tea"]]
    count = (await gw.run("query_hits.facts_count", sid="c-nora", kids=[], texts=["Goldie", "herbal tea"]))[0]
    assert int(count["facts"]) == 0


async def test_union_subject_anchors(db, gw):
    mids, facts = await extra(db, gw)
    rows = await gw.run("query_hits.facts", sid="c-nora", kids=[], texts=["old tent", "red kayak"])
    assert observation_ids(rows) == [facts["bysid"], facts["bysubj"]]             # subject_id only; HAS_SUBJECT only


# --- the section -----------------------------------------------------------------------------------------

async def test_section_fires_on_a_text_match_alone(db, gw, monkeypatch):
    mids, facts = await extra(db, gw)
    stub(monkeypatch, {"drink": unit(1), "green tea": at(0.9), "pottery class": at(0.8, 2)})
    q = "What does Nora drink?"
    assert await gf.build_graph_facts_section(db, q, GF_ONLY, analysis=None) is None     # no object Concept named
    sec = await gf.build_graph_facts_section(db, q, ON, analysis=SimpleNamespace(shape="list"))
    assert sec.source_node_ids == [facts["pottery"], facts["tea"]]
    lines = sec.content[0]["text"].splitlines()
    assert lines[0] == "[computed: list, 2 rows] Nora → pottery class; green tea"
    assert lines[2] == ('[fact] Nora · prefers · green tea · said 2023-05-10 · "I drink green tea daily"')
    assert await gf.build_graph_facts_section(db, q, {"retrieval": {"object_text_match": True}}, None) is None  # needs graph_facts


async def test_section_union_over_25_gives_none(db, gw, monkeypatch):
    await extra(db, gw)
    stub(monkeypatch, {"drink": unit(1), "green tea": at(0.9), "pottery class": at(0.8, 2)})
    q = "What pets does Nora drink?"                                  # kids alone: 2 facts; union: 4
    assert await gf.build_graph_facts_section(db, q, ON, analysis=None) is not None
    monkeypatch.setattr(gf, "MAX_FACTS", 3)
    assert await gf.build_graph_facts_section(db, q, ON, analysis=None) is None
    assert await gf.build_graph_facts_section(db, q, GF_ONLY, analysis=None) is not None   # kids alone still fits


async def test_embedder_error_falls_back_to_exact_labels(db, gw, monkeypatch):
    await extra(db, gw)

    def boom(texts, model_name=None):
        raise RuntimeError("no embedder")
    monkeypatch.setattr(_embeddings(), "embed_batch", boom)
    q = "What pets does Nora have?"
    base = await gf.build_graph_facts_section(db, q, GF_ONLY, analysis=None)
    on = await gf.build_graph_facts_section(db, q, ON, analysis=None)
    assert on.content == base.content
    assert await gf.build_graph_facts_section(db, "What does Nora drink?", ON, analysis=None) is None


# --- the cache; nothing written ---------------------------------------------------------------------------

def test_cache_is_bounded_lru_and_embeds_each_text_once(monkeypatch):
    emb = stub(monkeypatch, {})
    monkeypatch.setattr(otm, "_CACHE_MAX", 3)
    first = otm._vectors(["a1", "a2", "a3"])
    assert [len(x) for x in first] == [DIM] * 3 and all(abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-12 for v in first)
    otm._vectors(["a1", "a2", "a3", "a1"])
    assert sum(len(c) for c in emb.calls) == 3                       # a repeat is not embedded again
    otm._vectors(["a1", "b1"])                                       # b1 enters, a2 (least recently used) leaves
    assert len(otm._cache) == 3 and (_embeddings().MODEL_NAME, "a2") not in otm._cache
    otm._vectors(["a2"])
    assert sum(len(c) for c in emb.calls) == 5


async def test_resolving_writes_nothing(db, gw, monkeypatch, tmp_path):
    await extra(db, gw)
    stub(monkeypatch, {"drink": unit(1), "green tea": at(0.9)})
    files = sorted(p.name for p in tmp_path.rglob("*"))
    before = sorted(map(str, db._execute_and_collect("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")), key=str)
    assert await otm.resolve_object_texts(gw, "c-nora", question_terms("What does Nora drink?"), "Nora") == ["green tea"]
    after = sorted(map(str, db._execute_and_collect("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")), key=str)
    assert before == after and files == sorted(p.name for p in tmp_path.rglob("*"))
