"""B514: the benchmark-gated levers are on by default (walk off), and an old store copes.

Pins the shipped defaults (code and packaged campy.toml), that the v1 walk adds no
section at its default limit, that the SHACL gate degrades safely when pyshacl or
rdflib cannot be imported, that B499's string rule is not applied on top of B509's
OWL supersession, and that a store written before the flags existed (no kinds, no
attribute properties, no MENTIONS) still ingests and compiles with the defaults on.
Fake LLM, real Oxigraph store.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, load_config
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex
from campy.brain.thalamus import bundle_compiler as bc

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
PACKAGED = Path(__file__).resolve().parent.parent / "campy" / "data" / "config" / "campy.toml"

ON = {
    ("retrieval", "conversation_embedded_statements"): True,
    ("retrieval", "graph_linking"): True,
    ("retrieval", "skos_vocab"): True,
    ("observations", "entities"): True,
    ("observations", "owl_properties"): True,
    ("observations", "shacl_gate"): True,
}
STILL_OFF = {
    ("observations", "supersede"): False,     # B499's string rule; B509 replaces it
}


def _check(cfg):
    for (section, key), value in {**ON, **STILL_OFF}.items():
        assert cfg[section][key] is value, (section, key)
    assert cfg["retrieval"]["graph_linking_limit"] == 0     # links written, v1 walk adds no section


def test_code_defaults():
    _check(_DEFAULT_CONFIG)


def test_packaged_toml_defaults_match_the_code():
    with open(PACKAGED, "rb") as f:
        _check(tomllib.load(f))


def test_a_user_config_without_the_sections_gets_the_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "ollama"\n')
    _check(load_config(path))


def test_no_experimental_lever_is_on_by_default():
    retrieval = _DEFAULT_CONFIG["retrieval"]
    assert not any("walk_v2" in k or "aggregate" in k for k in retrieval)
    assert not any("aggregate" in k for k in _DEFAULT_CONFIG.get("ask", {}))


# --- the walk -----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b514.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _message(gw, mid, text, day=3):
    stamp = f"2023-05-{day:02d}T12:00:00+00:00"
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
    await gw.run("capture.set_message_source", message_id=mid, speaker="Sam", occurred_at=stamp)


def _config(**retrieval):
    cfg = copy.deepcopy(_DEFAULT_CONFIG)
    cfg["observations"]["retrieval"] = False
    cfg["retrieval"]["conversation_token_budget"] = 0
    cfg["retrieval"].update(retrieval)
    return cfg


async def test_default_limit_zero_adds_no_walk_section_but_a_positive_limit_does(db, gw):
    from campy.brain.hippocampus import concept_links as cl

    await gw.run("temporal_lobe.dict_create_concept", cid="c-kit", text="model kit", emb=[0.0] * DIM,
                 gist="Category", stype="DefinedTerm", now=T0)
    for i, text in enumerate(["Picked up a Revell F-15 Eagle model kit.", "Finished the Tamiya Spitfire model kit."]):
        await _message(gw, f"m{i}", text, day=3 + i * 8)
        await cl.link_message_concepts(gw, f"m{i}", text)
    q = "How many model kits do I own?"
    default = await bc.compile_bundle(q, db, _config())
    assert not any(s.section_type == "linked" for s in default.sections)
    walked = await bc.compile_bundle(q, db, _config(graph_linking_limit=12))
    assert any(s.section_type == "linked" for s in walked.sections)      # the links ARE written


# --- the SHACL gate degrades safely ---------------------------------------------------

def _draft(**kw):
    base = dict(evidence_ref="m1", evidence_text="I work as a nurse", subject_text="I",
                predicate="has_attribute", object_text="job: nurse", extraction_method="llm",
                confidence=0.8, rule_version="llm-1")
    return obs.ObservationDraft(**{**base, **kw})


async def test_shacl_gate_with_missing_packages_logs_once_and_writes(db, gw, monkeypatch, caplog):
    pytest.importorskip("pyshacl")
    from campy.brain.hippocampus.shapes import validator

    def missing(*a, **k):
        raise ImportError("No module named 'pyshacl'")

    monkeypatch.setattr(validator, "validate_observation_candidate", missing)
    monkeypatch.setattr(obs, "_SHACL_UNAVAILABLE_LOGGED", False)
    await _message(gw, "m1", "I work as a nurse at the Denver clinic.")
    cfg = copy.deepcopy(_DEFAULT_CONFIG)
    with caplog.at_level("WARNING", logger=obs.__name__):
        first = await obs.record_observation(db, _draft(), config=cfg)
        second = await obs.record_observation(db, _draft(object_text="employer: Denver clinic"), config=cfg)
    assert [(first.status, first.reason), (second.status, second.reason)] == [("created", None)] * 2
    assert caplog.text.count("SHACL gate skipped") == 1


# --- an existing store ----------------------------------------------------------------

class _LLM:
    def __init__(self, *claims):
        self.reply = json.dumps(list(claims))

    def chat(self, messages, **kwargs):
        return self.reply


async def test_a_store_from_before_the_flags_ingests_and_compiles_with_the_defaults(db, gw):
    # Old shape: Messages, Concepts and Observations, no kinds, attribute properties or MENTIONS.
    await gw.run("temporal_lobe.dict_create_concept", cid="c-old", text="Denver", emb=[0.0] * DIM,
                 gist="Place", stype="Place", now=T0)
    await _message(gw, "old1", "I moved to Denver in March.", day=1)
    old = await obs.record_observation(db, _draft(evidence_text="I moved to Denver", evidence_ref="old1",
                                                  object_text="city: Denver"), config={})
    assert old.status == "created"
    cfg = copy.deepcopy(_DEFAULT_CONFIG)
    cfg["observations"]["retrieval"] = False
    cfg["retrieval"]["conversation_token_budget"] = 0
    await _message(gw, "m1", "I work as a nurse at the Denver clinic.", day=5)
    llm = _LLM({"subject": "I", "predicate": "has_attribute", "object": "job: nurse", "time": None,
                "polarity": "asserted", "quote": "I work as a nurse", "confidence": 0.9,
                "object_entity": "nurse", "object_kind": "profession"})
    stats = ex.ObservationWorkerStats()
    assert await ex.process_turn(db, cfg, llm, "m1", stats) == 1
    assert stats.entities_linked == 1
    bundle = await bc.compile_bundle("What does Sam do for work?", db, cfg)
    assert bundle is not None


async def test_owl_supersession_is_not_applied_twice(db, gw, monkeypatch):
    calls = []

    async def spy(*a, **k):
        calls.append(1)

    monkeypatch.setattr(obs, "_supersede_attributes", spy)
    await _message(gw, "m1", "I work as a nurse at the Denver clinic.")
    cfg = {"observations": {"owl_properties": True, "supersede": True}}
    res = await obs.record_observation(db, _draft(), config=cfg, supersede=True)
    assert (res.status, res.reason, res.detail) == ("created", None, None) and calls == []     # the OWL branch wins; the string rule is skipped
