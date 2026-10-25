"""Tests for scripts/gate_slice.py (B520). The dataset loader is not needed: these cover the pure parts."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gate_slice as gs


def test_constructions_match_structural_forms():
    assert gs.matches("count", "How many books has Tim read?")
    assert gs.matches("count", "What is the total spent?")
    assert not gs.matches("count", "Where does Tim live?")
    assert gs.matches("temporal", "When did she move?")
    assert gs.matches("latest", "What is her current job?")
    assert gs.matches("list", "What are all the places he visited?")
    assert gs.matches("list", "Which cities did she visit?")
    assert gs.matches("all", "anything")


def test_propose_prefers_unused_then_most_targets():
    full = {"a": 9, "b": 5, "c": 4}
    capped = {"a": 9, "b": 5, "c": 4}
    picked, total = gs.propose(full, capped, used={"a"}, min_targets=8)
    assert picked == ["b", "c"] and total == 9


def test_propose_falls_back_to_used_and_reports_shortfall():
    picked, total = gs.propose({"a": 3, "b": 2}, {"a": 3, "b": 2}, used={"a", "b"}, min_targets=10)
    assert set(picked) == {"a", "b"} and total == 5


def test_propose_skips_conversations_without_targets():
    picked, _ = gs.propose({"a": 0, "b": 4}, {"a": 0, "b": 4}, used=set(), min_targets=1)
    assert picked == ["b"]


def test_flags_match_runner_options():
    f = gs.flags(["conv-1", "conv-2"], 60)
    assert "--locomo10-conversation-ids conv-1,conv-2" in f
    assert "--locomo10-max-questions 60" in f and "--locomo10-categories 1,2,3,4" in f


def test_committed_history_seeded_with_reused_conversations():
    used = gs.used_conversations(gs.read_history())
    assert {"conv-30", "conv-44"} <= used
    assert gs.used_conversations(gs.read_history("/nonexistent/none.json")) == set()
    json.loads(gs.HISTORY.read_text())
