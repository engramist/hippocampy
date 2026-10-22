"""B507: SHACL shapes for Observation / Message / Concept, the write gate, and the structure report.

Pins:
- the shapes accept a valid Observation and reject each invalid variant (and the
  value sets in the shapes equal the Python constants they mirror);
- Concept labels: present, not empty, not stopword-only;
- `[observations] shacl_gate` (default OFF): on, a non-conforming draft is not
  written and is counted; off, behaviour is the writer's own, and the validator
  is never called;
- scripts/graph_structure_report.py runs on a tiny real store.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyshacl")

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.shapes import validator as sv

T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
MSG_TEXT = "My sister Dana is a nurse.  She said “I went to the Denver support group on 7 May 2023”."
QUOTE = "My sister Dana is a nurse"

MESSAGE = {"message_id": "m1", "text_raw": MSG_TEXT, "role": "user", "archived": False}
VALID = dict(
    observation_id="o1", subject_text="Dana", predicate="has_attribute", object_text="job: nurse",
    polarity="asserted", observed_at=T0, extraction_method="llm", confidence=0.8,
    evidence_text=QUOTE, evidence_ref="m1", evidence_start=0, evidence_end=len(QUOTE),
)


def _keys(fields=None, message=MESSAGE, severity="Violation"):
    report = sv.validate_observation_candidate({**VALID, **(fields or {})}, message)
    return [f.key for f in report.failures if f.severity == severity]


# --- the shapes ---------------------------------------------------------------------

def test_a_valid_observation_conforms():
    report = sv.validate_observation_candidate(VALID, MESSAGE)
    assert report.conforms and sv.blocking(report) == []


@pytest.mark.parametrize("change, shape", [
    (dict(predicate="invented"), "predicate [InConstraintComponent]"),
    (dict(polarity="maybe"), "polarity [InConstraintComponent]"),
    (dict(extraction_method="deterministic"), "extraction_method [InConstraintComponent]"),
    (dict(time_precision="decade"), "time_precision [InConstraintComponent]"),
    (dict(observed_at=None), "observed_at [MinCountConstraintComponent]"),
    (dict(observed_at="not-a-date"), "observed_at [DatatypeConstraintComponent]"),
    (dict(object_text="  "), "object_text [PatternConstraintComponent]"),
    (dict(object_text="x" * 201), "object_text [MaxLengthConstraintComponent]"),
    (dict(object_text="the"), "object_text content [NotConstraintComponent]"),
    (dict(object_text="..."), "object_text content [NotConstraintComponent]"),
    (dict(object_text="{'name': 'job'}"), "object_text not a structure [NotConstraintComponent]"),
    (dict(object_text="['a', 'b']"), "object_text not a structure [NotConstraintComponent]"),
    (dict(confidence=0.59), "confidence [MinInclusiveConstraintComponent]"),
    (dict(confidence=1.2), "confidence [MaxInclusiveConstraintComponent]"),
    (dict(evidence_text="y" * 401), "evidence_text [MaxLengthConstraintComponent]"),
    (dict(evidence_text=QUOTE.replace("nurse", "doctor")), "QuoteIsSpanOfEvidence [SPARQLConstraintComponent]"),
    (dict(evidence_start=9, evidence_end=3), "evidence_start [LessThanOrEqualsConstraintComponent]"),
    (dict(evidence_ref="other"), "EvidenceRefLinked [SPARQLConstraintComponent]"),
    (dict(time_start=T0, time_end=datetime(2020, 1, 1, tzinfo=timezone.utc)),
     "time_start [LessThanOrEqualsConstraintComponent]"),
])
def test_each_invalid_observation_variant_is_rejected(change, shape):
    assert shape in _keys(change)


def test_subject_needs_text_or_an_id():
    assert _keys(dict(subject_text=None, subject_id="c1")) == []          # an id alone is a subject
    assert any("OrConstraintComponent" in k for k in _keys(dict(subject_text="  ")))
    assert any("OrConstraintComponent" in k for k in _keys(dict(subject_text=None)))


def test_an_observation_needs_a_live_user_evidence_message():
    assert "EVIDENCED_BY [MinCountConstraintComponent]" in _keys(message=None)
    assert "evidence role [InConstraintComponent]" in _keys(message={**MESSAGE, "role": "assistant"})
    assert "evidence archived [InConstraintComponent]" in _keys(message={**MESSAGE, "archived": True})


def test_a_has_attribute_object_not_in_name_value_form_is_a_warning_not_a_failure():
    assert _keys(dict(object_text="nurse")) == []
    assert _keys(dict(object_text="nurse"), severity="Warning") == ["AttributeObjectIsNameValue [SPARQLConstraintComponent]"]
    assert _keys(dict(object_text="nurse", predicate="is_a"), severity="Warning") == []


def test_shape_value_sets_equal_the_python_constants():
    from rdflib import Namespace
    from rdflib.collection import Collection

    sh, campy = Namespace("http://www.w3.org/ns/shacl#"), Namespace(sv.NS)
    g = sv.load_shapes()

    def allowed(path):
        for ps in g.objects(campy.ObservationShape, sh.property):
            if (ps, sh.path, path) in g and (ps, sh["in"], None) in g:
                return {str(x) for x in Collection(g, g.value(ps, sh["in"]))}
        raise AssertionError(path)

    assert allowed(campy.predicate) == obs.PREDICATES
    assert allowed(campy.polarity) == obs.POLARITIES
    assert allowed(campy.time_precision) == obs.TIME_PRECISIONS
    assert allowed(campy.extraction_method) == obs.EXTRACTION_METHODS


# --- Concept labels -----------------------------------------------------------------

def _concept_graph(label):
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, XSD

    campy = Namespace(sv.NS)
    g = Graph()
    c = URIRef("https://campy.dev/id/Concept/c1")
    g.add((c, RDF.type, campy.Concept))
    g.add((c, campy.concept_id, Literal("c1")))
    if label is not None:
        g.add((c, campy.text_raw, Literal(label)))
    g.add((c, campy.archived, Literal(False, datatype=XSD.boolean)))
    return g


@pytest.mark.parametrize("label, ok", [
    ("Dana", True), ("AI", True), ("the Denver support group", True),
    (None, False), ("", False), ("   ", False), ("the", False), ("The of", False),
    ("it", False), ("I", False), ("...", False),
])
def test_concept_prefLabel_present_and_not_empty_or_stopword_only(label, ok):
    report, _ = sv.validate_graph(_concept_graph(label))
    assert (sv.blocking(report) == []) is ok
    assert sv.is_fragment(label) is (not ok or len((label or "").strip()) <= 2)


def test_fragments_are_stopword_only_or_one_or_two_characters():
    assert sv.is_fragment("a the") and sv.is_fragment("x") and sv.is_fragment("OK") and not sv.is_fragment("Dana")


# --- the gate -----------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    client = OxigraphClient(tmp_path / "b507.db")
    yield client
    client.close()


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _message(gw, mid="m1", text=MSG_TEXT):
    await gw.run(
        "capture.create_message", message_id=mid, text_raw=text, embedding=None,
        embedding_model="m", embedding_dim=384, role="user", byte_end=len(text),
        created_at="2023-05-07T12:00:00+00:00",
    )
    await gw.run("capture.set_message_source", message_id=mid, speaker="Melanie",
                 occurred_at="2023-05-07T12:00:00+00:00")


def _draft(**kw):
    base = dict(evidence_ref="m1", evidence_text=QUOTE, subject_text="Dana", predicate="has_attribute",
                object_text="job: nurse", extraction_method="llm", confidence=0.8, rule_version="llm-1")
    base.update(kw)
    return obs.ObservationDraft(**base)


GATE_ON = {"observations": {"shacl_gate": True}}


def test_the_gate_is_off_by_default_and_has_an_env_override():
    assert _DEFAULT_CONFIG["observations"]["shacl_gate"] is False
    assert obs.shacl_gate_enabled(None) is False and obs.shacl_gate_enabled({}) is False
    assert obs.shacl_gate_enabled(_DEFAULT_CONFIG) is False
    assert obs.shacl_gate_enabled(GATE_ON) is True
    assert apply_env_overrides({}, {"CAMPY_SHACL_GATE": "1"})["observations"]["shacl_gate"] is True
    assert apply_env_overrides({}, {"CAMPY_SHACL_GATE": "0"})["observations"]["shacl_gate"] is False
    assert "shacl_violation" in obs.REJECT_REASONS


async def test_gate_on_a_conforming_draft_is_written(gw, db):
    await _message(gw)
    res = await obs.record_observation(db, _draft(), config=GATE_ON)
    assert res.status == "created"
    assert len(await obs.observations_for_message(db, "m1")) == 1


@pytest.mark.parametrize("change, shape", [
    (dict(object_text="{'name': 'job'}"), "object_text not a structure [NotConstraintComponent]"),
    (dict(object_text="it"), "object_text content [NotConstraintComponent]"),
])
async def test_gate_on_a_nonconforming_draft_is_not_written_and_is_counted(gw, db, change, shape, caplog):
    await _message(gw)
    stats = obs.WriteStats()
    with caplog.at_level("WARNING", logger=obs.__name__):
        res = stats.record(await obs.record_observation(db, _draft(**change), config=GATE_ON))
    assert (res.status, res.reason) == ("rejected", "shacl_violation")
    assert shape in res.detail.split(";")
    assert await obs.observations_for_message(db, "m1") == []
    assert stats.rejected == {"shacl_violation": 1} and stats.shacl_shapes[shape] == 1
    assert shape in caplog.text


@pytest.mark.parametrize("config", [None, {}, {"observations": {"shacl_gate": False}}])
async def test_gate_off_nothing_changes_and_the_validator_is_never_called(gw, db, config, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("validator called with the gate off")

    monkeypatch.setattr(sv, "validate_observation_candidate", boom)
    await _message(gw)
    res = await obs.record_observation(db, _draft(object_text="{'name': 'job'}"), config=config)
    assert res.status == "created" and res.detail is None      # the same draft the gate rejects
    row = await obs.get_observation(db, res.observation_id)
    assert row["object_text"] == "{'name': 'job'}" and row["observed_at"] is not None


async def test_the_worker_stats_carry_the_failed_shapes():
    from campy.brain.temporal_lobe.observations.extract import ObservationWorkerStats

    ws = obs.WriteStats()
    ws.record(obs.WriteResult("rejected", None, "shacl_violation", "a [X];b [Y]"))
    stats = ObservationWorkerStats()
    stats.merge_write(ws)
    d = stats.as_details()
    assert d["rejected"] == {"shacl_violation": 1} and d["shacl_shapes"] == {"a [X]": 1, "b [Y]": 1}


# --- the structure report -----------------------------------------------------------

def _load_report():
    path = Path(__file__).resolve().parent.parent / "scripts" / "graph_structure_report.py"
    spec = importlib.util.spec_from_file_location("graph_structure_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_structure_report_on_a_tiny_store(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    client = OxigraphClient(home / "brain.db")
    gw = GraphGateway(client, REGISTRY)
    await _message(gw)
    for cid, text in (("c-dana", "Dana"), ("c-the", "the"), ("c-dana2", "dana")):
        await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=[0.05] * 384,
                     gist="Agent", stype="Person", now=T0)
    await obs.record_observation(client, _draft(subject_id="c-dana"))                 # linked, name: value
    await obs.record_observation(client, _draft(object_text="{'name': 'job'}", predicate="has_attribute"))
    client.close()

    rep = _load_report()
    m = rep.measure(home)
    assert m["observations"] == 2 and m["obs_linked"] == 1
    assert m["has_attribute"] == 2 and m["attr_name_value"] == 1 and m["attr_structured"] == 1
    assert m["concepts"] == 3 and m["concept_fragments"] == 1 and m["concept_redundant"] == 1
    assert m["user_messages"] == 1 and m["user_msgs_mention"] == 0
    assert m["shacl"]["Observation"] == {"total": 2, "nonconforming": 1, "warned": 0,
                                         "top": {"object_text not a structure [NotConstraintComponent]": 1}} \
        or m["shacl"]["Observation"]["nonconforming"] == 1
    assert m["shacl"]["Concept"]["nonconforming"] == 1 and m["shacl"]["Message"]["nonconforming"] == 0

    assert rep.main([str(home)]) == 0
    out = capsys.readouterr().out
    assert "SHACL Obs" in out and "50.0%" in out and "Top failing shapes" in out
    assert rep.main([str(home), "--json", "--no-shacl"]) == 0
    assert json.loads(capsys.readouterr().out)["pooled"]["observations"] == 2


def test_report_label_normalisation():
    rep = _load_report()
    assert rep.normalise_label("The  Denver, Group!") == rep.normalise_label("denver group")
