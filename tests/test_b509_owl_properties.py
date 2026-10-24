"""B509: OWL attribute properties; functional properties drive supersession (flag CAMPY_OWL_PROPERTIES).

Real Oxigraph store, no model. Pins:
- the flag and its env override; flag off = the base writer (no property nodes, B499 string rule intact);
- consolidation: "personal best 5K" and "5K personal best time" are ONE property (altLabel kept),
  "personal best" stays separate but is recorded as broader;
- typed values are stored apart from the name (number, money, date);
- a functional property (seed, modifier) supersedes: newer wins, out-of-order marks the incoming row,
  chains, other subjects untouched, DEPRECATED_BY written;
- a non-functional property never supersedes ("hobby: tennis" then "hobby: chess");
- the model's cardinality advice alone never makes a property functional; advice + a different later
  value + replacement language does;
- SHACL: two live values of a functional property are a violation, and fine once superseded;
- reasoning: a skos:broader cycle of any length is found, redundant edges are reported;
- the structure report's attribute metrics.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import attribute_properties as ap
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.shapes import validator as sv
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
OWL = {"observations": {"owl_properties": True}}
NS = "https://campy.dev/ns#"


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b509.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def attr(self, obj, date, *, config=OWL, text=None, advice=None, subject="I", speaker="Alex",
                   predicate="has_attribute", polarity="asserted", supersede=False):
        self.n += 1
        mid = f"m{self.n}"
        quote = text or (f"I think about {obj}" if subject == "I" else f"{subject} thinks about {obj}")
        body = f"Hello. {quote}. Bye."
        stamp = f"{date}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=body, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(body), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        res = await obs.record_observation(self.db, obs.ObservationDraft(
            evidence_ref=mid, evidence_text=quote, subject_text=subject, predicate=predicate,
            object_text=obj, extraction_method="llm", confidence=0.9, polarity=polarity, speaker=speaker,
            text_raw=f"{speaker} - {predicate} - {obj}", embedding=Q, attr_cardinality=advice),
            config=config, supersede=supersede)
        assert res.status == "created", res
        return res.observation_id

    async def row(self, oid):
        return await obs.get_observation(self.db, oid)

    async def props(self):
        return await ap.load_properties(self.gw)

    async def prop_of(self, oid):
        rows = await self.gw.run("properties.property_of", oid=oid)
        return dict(rows[0])["property_id"] if rows else None

    def edges(self, name):
        rows = self.db._execute_and_collect(f"SELECT ?a ?b WHERE {{ ?a <{NS}{name}> ?b }}")
        return [(str(r["a"]).rsplit("/", 1)[-1], str(r["b"]).rsplit("/", 1)[-1]) for r in rows]


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


# --- flag --------------------------------------------------------------------------------

def test_flag_default_off_env_on():
    assert _DEFAULT_CONFIG["observations"]["owl_properties"] is True   # B514
    assert obs.owl_properties_enabled(None) is False
    assert ap.owl_properties_enabled({"observations": {"owl_properties": True}}) is True
    on = apply_env_overrides({"observations": {}}, {"CAMPY_OWL_PROPERTIES": "1"})
    assert on["observations"]["owl_properties"] is True


def test_prompt_is_byte_identical_with_the_flag_off():
    a = ex.build_messages("I run a lot.", "Alex", "2023-05-01")
    b = ex.build_messages("I run a lot.", "Alex", "2023-05-01", cardinality=False)
    assert a == b and "cardinality" not in a[1]["content"]
    assert '"cardinality"' in ex.build_messages("I run.", "Alex", "2023-05-01", cardinality=True)[1]["content"]


async def test_flag_off_writes_no_property_and_keeps_the_b499_rule(store):
    a = await store.attr("age: 30", "2023-01-01", config=None, supersede=True)
    b = await store.attr("age: 31", "2023-03-01", config=None, supersede=True)
    assert await store.props() == {}
    assert store.edges("HAS_PROPERTY") == []
    assert (await store.row(a))["superseded_by"] == b               # B499's string rule, unchanged
    assert "attr_value" not in (await store.row(a)) or not (await store.row(a)).get("attr_value")


# --- consolidation -------------------------------------------------------------------------

async def test_personal_best_wordings_are_one_property(store):
    a = await store.attr("personal best 5K: 27:12", "2023-05-01")
    b = await store.attr("5K personal best time: 25:50", "2023-06-10")
    assert await store.prop_of(a) == await store.prop_of(b)
    props = await store.props()
    assert len(props) == 1
    p = props[await store.prop_of(a)]
    assert p.alts == ["5K personal best time"] and p.pref == "personal best 5K"
    assert p.functional_basis == "modifier"                      # contains the "personal best" modifier
    assert (await store.row(a))["superseded_by"] == b            # so the newer value replaced it


async def test_containment_is_recorded_not_merged(store):
    wide = await store.attr("personal best: 20:10", "2023-05-01")
    narrow = await store.attr("5K personal best: 25:50", "2023-05-02")
    wp, np_ = await store.prop_of(wide), await store.prop_of(narrow)
    assert wp != np_
    assert (np_, wp) in store.edges("BROADER")
    # order independent: the broader name arriving later still gets the narrower one linked up
    s2 = Store(store.db, store.gw)
    s2.n = 100
    other = await s2.attr("marathon pace: 8:00", "2023-05-03")
    broader = await s2.attr("pace: 9:00", "2023-05-04")
    assert (await s2.prop_of(other), await s2.prop_of(broader)) in s2.edges("BROADER")


async def test_seed_wordings_resolve_to_the_seed(store):
    a = await store.attr("job: nurse", "2023-01-01")
    b = await store.attr("occupation: doctor", "2023-02-01")
    c = await store.attr("current job: surgeon", "2023-03-01")
    assert {await store.prop_of(x) for x in (a, b, c)} == {"occupation"}
    p = (await store.props())["occupation"]
    assert p.functional and p.functional_basis is None            # functional by the vocabulary file alone


# --- typed values ---------------------------------------------------------------------------

async def test_value_is_stored_apart_from_the_name_and_typed(store):
    sal = await store.attr("salary: $85,000", "2023-01-01")
    age = await store.attr("age: 30", "2023-01-01")
    when = await store.attr("started: 2023-05-02", "2023-05-03")
    word = await store.attr("hobby: tennis", "2023-05-03")
    rows = {o: store.db._execute_and_collect(
        f"SELECT ?v ?k ?n ?u ?t WHERE {{ ?o <{NS}observation_id> '{o}' . OPTIONAL {{ ?o <{NS}attr_value> ?v }} "
        f"OPTIONAL {{ ?o <{NS}attr_value_kind> ?k }} OPTIONAL {{ ?o <{NS}attr_value_num> ?n }} "
        f"OPTIONAL {{ ?o <{NS}attr_value_unit> ?u }} OPTIONAL {{ ?o <{NS}attr_value_time> ?t }} }}")[0]
        for o in (sal, age, when, word)}
    assert (rows[sal]["v"], rows[sal]["k"], float(rows[sal]["n"]), rows[sal]["u"]) == ("$85,000", "money", 85000.0, "USD")
    assert (rows[age]["k"], float(rows[age]["n"])) == ("number", 30.0)
    assert rows[when]["k"] == "date" and str(rows[when]["t"])[:10] == "2023-05-02"
    assert (rows[word]["k"], rows[word]["n"]) == ("text", None)


# --- supersession ------------------------------------------------------------------------------

async def test_functional_property_newer_value_supersedes(store):
    old = await store.attr("age: 30", "2023-01-01")
    new = await store.attr("age: 31", "2023-06-01")
    o, n = await store.row(old), await store.row(new)
    assert o["superseded_by"] == new and str(o["superseded_at"])[:10] == "2023-06-01"
    assert not n.get("superseded_by")
    assert store.edges("DEPRECATED_BY") == [(old, new)]


async def test_functional_out_of_order_marks_the_incoming_row(store):
    new = await store.attr("residence: Denver", "2023-06-01")
    old = await store.attr("residence: Austin", "2023-01-01")
    assert (await store.row(old))["superseded_by"] == new
    assert not (await store.row(new)).get("superseded_by")
    assert store.edges("DEPRECATED_BY") == [(old, new)]


async def test_functional_chain_and_other_subjects(store):
    a = await store.attr("employer: Acme", "2023-01-01")
    b = await store.attr("employer: Globex", "2023-02-01")
    c = await store.attr("employer: Initech", "2023-03-01")
    other = await store.attr("employer: Hooli", "2023-04-01", subject="Maya", speaker="Alex")
    assert (await store.row(a))["superseded_by"] == b
    assert (await store.row(b))["superseded_by"] == c
    assert not (await store.row(c)).get("superseded_by") and not (await store.row(other)).get("superseded_by")


async def test_same_value_restated_does_not_supersede(store):
    a = await store.attr("age: 30", "2023-01-01")
    b = await store.attr("age: 30.0", "2023-02-01")
    assert not (await store.row(a)).get("superseded_by") and not (await store.row(b)).get("superseded_by")


async def test_non_functional_property_never_supersedes(store):
    a = await store.attr("hobby: tennis", "2023-01-01")
    b = await store.attr("hobby: chess", "2023-06-01")
    c = await store.attr("places visited: Lisbon", "2023-01-01")
    d = await store.attr("places visited: Oslo", "2023-06-01")
    for o in (a, b, c, d):
        assert not (await store.row(o)).get("superseded_by")
    assert store.edges("DEPRECATED_BY") == []
    # B499's string rule WOULD have superseded here; with the property flag on it does not run
    s2 = Store(store.db, store.gw)
    s2.n = 50
    x = await s2.attr("pastime: golf", "2023-01-01", config=None, supersede=True)
    y = await s2.attr("pastime: yoga", "2023-06-01", config=None, supersede=True)
    assert (await s2.row(x))["superseded_by"] == y


async def test_favorite_x_modifier_is_functional(store):
    a = await store.attr("favorite food: pizza", "2023-01-01")
    b = await store.attr("favourite food: sushi", "2023-06-01")
    assert await store.prop_of(a) == await store.prop_of(b)
    assert (await store.row(a))["superseded_by"] == b


async def test_negated_value_neither_supersedes_nor_is_superseded(store):
    a = await store.attr("residence: Austin", "2023-01-01")
    b = await store.attr("residence: Denver", "2023-06-01", polarity="negated")
    assert not (await store.row(a)).get("superseded_by") and not (await store.row(b)).get("superseded_by")


# --- the model advises, rules decide ---------------------------------------------------------

async def test_advice_alone_does_not_make_a_property_functional(store):
    a = await store.attr("mood: happy", "2023-01-01", advice="one")
    b = await store.attr("mood: sad", "2023-06-01", advice="one")          # plain turn, no replacement language
    p = (await store.props())[await store.prop_of(a)]
    assert (p.advised_one, p.advised_many) == (2, 0)                        # stored as a candidate ...
    assert p.functional_basis is None and not p.functional                  # ... that decides nothing
    assert not (await store.row(a)).get("superseded_by") and not (await store.row(b)).get("superseded_by")


async def test_replacement_language_alone_does_not_confirm(store):
    a = await store.attr("mood: happy", "2023-01-01")
    b = await store.attr("mood: sad", "2023-06-01", text="I am now feeling mood: sad")
    assert not (await store.row(a)).get("superseded_by")
    assert (await store.props())[await store.prop_of(a)].functional_basis is None


async def test_advice_plus_replacement_language_confirms_and_supersedes(store):
    a = await store.attr("team: Reds", "2023-01-01", advice="one")
    b = await store.attr("team: Blues", "2023-06-01", advice="one", text="I switched and now my team: Blues")
    p = (await store.props())[await store.prop_of(a)]
    assert p.functional_basis == "confirmed" and p.functional
    assert (await store.row(a))["superseded_by"] == b


# --- SHACL: one live value ----------------------------------------------------------------------

def _graph(db):
    path = Path(__file__).resolve().parent.parent / "scripts" / "graph_structure_report.py"
    spec = importlib.util.spec_from_file_location("gsr_b509_g", path)
    rep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rep)
    return rep.to_rdflib(db.store)


def _violations(g):
    report, _ = sv.validate_graph(g)
    return {f.shape for f in report.failures if f.severity == "Violation"}


async def test_shacl_two_live_values_of_a_functional_property(store, db):
    old = await store.attr("age: 30", "2023-01-01")
    new = await store.attr("age: 31", "2023-06-01")
    assert "FunctionalPropertyOneLiveValue" not in _violations(_graph(db))      # superseded: one live value
    db.execute(f"DELETE WHERE {{ ?o <{NS}superseded_by> ?x }}")                  # undo it: two live values
    g = _graph(db)
    assert "FunctionalPropertyOneLiveValue" in _violations(g)
    # a non-functional property with two live values is fine
    await store.attr("hobby: tennis", "2023-01-01")
    await store.attr("hobby: chess", "2023-02-01")
    bad = [f for f in sv.validate_graph(_graph(db))[0].failures if f.shape == "FunctionalPropertyOneLiveValue"]
    assert len(bad) == 1


# --- reasoning --------------------------------------------------------------------------------

def _broader(*pairs):
    from rdflib import Graph, Namespace, URIRef
    skos = Namespace(sv.SKOS_NS)
    g = Graph()
    for a, b in pairs:
        g.add((URIRef(f"http://x/{a}"), skos.broader, URIRef(f"http://x/{b}")))
    return g


def test_broader_cycles_of_any_length_are_found():
    assert sv.broader_cycles(_broader(("a", "b"), ("b", "c"))) == []
    assert len(sv.broader_cycles(_broader(("a", "b"), ("b", "a")))) == 1
    three = sv.broader_cycles(_broader(("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")))
    assert three == [["http://x/a", "http://x/b", "http://x/c"]]
    assert sv.broader_cycles(_broader(("a", "a"))) == [["http://x/a"]]
    assert len(sv.broader_cycles(_broader(("a", "b"), ("b", "a"), ("x", "y"), ("y", "z"), ("z", "x")))) == 2


def test_transitive_reduction_reports_redundant_edges_only():
    r = sv.redundant_broader(_broader(("a", "b"), ("b", "c"), ("a", "c"), ("a", "d")))
    assert r == [("http://x/a", "http://x/c")]
    assert sv.redundant_broader(_broader(("a", "b"), ("b", "c"))) == []


def test_reasoner_flags_instance_of_and_broader_on_one_pair():
    from rdflib import Graph, Namespace, URIRef
    campy = Namespace(NS)
    g = Graph()
    a, b = URIRef("http://x/a"), URIRef("http://x/b")
    g.add((a, campy.INSTANCE_OF, b))
    assert sv.reasoning_report(g).inconsistencies == []
    g.add((a, campy.BROADER, b))
    assert any("disjoint" in m for m in sv.reasoning_report(g).inconsistencies)


# --- structure report ----------------------------------------------------------------------------

def _load_report():
    path = Path(__file__).resolve().parent.parent / "scripts" / "graph_structure_report.py"
    spec = importlib.util.spec_from_file_location("graph_structure_report_b509", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_report_attribute_metrics(tmp_path):
    home = tmp_path / "rep"
    home.mkdir()
    client = OxigraphClient(home / "brain.db")
    st = Store(client, GraphGateway(client, REGISTRY))
    await st.attr("age: 30", "2023-01-01")
    await st.attr("age: 31", "2023-06-01")
    await st.attr("hobby: tennis", "2023-01-01")
    await st.attr("hobby: chess", "2023-02-01")
    await st.attr("note without a name", "2023-02-01")
    client.close()
    m = _load_report().measure(home, shacl=True)
    assert m["has_attribute"] == 5
    assert m["attr_properties"] == 2 and m["attr_props_functional"] == 1
    assert m["attr_linked"] == 4 and m["attr_typed"] == 2
    assert m["attr_superseded"] == 1 and m["functional_violations"] == 0
    assert m["broader_cycles"] == 0 and m["owl_inconsistencies"] == 0
    assert m["concept_fragments"] == 0              # property labels are not Concepts
    assert m["shacl"]["Observation"]["nonconforming"] == 0


async def test_backfill_links_existing_attributes_in_event_order(store):
    a = await store.attr("age: 31", "2023-06-01", config=None)
    b = await store.attr("age: 30", "2023-01-01", config=None)
    out = await ap.backfill(store.gw)
    assert out["linked"] == 2
    assert (await store.row(b))["superseded_by"] == a
    assert (await ap.backfill(store.gw))["linked"] == 0                  # idempotent
