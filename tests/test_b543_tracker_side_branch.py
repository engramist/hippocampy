"""B543: the decision tracker (Loop steps 2-7) as a deprecated side branch. Real Oxigraph store and real spaCy,
no model, no LLM (the classifier and the arbiter are stubbed).

Pins:
- flag: off by default, key-less config off, env CAMPY_TRACKER_SIDE_BRANCH, template line, profile member;
- flag off: a contradiction verdict archives the old Concept (DEPRECATED_BY + MergeEvent), as before;
- flag on: the same verdict archives nothing, stores the new Concept and a DisambiguationEvent;
- flag on: with steps 2 and 4 forced to noise, the stored entities equal the flag-off store;
- flag on: the tracker's own records (Constraint via REIFIED_AS) are still written;
- byte-identity: the whole store (all triples, ids and times normalised) is the same for flag absent / False,
  and for flag True when no contradiction verdict occurs;
- daemon: a Loop failure still enqueues the turn's Observation extraction with the flag on, not with it off;
- the one start-up warning when the flag is on and entity_admission is off.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from campy import brain_daemon as bd
from campy.brain.brainstem.config import _DEFAULT_CONFIG, PROFILES, apply_env_overrides
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.temporal_lobe.loop import tracker_branch as tb
from campy.brain.temporal_lobe.observations import extract as ex

pytestmark = pytest.mark.asyncio

DIM = 384
T0 = datetime(2023, 8, 11, 12, 0, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
BASE = {"loop": {"entity_admission": True}, "retrieval": {"graph_linking": False}}
ON = {"loop": {"entity_admission": True, "tracker_side_branch": True}, "retrieval": {"graph_linking": False}}
OFF = {"loop": {"entity_admission": True, "tracker_side_branch": False}, "retrieval": {"graph_linking": False}}
TURN = "We visited Boston last year and Berlin this spring."


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    def fake(text, model_name=None):
        v = [0.0] * DIM
        v[sum(map(ord, text.lower())) % DIM] = 1.0
        return v
    monkeypatch.setattr(embeddings_mod, "embed", fake)
    monkeypatch.setattr(orch.emb, "embed", fake)


def _store(tmp_path, name):
    db = OxigraphClient(tmp_path / f"{name}.db")
    return db, GraphGateway(db, REGISTRY)


async def _message(gw, mid, text, role="user"):
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text),
                 created_at=T0.isoformat())


def _pass_step2(monkeypatch):
    monkeypatch.setattr(orch, "classify_concept", lambda text, *a, **k: {
        "system": "1", "gist_class": "PhysicalThing", "confidence": 0.9, "vector": orch.emb.embed(text)})


def _noise(monkeypatch):
    monkeypatch.setattr(orch, "classify_concept",
                        lambda *a, **k: {"system": "noise", "gist_class": None, "confidence": 0.1, "vector": None})


def _step4(monkeypatch, artifact="decision", confidence=0.7):
    # only "Berlin" clears step 4, so exactly one entity reaches step 5 (Boston, admitted earlier, is the candidate)
    monkeypatch.setattr(orch, "classify_artifact", lambda *a, entity_text=None, **k: {
        "artifact_type": artifact, "confidence": confidence, "confidence_low": confidence < 0.9,
        "should_proceed": entity_text == "Berlin" or artifact == "constraint"})


def _arbitrate(monkeypatch, verdict):
    """Step 5 offers an existing Concept in the gray zone; step 6 answers `verdict`."""
    def candidates(vector, _q, db, exclude_ids=()):
        rows = db._execute_and_collect(
            f"SELECT ?id ?t WHERE {{ ?c a {NS}Concept> ; {NS}concept_id> ?id ; {NS}text_raw> ?t . "
            f"FILTER(?t = \"Boston\") }}")
        return [{"concept_id": str(r["id"]), "text_raw": str(r["t"]), "similarity": 0.8, "pathway_strength": 0.8}
                for r in rows]
    monkeypatch.setattr(orch, "retrieve_candidates", candidates)
    monkeypatch.setattr(orch, "arbitrate", lambda ent, cands, *a, **k: {
        "classification": verdict, "rationale": "", "referenced_node_ids": [c["concept_id"] for c in cands]})


async def _loop(db, mid, text, config):
    return await orch.run_loop(mid, text, db, None, config, {}, role="user", speaker=None)


async def _seed_boston(db, gw):
    await _message(gw, "m0", "I love Boston.")
    await _loop(db, "m0", "I love Boston.", BASE)


def _ask(db, q):
    return db._execute_and_collect(q)


def _archived(db, text):
    rows = _ask(db, f"SELECT ?a WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> \"{text}\" ; {NS}archived> ?a }}")
    return [str(r["a"]).lower() for r in rows]


def _count(db, typ):
    return len(_ask(db, f"SELECT ?x WHERE {{ ?x a {NS}{typ}> }}"))


def _dump(db):
    """Every triple, with the random ids and the clock normalised, sorted."""
    rows = _ask(db, "SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
    out = []
    for r in rows:
        line = f"{r['s']} {r['p']} {r['o']}"
        line = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>", line)
        line = re.sub(r"\d{4}-\d\d-\d\d[T ][\d:.+\-Z]+", "<t>", line)
        line = re.sub(r"_:[0-9a-f]+", "_:b", line)
        line = re.sub(r'"[-0-9.e]*(\[[^\]]*\])?"\^\^<http://www.w3.org/2001/XMLSchema#double>', "<d>", line)
        out.append(line)
    return sorted(out)


# --- the flag ----------------------------------------------------------------------------

async def test_flag_default_keyless_env_template_and_profile():
    assert tb.tracker_side_branch_enabled(_DEFAULT_CONFIG) is False
    assert tb.tracker_side_branch_enabled({}) is False
    assert tb.tracker_side_branch_enabled({"loop": {}}) is False
    on = apply_env_overrides({"loop": {}}, {"CAMPY_TRACKER_SIDE_BRANCH": "1"})
    assert tb.tracker_side_branch_enabled(on) is True
    off = apply_env_overrides({"loop": {"tracker_side_branch": True}}, {"CAMPY_TRACKER_SIDE_BRANCH": "0"})
    assert tb.tracker_side_branch_enabled(off) is False
    assert PROFILES["principled"]["loop"]["tracker_side_branch"] is True
    assert PROFILES["principled"]["loop"]["entity_admission"] is True
    path = Path(orch.__file__).parents[3] / "data/config/campy.toml"
    assert "tracker_side_branch" not in tomllib.loads(path.read_text()).get("loop", {})
    assert "# tracker_side_branch = false" in path.read_text()
    assert "deprecated" in tb.STATUS


# --- step 6: the only path that removed a stored Concept ------------------------------------

async def test_flag_off_contradiction_archives_the_old_concept(tmp_path, monkeypatch):
    db, gw = _store(tmp_path, "off")
    await _seed_boston(db, gw)
    _pass_step2(monkeypatch); _step4(monkeypatch); _arbitrate(monkeypatch, "contradiction")
    await _message(gw, "m1", TURN)
    summary = await _loop(db, "m1", TURN, OFF)
    assert _archived(db, "Boston") == ["true"]
    assert _count(db, "MergeEvent") >= 1 and _count(db, "DisambiguationEvent") == 0
    assert _ask(db, f"ASK {{ ?o {NS}DEPRECATED_BY> ?n }}") is True
    assert "contradictions_kept" not in summary


async def test_flag_on_contradiction_keeps_the_old_concept_and_adds_a_disambiguation_event(tmp_path, monkeypatch):
    db, gw = _store(tmp_path, "on")
    await _seed_boston(db, gw)
    _pass_step2(monkeypatch); _step4(monkeypatch); _arbitrate(monkeypatch, "contradiction")
    await _message(gw, "m1", TURN)
    summary = await _loop(db, "m1", TURN, ON)
    assert _archived(db, "Boston") == ["false"]
    assert _archived(db, "Berlin") == ["false"]
    assert _count(db, "MergeEvent") == 0
    assert _ask(db, f"ASK {{ ?o {NS}DEPRECATED_BY> ?n }}") is False
    assert _count(db, "DisambiguationEvent") >= 1
    pending = await gw.run("quests.get_pending_disambiguation_events", lim=50)
    assert len(pending) >= 1
    assert summary["contradictions_kept"] >= 1 and summary["contradictions"] == 0


# --- steps 2 and 4 never decide what a rule stores ------------------------------------------

async def test_flag_on_with_every_entity_dropped_stores_what_flag_off_stores(tmp_path, monkeypatch):
    _noise(monkeypatch)
    dumps = {}
    for name, cfg in (("a", OFF), ("b", ON)):
        db, gw = _store(tmp_path, name)
        await _message(gw, "m1", TURN)
        await _loop(db, "m1", TURN, cfg)
        names = sorted(str(r["t"]) for r in _ask(db, f"SELECT ?t WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> ?t }}"))
        assert "Boston" in names and "Berlin" in names
        assert _count(db, "Decision") == _count(db, "Constraint") == 0
        dumps[name] = _dump(db)
    assert dumps["a"] == dumps["b"]


async def test_flag_on_keeps_adding_the_trackers_own_records(tmp_path, monkeypatch):
    _pass_step2(monkeypatch); _step4(monkeypatch, artifact="constraint", confidence=0.95)
    db, gw = _store(tmp_path, "rec")
    text = "Dave must never ship on Friday."
    await _message(gw, "m1", text)
    await _loop(db, "m1", text, ON)
    assert _count(db, "Constraint") >= 1
    assert _ask(db, f"ASK {{ ?c {NS}REIFIED_AS> ?x }}") is True


# --- flag off is byte-identical ---------------------------------------------------------------

async def _run_store(tmp_path, name, cfg, monkeypatch, verdict):
    _pass_step2(monkeypatch); _step4(monkeypatch); _arbitrate(monkeypatch, verdict)
    db, gw = _store(tmp_path, name)
    await _seed_boston(db, gw)
    await _message(gw, "m1", TURN)
    summary = await _loop(db, "m1", TURN, cfg)
    dump = _dump(db)
    assert len(dump) > 40 and summary["entities_found"] >= 2   # the comparison is over a real store
    return dump, summary


@pytest.mark.parametrize("verdict", ["additive", "uncertain", "contradiction"])
async def test_flag_absent_equals_flag_false_for_every_verdict(tmp_path, monkeypatch, verdict):
    absent, s_absent = await _run_store(tmp_path, "abs", BASE, monkeypatch, verdict)
    false, s_false = await _run_store(tmp_path, "fls", OFF, monkeypatch, verdict)
    assert absent == false
    assert s_absent == s_false


@pytest.mark.parametrize("verdict", ["additive", "uncertain"])
async def test_flag_on_equals_flag_off_when_no_contradiction_occurs(tmp_path, monkeypatch, verdict):
    off, s_off = await _run_store(tmp_path, "o", OFF, monkeypatch, verdict)
    on, s_on = await _run_store(tmp_path, "n", ON, monkeypatch, verdict)
    assert on == off
    assert s_on == s_off


# --- the daemon: a Loop failure never withholds the turn's Observation extraction ---------------

def _fake_daemon(config):
    return SimpleNamespace(
        db=object(), _llm_client=object(), config=config, _centroids={},
        _loop_queue=asyncio.Queue(), _observation_queue=asyncio.Queue(maxsize=10),
        _observation_stats=ex.ObservationWorkerStats())


async def _worker(fake, monkeypatch, run_loop):
    monkeypatch.setattr(bd, "run_loop", run_loop)
    task = asyncio.create_task(bd.BrainDaemon._loop_worker(fake))
    await asyncio.wait_for(fake._loop_queue.join(), timeout=2.0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.parametrize("flag, queued", [(False, 0), (True, 1)])
async def test_loop_failure_enqueues_observation_only_with_the_flag(monkeypatch, flag, queued):
    fake = _fake_daemon({"loop": {"tracker_side_branch": flag}})
    await fake._loop_queue.put(("m-user", "hello there friend", "user", "s1", None, "Melanie"))
    await _worker(fake, monkeypatch, AsyncMock(side_effect=RuntimeError("model timeout")))
    assert fake._observation_queue.qsize() == queued


@pytest.mark.parametrize("flag", [False, True])
async def test_loop_success_enqueues_once_whatever_the_flag(monkeypatch, flag):
    fake = _fake_daemon({"loop": {"tracker_side_branch": flag}})
    await fake._loop_queue.put(("m-user", "hello there friend", "user", "s1", None, "Melanie"))
    ok = AsyncMock(return_value={"entities_found": 0, "concepts_stored": 0, "relations_found": 0, "noise_count": 0})
    await _worker(fake, monkeypatch, ok)
    assert fake._observation_queue.qsize() == 1


# --- the start-up warning ----------------------------------------------------------------------

async def test_one_warning_when_flag_on_without_admission(caplog):
    with caplog.at_level(logging.WARNING, logger=tb.__name__):
        assert tb.warn_if_tracker_without_admission({"loop": {"tracker_side_branch": True}}) is True
    assert len(caplog.records) == 1
    assert tb.warn_if_tracker_without_admission({"loop": {"tracker_side_branch": True, "entity_admission": True}}) is False
    assert tb.warn_if_tracker_without_admission({"loop": {"entity_admission": False}}) is False
    assert tb.warn_if_tracker_without_admission({}) is False
