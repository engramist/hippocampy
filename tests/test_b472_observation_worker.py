"""B472 Phase 3b: the Observation worker and its per-turn LLM extraction.

No real LLM: every model is a fake. Pins:
- disabled (the default) means no queue, no worker task, nothing enqueued;
- enabled, a user turn yields grounded Observations linked to the evidence
  Message and to EXISTING Concepts (never a new one); assistant turns are skipped;
- malformed or paraphrasing model output is tolerated and counted;
- the queue is bounded, a full queue drops (counted) and never blocks capture;
- a worker exception never kills the loop; re-processing is idempotent.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import campy.brain_daemon as bd
from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.observations import extract as ex

EMB = [0.05] * 384
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
TEXT = "My sister Dana is a nurse. I went to the Denver support group last Saturday."
CFG = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600}}


@pytest.fixture(autouse=True)
def _no_embedder(monkeypatch):
    monkeypatch.setattr(ex.emb, "embed", lambda text, model_name=None: EMB)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b472p3b.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _message(gw, mid="m1", text=TEXT, role="user", speaker="Melanie"):
    await gw.run(
        "capture.create_message", message_id=mid, text_raw=text, embedding=None,
        embedding_model="m", embedding_dim=384, role=role, byte_end=len(text),
        created_at="2023-05-07T12:00:00+00:00",
    )
    if speaker:
        await gw.run("capture.set_message_source", message_id=mid, speaker=speaker,
                     occurred_at="2023-05-07T12:00:00+00:00")
    return mid


async def _concept(gw, cid, text, stype="Person"):
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=EMB,
                 gist="Agent", stype=stype, now=T0)
    return cid


class FakeLLM:
    """Returns canned replies in order (the last repeats) and records calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[list, dict]] = []
        self.threads: list[int] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        self.threads.append(threading.get_ident())
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _reply(*items):
    return json.dumps(list(items))


JOB = {"subject": "my sister", "predicate": "has_attribute", "object": "job: nurse",
       "time": None, "polarity": "asserted", "quote": "My sister Dana is a nurse", "confidence": 0.9}
DANA_JOB = {**JOB, "subject": "Dana"}
WENT = {"subject": "I", "predicate": "did", "object": "went to the Denver support group",
        "time": "last Saturday", "polarity": "asserted",
        "quote": "I went to the Denver support group last Saturday", "confidence": 0.85}


# --- off by default -----------------------------------------------------------------

def test_disabled_by_default_means_no_queue_no_worker_and_nothing_enqueued(monkeypatch, tmp_path):
    assert _DEFAULT_CONFIG["observations"]["enabled"] is False
    monkeypatch.setattr(bd, "OxigraphClient", lambda p: object())
    assert bd.BrainDaemon(dict(_DEFAULT_CONFIG))._observation_queue is None
    daemon = bd.BrainDaemon({**_DEFAULT_CONFIG, "observations": {**_DEFAULT_CONFIG["observations"], "enabled": True, "queue_max": 7}})
    assert daemon._observation_queue.maxsize == 7

    off = SimpleNamespace(_observation_queue=None)
    bd._enqueue_observation(off, ("m", "t", "user", "s", None, "Mel"), "m", "user", "s", "Mel")  # no crash, no effect
    bd._enqueue_observation(SimpleNamespace(), ("m", "t", "user", "s", None, None), "m", "user", "s", None)


def test_env_override_turns_it_on():
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_ENABLED": "1"})["observations"]["enabled"] is True
    assert apply_env_overrides({}, {"CAMPY_OBSERVATIONS_ENABLED": "false"})["observations"]["enabled"] is False
    assert "observations" not in apply_env_overrides({}, {})


def _fake_daemon(enabled=True, maxsize=10):
    return SimpleNamespace(
        db=object(), _llm_client=object(), config={}, _centroids={},
        _loop_queue=asyncio.Queue(),
        _observation_queue=asyncio.Queue(maxsize=maxsize) if enabled else None,
        _observation_stats=ex.ObservationWorkerStats(),
    )


async def _run_loop_worker(fake, monkeypatch):
    monkeypatch.setattr(bd, "run_loop", AsyncMock(return_value={
        "entities_found": 0, "concepts_stored": 0, "relations_found": 0, "noise_count": 0}))
    task = asyncio.create_task(bd.BrainDaemon._loop_worker(fake))
    await asyncio.wait_for(fake._loop_queue.join(), timeout=2.0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_loop_worker_feeds_user_turns_only(monkeypatch):
    fake = _fake_daemon()
    await fake._loop_queue.put(("m-user", "hello there friend", "user", "s1", None, "Melanie"))
    await fake._loop_queue.put(("m-asst", "hello there friend", "assistant", "s1", None, None))
    await fake._loop_queue.put(("x-extract", "document chunk text", "user", "unknown"))  # ingest_document's 4-tuple
    await _run_loop_worker(fake, monkeypatch)
    assert fake._observation_queue.qsize() == 1
    assert fake._observation_queue.get_nowait() == ("m-user", "s1", "Melanie")


@pytest.mark.asyncio
async def test_loop_worker_enqueues_nothing_when_disabled(monkeypatch):
    fake = _fake_daemon(enabled=False)
    await fake._loop_queue.put(("m1", "hello there friend", "user", "s1", None, "Melanie"))
    await _run_loop_worker(fake, monkeypatch)
    assert fake._observation_queue is None


@pytest.mark.asyncio
async def test_a_full_queue_drops_the_newest_counted_and_never_blocks_or_raises():
    fake = _fake_daemon(maxsize=1)
    item = ("m", "t", "user", "s", None, None)
    bd._enqueue_observation(fake, item, "m1", "user", "s", None)
    bd._enqueue_observation(fake, item, "m2", "user", "s", None)   # full: must return immediately
    bd._enqueue_observation(fake, item, "m3", "user", "s", None)
    assert fake._observation_stats.queue_dropped == 2
    assert fake._observation_queue.get_nowait()[0] == "m1"          # oldest kept


@pytest.mark.asyncio
async def test_a_worker_exception_does_not_kill_the_loop(monkeypatch):
    fake = _fake_daemon()
    seen = []

    async def flaky(db, config, client, message_id, stats, **kw):
        seen.append(message_id)
        if message_id == "bad":
            raise RuntimeError("storage blew up")
        return 0

    monkeypatch.setattr(bd, "process_observation_turn", flaky)
    monkeypatch.setattr(bd, "create_llm_client_for_step", lambda c, s: None)
    monkeypatch.setattr(bd, "emit_activity", lambda *a, **k: None)
    for mid in ("bad", "good"):
        await fake._observation_queue.put((mid, "s", None))
    await fake._observation_queue.put(5)                 # malformed item
    await fake._observation_queue.put(("also", ))                    # too short to unpack
    task = asyncio.create_task(bd.BrainDaemon._observation_worker(fake))
    await asyncio.wait_for(fake._observation_queue.join(), timeout=2.0)
    assert not task.done()
    assert seen == ["bad", "good"]
    assert fake._observation_stats.errors == 3
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# --- extraction ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_user_turn_yields_observations_linked_to_message_and_existing_concepts(db, gw):
    await _message(gw)
    await _concept(gw, "c-dana", "Dana")
    await _concept(gw, "c-mel", "Melanie")
    llm = FakeLLM(_reply(DANA_JOB, WENT))
    stats = ex.ObservationWorkerStats()
    n = await ex.process_turn(db, CFG, llm, "m1", stats)
    assert n == 2 and stats.created == 2 and stats.proposed == 2 and not stats.rejected
    rows = await obs.observations_for_message(db, "m1")
    by_pred = {r["predicate"]: r for r in rows}
    job, did = by_pred["has_attribute"], by_pred["did"]
    assert job["subject_id"] == "c-dana" and job["extraction_method"] == "llm"
    assert job["rule_version"] == ex.RULE_VERSION and job["evidence_ref"] == "m1"
    assert did["subject_text"] == "I" and did["subject_id"] == "c-mel"      # speaker's Concept
    assert did["time_text"] == "last Saturday" and did["time_start"] is None  # not normalised (M4.2)
    assert did["text_raw"].startswith("Melanie - did")
    assert await obs.observations_for_concept(db, "c-dana")
    assert stats.linked_subject == 2


@pytest.mark.asyncio
async def test_unknown_names_are_not_turned_into_concepts(db, gw):
    await _message(gw)
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, FakeLLM(_reply(DANA_JOB)), "m1", stats)
    (row,) = await obs.observations_for_message(db, "m1")
    assert row["subject_id"] is None and row["subject_text"] == "Dana"
    assert await gw.run("orchestrator.find_endpoint_concept", t="Dana") == []   # still none


@pytest.mark.asyncio
async def test_an_entity_object_links_to_an_existing_concept(db, gw):
    text = "Melanie is my friend and we talk daily."
    await _message(gw, text=text, speaker="Caroline")
    await _concept(gw, "c-mel", "Melanie")
    p = {"subject": "I", "predicate": "relates_to", "object": "friend: Melanie", "time": None,
         "polarity": "asserted", "quote": "Melanie is my friend", "confidence": 0.9}
    await ex.process_turn(db, CFG, FakeLLM(_reply(p)), "m1", ex.ObservationWorkerStats())
    (row,) = await obs.observations_for_message(db, "m1")
    assert row["object_id"] == "c-mel"
    assert row["subject_id"] is None           # Caroline has no Concept here: not created


@pytest.mark.asyncio
async def test_unnamed_speaker_first_person_is_the_user(db, gw):
    await _message(gw, speaker=None)
    await ex.process_turn(db, CFG, FakeLLM(_reply(WENT)), "m1", ex.ObservationWorkerStats())
    (row,) = await obs.observations_for_message(db, "m1")
    assert row["subject_text"] == "the user" and row["subject_id"] is None


@pytest.mark.asyncio
async def test_the_speaker_name_written_for_I_is_read_as_first_person(db, gw):
    await _message(gw)
    p = {**WENT, "subject": "Melanie"}
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, FakeLLM(_reply(p)), "m1", stats)
    assert stats.created == 1 and not stats.rejected


@pytest.mark.asyncio
async def test_assistant_and_missing_turns_are_skipped_without_an_llm_call(db, gw):
    await _message(gw, mid="a1", role="assistant")
    llm = FakeLLM(_reply(JOB))
    stats = ex.ObservationWorkerStats()
    assert await ex.process_turn(db, CFG, llm, "a1", stats) == 0
    assert await ex.process_turn(db, CFG, llm, "nope", stats) == 0
    assert llm.calls == [] and stats.skipped_not_user == 1 and stats.skipped_no_message == 1


@pytest.mark.asyncio
async def test_short_turns_cost_no_llm_call(db, gw):
    await _message(gw, text="ok thanks")
    llm = FakeLLM(_reply(JOB))
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, llm, "m1", stats)
    assert llm.calls == [] and stats.skipped_short == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    "I could not find any facts.", "", "{not json", '{"a": 1}', "[1, 2]", '["x"]', "null",
])
async def test_malformed_model_output_writes_nothing_and_is_counted(db, gw, reply):
    await _message(gw)
    stats = ex.ObservationWorkerStats()
    assert await ex.process_turn(db, CFG, FakeLLM(reply), "m1", stats) == 0
    assert stats.malformed == 1 and stats.created == 0
    assert await obs.observations_for_message(db, "m1") == []


@pytest.mark.asyncio
async def test_empty_array_is_not_malformed(db, gw):
    await _message(gw)
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, FakeLLM("[]"), "m1", stats)
    assert stats.malformed == 0 and stats.proposed == 0


def test_parse_tolerates_fences_and_prose():
    assert ex.parse_observations('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert ex.parse_observations('Sure! Here you go: [{"a": 1}] hope that helps') == [{"a": 1}]
    assert ex.parse_observations('{"observations": [{"a": 1}]}') == [{"a": 1}]
    assert ex.parse_observations(None) is None


@pytest.mark.asyncio
async def test_a_paraphrased_quote_or_bad_predicate_is_rejected_and_counted(db, gw):
    await _message(gw)
    paraphrase = {**JOB, "quote": "Dana works as a nurse"}
    invented = {**JOB, "predicate": "is_friends_with"}
    low = {**WENT, "confidence": 0.3}
    incomplete = {"subject": "I", "predicate": "did"}
    stats = ex.ObservationWorkerStats()
    n = await ex.process_turn(db, CFG, FakeLLM(_reply(paraphrase, invented, low, incomplete, JOB)), "m1", stats)
    assert n == 1 and stats.created == 1
    assert stats.rejected == {"quote_not_found": 1, "bad_predicate": 1, "low_confidence": 1, "malformed_proposal": 1}


@pytest.mark.asyncio
async def test_proposals_per_turn_are_capped(db, gw):
    await _message(gw)
    many = [{**JOB, "object": f"job: nurse{i}"} for i in range(ex.MAX_PER_TURN + 3)]
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, FakeLLM(_reply(*many)), "m1", stats)
    assert stats.proposed == ex.MAX_PER_TURN and stats.truncated_proposals == 3


@pytest.mark.asyncio
async def test_reprocessing_is_idempotent(db, gw):
    await _message(gw)
    llm = FakeLLM(_reply(DANA_JOB, WENT))
    first, second = ex.ObservationWorkerStats(), ex.ObservationWorkerStats()
    await ex.process_turn(db, CFG, llm, "m1", first)
    await ex.process_turn(db, CFG, llm, "m1", second)
    assert (first.created, first.duplicate) == (2, 0)
    assert (second.created, second.duplicate) == (0, 2)
    assert len(await obs.observations_for_message(db, "m1")) == 2


@pytest.mark.asyncio
async def test_llm_failure_is_counted_not_raised(db, gw):
    await _message(gw)
    stats = ex.ObservationWorkerStats()
    assert await ex.process_turn(db, CFG, FakeLLM(TimeoutError("slow")), "m1", stats) == 0
    assert stats.llm_failed == 1


@pytest.mark.asyncio
async def test_the_llm_call_runs_off_the_event_loop_with_a_small_cap_and_context(db, gw):
    await _message(gw)
    llm = FakeLLM("[]")
    await ex.process_turn(db, CFG, llm, "m1", ex.ObservationWorkerStats())
    assert llm.threads[0] != threading.get_ident()
    messages, kwargs = llm.calls[0]
    assert kwargs == {"max_tokens": ex.MAX_TOKENS}
    prompt = messages[-1]["content"]
    assert "Speaker: Melanie" in prompt and "Date of message: 2023-05-07" in prompt and TEXT[:20] in prompt


@pytest.mark.asyncio
async def test_llm_disabled_in_config_makes_no_call(db, gw):
    await _message(gw)
    llm = FakeLLM(_reply(JOB))
    cfg = {"observations": {"enabled": True, "llm_enabled": False}}
    await ex.process_turn(db, cfg, llm, "m1", ex.ObservationWorkerStats())
    assert llm.calls == []


def test_stats_details_are_counts_only():
    s = ex.ObservationWorkerStats(turns=2, created=1, rejected={"quote_not_found": 1})
    d = s.as_details()
    assert d == {"turns": 2, "created": 1, "rejected": {"quote_not_found": 1}}
    delta = bd._stats_delta(ex.ObservationWorkerStats(turns=1), s)
    assert delta == {"turns": 1, "created": 1, "rejected": {"quote_not_found": 1}}


@pytest.mark.asyncio
async def test_consolidation_pending_counts_the_observation_backlog():
    from campy.brain.thalamus.tools import _shared, context_status

    class _Result:
        def has_next(self): return False

    class _DB:
        def execute(self, query, params=None): return _Result()

    async def pending():
        return (await context_status({"session_id": "s"}, _DB(), {}))["consolidation_pending"]

    prev_loop = _shared._loop_queue
    try:
        _shared._loop_queue = asyncio.Queue()
        _shared.init_observation_queue(None)
        assert await pending() == 0                       # disabled: unchanged
        oq = asyncio.Queue()
        _shared.init_observation_queue(oq)
        oq.put_nowait(("m1", "s", None))
        oq.put_nowait(("m2", "s", None))
        assert await pending() == 2
        await oq.get()                                    # in flight until task_done
        assert await pending() == 2
        oq.task_done()
        assert await pending() == 1
        _shared._loop_queue = None
        assert await pending() is None                    # no loop queue: still None
    finally:
        _shared._loop_queue = prev_loop
        _shared.init_observation_queue(None)
