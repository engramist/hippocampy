"""B434 regression: BrainDaemon._loop_worker must accept the real 5-tuple
shape notify_turn() enqueues -- (message_id, text, role, session_id,
precomputed) -- and thread `precomputed` into run_loop().

Before the fix, _loop_worker unpacked only 4 names against a 5-tuple,
raising ValueError on the very first queued item, before the
surrounding try/except, permanently crash-looping the background
consolidation worker.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import campy.brain_daemon as brain_daemon_mod
from campy.brain_daemon import BrainDaemon


@pytest.mark.asyncio
async def test_loop_worker_unpacks_real_five_tuple_and_forwards_precomputed(monkeypatch):
    fake_self = SimpleNamespace(
        db=object(),
        _llm_client=object(),
        config={},
        _centroids={},
        _loop_queue=asyncio.Queue(),
    )

    run_loop_mock = AsyncMock(return_value={
        "entities_found": 0,
        "concepts_stored": 0,
        "relations_found": 0,
        "noise_count": 0,
    })
    monkeypatch.setattr(brain_daemon_mod, "run_loop", run_loop_mock)

    precomputed_payload = {"entities": [{"text": "PostgreSQL 16"}]}
    # Exactly the shape notify_turn() puts onto the real queue
    # (campy/brain/thalamus/tools/capture.py).
    await fake_self._loop_queue.put(
        ("msg-1", "some turn text", "user", "session-1", precomputed_payload)
    )

    worker_task = asyncio.create_task(BrainDaemon._loop_worker(fake_self))
    try:
        await asyncio.wait_for(fake_self._loop_queue.join(), timeout=2.0)
    except asyncio.TimeoutError:
        worker_task.cancel()
        pytest.fail(
            "loop worker never drained the queue -- unpack likely raised "
            "before reaching run_loop()"
        )

    assert not worker_task.done() or worker_task.exception() is None

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    run_loop_mock.assert_awaited_once()
    _, kwargs = run_loop_mock.call_args
    assert kwargs["message_id"] == "msg-1"
    assert kwargs["text"] == "some turn text"
    assert kwargs["role"] == "user"
    assert kwargs["session_id"] == "session-1"
    assert kwargs["precomputed"] == precomputed_payload


@pytest.mark.asyncio
async def test_loop_worker_survives_precomputed_none(monkeypatch):
    """The common case -- notify_turn() with no precomputed data still
    enqueues a 5-tuple (precomputed=None), which must unpack cleanly too."""
    fake_self = SimpleNamespace(
        db=object(),
        _llm_client=object(),
        config={},
        _centroids={},
        _loop_queue=asyncio.Queue(),
    )

    run_loop_mock = AsyncMock(return_value={
        "entities_found": 0,
        "concepts_stored": 0,
        "relations_found": 0,
        "noise_count": 0,
    })
    monkeypatch.setattr(brain_daemon_mod, "run_loop", run_loop_mock)

    await fake_self._loop_queue.put(("msg-2", "turn text", "user", "session-2", None))

    worker_task = asyncio.create_task(BrainDaemon._loop_worker(fake_self))
    try:
        await asyncio.wait_for(fake_self._loop_queue.join(), timeout=2.0)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    run_loop_mock.assert_awaited_once()
    assert run_loop_mock.call_args.kwargs["precomputed"] is None
