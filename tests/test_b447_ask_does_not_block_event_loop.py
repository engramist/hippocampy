"""tests/test_b447_ask_does_not_block_event_loop.py -- B447 proof.

`run_ask()` called `llm.chat(messages)` -- a synchronous network call -- directly
inside a coroutine, three separate places (main answer, H2 empty-claim retry,
LLM-prose compression). A synchronous call inside a coroutine blocks the
daemon's single-threaded asyncio event loop for its full duration: every other
coroutine (other ask()/notify_turn calls, the Gated Consolidation Loop worker,
even the health-check endpoint) is cooperatively scheduled on that same loop and
cannot run AT ALL while one is blocked. This is why a chain of slow `ask()`
calls could delay an unrelated write by 100+ seconds (B447's 138s/256s
create_gist_example writes) -- not database contention, an event loop that
could not get to the Loop worker's turn.

These tests prove the fix directly: a concurrent task makes real progress
(ticks a counter every 10ms) *while* run_ask is "talking" to a slow LLM. Before
the fix, a synchronous mock_llm.chat() with a real time.sleep() would have
frozen the counter for the sleep's duration; a real network call would have
done the same. The mocks below simulate that exact slow-network shape.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _SlowSyncLLM:
    """Shaped like the real LLMClient: chat() is a blocking sync call (as a
    real network request would be); achat() offloads it to a thread, exactly
    like campy/brain/llm/provider.py's real achat()."""

    def __init__(self, delay: float, answer: str):
        self.delay = delay
        self.answer = answer
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        time.sleep(self.delay)  # simulates a slow synchronous network call
        return self.answer

    async def achat(self, messages):
        return await asyncio.to_thread(self.chat, messages)


async def _run_ask_stays_concurrent(
    monkeypatch, llm, *, trigger_h2=False, force_compression=False, nonempty_bundle=False,
):
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {"compression": {}, "ask": {"harness_variant": "H2"} if trigger_h2 else {}}
    mock_bundle = MagicMock()
    if force_compression or nonempty_bundle:
        section = MagicMock()
        section.content = [{"text": "some content"}]
        section.token_estimate = 10_000_000 if force_compression else 10
        section.section_type = "summary"
        mock_bundle.sections = [section]
    else:
        mock_bundle.sections = []
    mock_bundle.query = "q"

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    with patch(
        "campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=mock_bundle,
    ), patch(
        "campy.brain.thalamus.ask._get_llm", return_value=llm,
    ), patch(
        "campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock,
    ):
        if trigger_h2:
            monkeypatch.setattr(
                "campy.brain.thalamus.ask._EMPTY_CLAIM_RE",
                __import__("re").compile("EMPTY_CLAIM_MARKER"),
            )
        task = asyncio.ensure_future(ticker())
        t0 = time.perf_counter()
        result = await run_ask(query="q", session_id="s", db=mock_db, config=config)
        elapsed = time.perf_counter() - t0
        task.cancel()
    return result, elapsed, ticks


@pytest.mark.asyncio
async def test_main_answer_does_not_block_event_loop(monkeypatch):
    """AC (B447): while the main llm.chat() call is 'in flight' (0.3s), a
    concurrently-scheduled coroutine keeps ticking -- proving the event loop
    was never blocked. Before the fix (a bare `llm.chat(messages)`), ticks
    would be 0."""
    llm = _SlowSyncLLM(delay=0.3, answer="the answer")
    result, elapsed, ticks = await _run_ask_stays_concurrent(monkeypatch, llm)
    assert result == "the answer"
    assert elapsed >= 0.3
    assert ticks >= 15  # ~0.3s / 0.01s tick, generous margin for scheduling jitter


@pytest.mark.asyncio
async def test_h2_retry_does_not_block_event_loop(monkeypatch):
    """AC (B447): _h2_empty_claim_guard's retry llm.chat() call is the second
    blocking site fixed -- also offloaded."""
    llm = _SlowSyncLLM(delay=0.3, answer="EMPTY_CLAIM_MARKER present")
    # second call (the retry) returns a real answer
    real_answers = iter(["EMPTY_CLAIM_MARKER present", "a real retried answer"])

    def chat(messages, **kwargs):
        llm.calls += 1
        time.sleep(0.15)
        return next(real_answers)

    llm.chat = chat
    # _h2_empty_claim_guard only retries when the bundle is non-empty (an
    # empty bundle legitimately has nothing to answer from) -- give it one
    # real section so the H2 retry path actually fires.
    result, elapsed, ticks = await _run_ask_stays_concurrent(
        monkeypatch, llm, trigger_h2=True, nonempty_bundle=True,
    )
    assert llm.calls == 2  # main + H2 retry
    assert ticks >= 15


@pytest.mark.asyncio
async def test_compression_does_not_block_event_loop(monkeypatch):
    """AC (B447): LLMCompressor.compress()'s llm.chat() call (the third
    blocking site) is also offloaded when a section exceeds budget."""
    llm = _SlowSyncLLM(delay=0.3, answer="compressed text")
    monkeypatch.setattr(
        "campy.brain.thalamus.compression.llm_prose.LLMCompressor._get_llm",
        lambda self: llm,
    )
    result, elapsed, ticks = await _run_ask_stays_concurrent(monkeypatch, llm, force_compression=True)
    assert ticks >= 15
