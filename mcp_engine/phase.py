"""Phase state machine for Campy activity indicator."""
import asyncio
import time
from datetime import datetime, timezone
from typing import Set

import logging

logger = logging.getLogger(__name__)

# --- Phase state (module-level singleton) ---
_current_phase: str = "idle"
_phase_changed_at: float = time.time()
_subscribers: Set[asyncio.Queue] = set()
_idle_handle: asyncio.TimerHandle | None = None

VALID_PHASES = {"idle", "encoding", "recalling", "sweeping"}
IDLE_TIMEOUT_S = 3.0
HEARTBEAT_INTERVAL_S = 15.0


def get_phase() -> dict:
    """Return current phase as a dict (for heartbeat endpoint)."""
    return {
        "phase": _current_phase,
        "since": datetime.fromtimestamp(_phase_changed_at, tz=timezone.utc).isoformat(),
        "uptime_s": round(time.time() - _phase_changed_at, 1),
    }


def set_phase(phase: str) -> None:
    """Transition to a new phase and broadcast to SSE subscribers."""
    global _current_phase, _phase_changed_at, _idle_handle

    if phase not in VALID_PHASES:
        logger.warning(f"Invalid phase: {phase}")
        return
    if phase == _current_phase:
        return  # no-op: same phase

    _current_phase = phase
    _phase_changed_at = time.time()
    _broadcast({"event": "phase", "data": get_phase()})

    # Schedule auto-idle if transitioning to a non-idle phase
    if _idle_handle is not None:
        _idle_handle.cancel()
        _idle_handle = None
    if phase != "idle":
        try:
            loop = asyncio.get_running_loop()
            _idle_handle = loop.call_later(IDLE_TIMEOUT_S, _auto_idle)
        except RuntimeError:
            pass  # no event loop (e.g. testing)


def _auto_idle() -> None:
    """Reset to idle after timeout (crash safety)."""
    global _idle_handle
    _idle_handle = None
    set_phase("idle")


def _broadcast(message: dict) -> None:
    """Push a message to all SSE subscriber queues."""
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber. Returns a queue that receives events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(q)
    # Send current phase immediately so subscriber knows the initial state
    q.put_nowait({"event": "phase", "data": get_phase()})
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove an SSE subscriber."""
    _subscribers.discard(q)


async def heartbeat_loop() -> None:
    """Background task that broadcasts heartbeat events to all subscribers."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        if _subscribers:
            _broadcast({"event": "heartbeat", "data": get_phase()})
