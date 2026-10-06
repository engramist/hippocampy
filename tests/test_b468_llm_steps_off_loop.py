"""
B468: the consolidation loop's LLM steps must not freeze the daemon.

`_loop_worker` runs `run_loop` as a task on the daemon's own event loop, so a
synchronous LLM call inside it (Step 2 gist, Step 3b relations, Step 6
arbitration) blocks every request the daemon serves. On LongMemEval a Step 3b
call on a long assistant turn generated 8,000+ tokens until the 180 s Ollama
timeout; the adapter's `notify_turn` timed out meanwhile and reported the
daemon offline. Two fixes, two kinds of test:

- the steps run off the event loop (a ticker keeps running while they block);
- the JSON-only calls cap their output (`max_tokens`), so a degenerate
  generation stops early instead of running to the client timeout.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from tests._spacy import SPACY_AVAILABLE

needs_spacy = pytest.mark.skipif(not SPACY_AVAILABLE, reason="needs spaCy en_core_web_md")


class _RecordingLLM:
    """Returns a fixed reply and records the kwargs of every chat() call."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.reply


# ---------------------------------------------------------------------------
# Output caps
# ---------------------------------------------------------------------------

def test_step3b_caps_its_output():
    from campy.brain.temporal_lobe.loop.step3b_relations import (
        extract_semantic_relations,
    )

    llm = _RecordingLLM("null")
    extract_semantic_relations(
        [{"text": "Redis", "gist_class": "Tool"}, {"text": "Memcached", "gist_class": "Tool"}],
        "We replaced Memcached with Redis.", llm,
    )
    assert llm.calls and 0 < llm.calls[0].get("max_tokens", 0) <= 512


def test_step2_gist_caps_its_output():
    from campy.brain.temporal_lobe.loop.step2_gist import _classify_with_llm

    llm = _RecordingLLM('{"class": "Tool", "confidence": 0.9}')
    _classify_with_llm("Redis", llm)
    assert llm.calls and 0 < llm.calls[0].get("max_tokens", 0) <= 512


def test_step6_arbitration_caps_its_output():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

    llm = _RecordingLLM('{"classification": "additive", "rationale": "same", "referenced_index": 1}')
    arbitrate(
        {"text": "Redis", "gist_class": "Tool"},
        [{"concept_id": "c1", "text_raw": "Redis cache", "similarity": 0.8, "pathway_strength": 0.5}],
        "We use Redis.", llm,
    )
    assert llm.calls and 0 < llm.calls[0].get("max_tokens", 0) <= 512


# ---------------------------------------------------------------------------
# Off the event loop
# ---------------------------------------------------------------------------

class _Result:
    def has_next(self):
        return False

    def get_next(self):
        return None


class _DB:
    def execute(self, query, params=None):
        return _Result()

    async def execute_write(self, query, params=None):
        return None

    async def execute_read(self, query, params=None):
        return []

    def vector_search(self, table_name, index_name, embedding, limit):
        return []


BLOCK_S = 0.4


async def _ticks_during(coro) -> int:
    """How many 10 ms ticks the event loop managed while `coro` ran."""
    ticks = 0
    done = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        await coro
    finally:
        done.set()
        await t
    return ticks


def _blocking(result):
    def step(*args, **kwargs):
        time.sleep(BLOCK_S)  # a slow, synchronous LLM call
        return result
    return step


async def _run_loop_with(monkeypatch, **patches):
    from campy.brain.temporal_lobe.loop import orchestrator

    for name, fn in patches.items():
        monkeypatch.setattr(orchestrator, name, fn)
    return await orchestrator.run_loop(
        message_id="m-b468", text="Alice moved the billing service from Heroku to Fly.io in Berlin.",
        db=_DB(), llm_client=None,
        config={"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
                "nlp": {"spacy_model": "en_core_web_md"}},
        centroids={},
    )


@needs_spacy
@pytest.mark.asyncio
async def test_step3b_does_not_block_the_event_loop(monkeypatch):
    calls = []

    def gist(*args, **kwargs):
        return {"gist_class": "Tool", "confidence": 0.9, "system": "1", "vector": [0.0] * 384}

    def relations(*args, **kwargs):
        calls.append(1)
        time.sleep(BLOCK_S)
        return []

    ticks = await _ticks_during(_run_loop_with(
        monkeypatch, classify_concept=gist, extract_semantic_relations=relations))
    assert calls, "the message did not reach Step 3b; pick a text with 2+ entities"
    # Blocked on the loop, the ticker would get ~0 ticks during the 0.4 s call.
    assert ticks >= 0.5 * BLOCK_S / 0.01


@needs_spacy
@pytest.mark.asyncio
async def test_step2_does_not_block_the_event_loop(monkeypatch):
    ticks = await _ticks_during(_run_loop_with(
        monkeypatch,
        classify_concept=_blocking({"gist_class": None, "confidence": 0.0, "system": "noise", "vector": None})))
    assert ticks >= 0.5 * BLOCK_S / 0.01


@needs_spacy
@pytest.mark.asyncio
async def test_step6_does_not_block_the_event_loop(monkeypatch):
    from campy.brain.temporal_lobe.loop import orchestrator

    calls = []

    def gist(*args, **kwargs):
        return {"gist_class": "Tool", "confidence": 0.9, "system": "1", "vector": [0.0] * 384}

    gray = (orchestrator.MATCH_THRESHOLD + orchestrator.GRAY_ZONE_UPPER) / 2

    def candidates(*args, **kwargs):
        return [{"concept_id": "c-existing", "text_raw": "existing", "similarity": gray}]

    def arbitration(*args, **kwargs):
        calls.append(1)
        time.sleep(BLOCK_S)
        return {"classification": "uncertain", "rationale": "", "referenced_node_ids": []}

    def proceed(*args, **kwargs):
        return {"artifact_type": "decision", "confidence": 0.9, "confidence_low": False,
                "should_proceed": True}

    ticks = await _ticks_during(_run_loop_with(
        monkeypatch, classify_concept=gist, extract_semantic_relations=lambda *a, **k: [],
        classify_artifact=proceed, retrieve_candidates=candidates, arbitrate=arbitration))
    assert calls, "no entity reached Step 6"
    assert ticks >= 0.5 * BLOCK_S / 0.01
