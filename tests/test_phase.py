"""Tests for the phase state machine."""
import asyncio
import pytest
from mcp_engine.phase import set_phase, get_phase, subscribe, unsubscribe
import mcp_engine.phase as phase_mod


class TestPhaseStateMachine:
    def setup_method(self):
        """Reset phase state before each test."""
        phase_mod._current_phase = "idle"
        phase_mod._phase_changed_at = 0
        phase_mod._subscribers.clear()
        if phase_mod._idle_handle is not None:
            phase_mod._idle_handle.cancel()
            phase_mod._idle_handle = None

    def test_initial_phase_is_idle(self):
        assert get_phase()["phase"] == "idle"

    def test_set_phase_changes_state(self):
        set_phase("encoding")
        assert get_phase()["phase"] == "encoding"

    def test_set_same_phase_is_noop(self):
        set_phase("encoding")
        t1 = get_phase()["since"]
        set_phase("encoding")
        t2 = get_phase()["since"]
        assert t1 == t2

    def test_invalid_phase_ignored(self):
        set_phase("encoding")
        set_phase("bogus")
        assert get_phase()["phase"] == "encoding"

    def test_subscriber_receives_initial_phase(self):
        q = subscribe()
        msg = q.get_nowait()
        assert msg["event"] == "phase"
        assert msg["data"]["phase"] == "idle"
        unsubscribe(q)

    def test_subscriber_receives_transition(self):
        q = subscribe()
        _ = q.get_nowait()  # consume initial
        set_phase("recalling")
        msg = q.get_nowait()
        assert msg["event"] == "phase"
        assert msg["data"]["phase"] == "recalling"
        unsubscribe(q)

    def test_unsubscribe_stops_delivery(self):
        q = subscribe()
        _ = q.get_nowait()
        unsubscribe(q)
        set_phase("sweeping")
        assert q.empty()

    def test_get_phase_returns_uptime(self):
        set_phase("encoding")
        data = get_phase()
        assert "uptime_s" in data
        assert isinstance(data["uptime_s"], float)
