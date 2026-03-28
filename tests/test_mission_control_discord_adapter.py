import json
import sys
import pytest
from pathlib import Path

from fastapi.testclient import TestClient

_MC_SERVER = Path(__file__).resolve().parent.parent / "mission-control" / "server.py"
pytestmark = pytest.mark.skipif(
    not _MC_SERVER.exists(),
    reason="mission-control/server.py not present (extracted to clawshop repo)"
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mission-control"))

try:
    import server
except ModuleNotFoundError:
    server = None  # type: ignore


def _write_kanban(tmp_path, tasks):
    path = tmp_path / "kanban.json"
    path.write_text(json.dumps({"schema_version": 1, "columns": ["backlog", "in_progress", "under_review", "completed"], "tasks": tasks}))
    return path


def test_discord_execute_dry_run_does_not_persist_ids(tmp_path, monkeypatch):
    kanban_path = _write_kanban(tmp_path, [{
        "id": "MC-025",
        "title": "Implement Discord write adapter",
        "column": "in_progress",
        "phase": "blocked",
        "priority": "high",
        "agent": "Gemini",
        "card_type": "implementation",
        "waiting_on": "dj_decision",
    }])
    monkeypatch.setattr(server, "KANBAN_PATH", kanban_path)

    client = TestClient(server.app)
    resp = client.post("/api/discord/execute/MC-025")
    payload = resp.json()

    assert resp.status_code == 200
    assert payload["dry_run"] is True
    assert {item["kind"] for item in payload["executed"]} == {"anchor", "blocker"}

    stored = json.loads(kanban_path.read_text())["tasks"][0]
    assert stored.get("discord_anchor_message_id") is None
    assert stored.get("discord_blocked_message_id") is None


def test_discord_execute_live_persists_anchor_thread_and_blocker_ids(tmp_path, monkeypatch):
    kanban_path = _write_kanban(tmp_path, [{
        "id": "MC-025",
        "title": "Implement Discord write adapter",
        "column": "in_progress",
        "phase": "blocked",
        "priority": "critical",
        "agent": "Gemini",
        "card_type": "implementation",
        "waiting_on": "dj_decision",
    }])
    monkeypatch.setattr(server, "KANBAN_PATH", kanban_path)
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_ENABLE_WRITES", "1")

    async def fake_execute(task, action, client=None):
        if action["kind"] == "anchor":
            return {
                "kind": "anchor",
                "channel": action["channel"],
                "mode": action["mode"],
                "message_id": "anchor-123",
                "thread_id": "thread-456",
                "thread_state": "open",
            }
        if action["kind"] == "blocker":
            return {
                "kind": "blocker",
                "channel": action["channel"],
                "mode": action["mode"],
                "message_id": "blocker-789",
            }
        raise AssertionError(f"unexpected action: {action['kind']}")

    monkeypatch.setattr(server, "_execute_discord_hook_action", fake_execute)

    client = TestClient(server.app)
    resp = client.post("/api/discord/execute/MC-025", json={"dry_run": False})
    payload = resp.json()

    assert resp.status_code == 200
    assert payload["dry_run"] is False
    assert payload["discord_state"]["discord_anchor_message_id"] == "anchor-123"
    assert payload["discord_state"]["discord_thread_id"] == "thread-456"
    assert payload["discord_state"]["discord_blocked_message_id"] == "blocker-789"

    stored = json.loads(kanban_path.read_text())["tasks"][0]
    assert stored["discord_anchor_channel"] == server.DISCORD_CHANNELS["anchor"]
    assert stored["discord_anchor_message_id"] == "anchor-123"
    assert stored["discord_thread_id"] == "thread-456"
    assert stored["discord_thread_state"] == "open"
    assert stored["discord_blocked_message_id"] == "blocker-789"


def test_discord_execute_live_persists_completion_and_marks_thread_ready(tmp_path, monkeypatch):
    kanban_path = _write_kanban(tmp_path, [{
        "id": "MC-025",
        "title": "Implement Discord write adapter",
        "column": "completed",
        "phase": "completed",
        "priority": "high",
        "agent": "Gemini",
        "card_type": "implementation",
        "discord_anchor_message_id": "anchor-123",
        "discord_thread_id": "thread-456",
    }])
    monkeypatch.setattr(server, "KANBAN_PATH", kanban_path)
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_ENABLE_WRITES", "1")

    async def fake_execute(task, action, client=None):
        if action["kind"] == "completion":
            return {
                "kind": "completion",
                "channel": action["channel"],
                "mode": action["mode"],
                "message_id": "ship-999",
                "thread_id": task["discord_thread_id"],
                "thread_state": "ready_to_archive",
            }
        if action["kind"] == "anchor_reply":
            return {
                "kind": "anchor_reply",
                "channel": action["channel"],
                "mode": action["mode"],
                "message_id": "reply-111",
            }
        raise AssertionError(f"unexpected action: {action['kind']}")

    monkeypatch.setattr(server, "_execute_discord_hook_action", fake_execute)

    client = TestClient(server.app)
    resp = client.post("/api/discord/execute/MC-025", json={"dry_run": False, "signal": "worker_completed"})
    payload = resp.json()

    assert resp.status_code == 200
    assert {item["kind"] for item in payload["executed"]} == {"completion", "anchor_reply"}
    assert payload["discord_state"]["discord_shiplog_message_id"] == "ship-999"
    assert payload["discord_state"]["discord_thread_state"] == "ready_to_archive"

    stored = json.loads(kanban_path.read_text())["tasks"][0]
    assert stored["discord_shiplog_message_id"] == "ship-999"
    assert stored["discord_thread_state"] == "ready_to_archive"


def test_workflow_signal_auto_executes_live_discord_when_enabled(tmp_path, monkeypatch):
    kanban_path = _write_kanban(tmp_path, [{
        "id": "MC-028",
        "title": "Make Discord workflow live",
        "column": "backlog",
        "phase": "planning",
        "priority": "critical",
        "agent": "Gemini",
        "card_type": "implementation",
    }])
    monkeypatch.setattr(server, "KANBAN_PATH", kanban_path)
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_ENABLE_WRITES", "1")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_AUTO_EXECUTE", "1")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_CHANNEL_MISSION_CONTROL", "chan-anchor")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_CHANNEL_BLOCKED_DECISIONS", "chan-blocked")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_CHANNEL_SHIP_LOG", "chan-ship")
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_CHANNEL_WORK_INTAKE", "chan-intake")

    async def fake_execute(task, action, client=None):
        return {
            "kind": action["kind"],
            "channel": action["channel"],
            "mode": action["mode"],
            "message_id": "anchor-321",
            "thread_id": "thread-654",
            "thread_state": "open",
        }

    monkeypatch.setattr(server, "_execute_discord_hook_action", fake_execute)

    client = TestClient(server.app)
    resp = client.post("/api/workflow/signal", json={"task_id": "MC-028", "signal": "worker_started"})
    payload = resp.json()

    assert resp.status_code == 200
    assert payload["discord_execution"]["attempted"] is True
    assert payload["discord_execution"]["ok"] is True
    assert payload["discord_execution"]["executed"][0]["kind"] == "anchor"

    stored = json.loads(kanban_path.read_text())["tasks"][0]
    assert stored["column"] == "in_progress"
    assert stored["phase"] == "running"
    assert stored["discord_anchor_message_id"] == "anchor-321"
    assert stored["discord_thread_id"] == "thread-654"


def test_workflow_signal_reports_precise_discord_config_blocker(tmp_path, monkeypatch):
    kanban_path = _write_kanban(tmp_path, [{
        "id": "MC-028",
        "title": "Make Discord workflow live",
        "column": "backlog",
        "phase": "planning",
        "priority": "critical",
        "agent": "Gemini",
        "card_type": "implementation",
    }])
    monkeypatch.setattr(server, "KANBAN_PATH", kanban_path)
    monkeypatch.setenv("MISSION_CONTROL_DISCORD_AUTO_EXECUTE", "1")

    client = TestClient(server.app)
    resp = client.post("/api/workflow/signal", json={"task_id": "MC-028", "signal": "worker_started"})
    payload = resp.json()

    assert resp.status_code == 200
    assert payload["discord_execution"]["attempted"] is False
    assert payload["discord_execution"]["reason"] == "discord_not_configured"
    assert "MISSION_CONTROL_DISCORD_ENABLE_WRITES=1" in payload["discord_execution"]["config"]["missing"]
    assert "MISSION_CONTROL_DISCORD_BOT_TOKEN" in payload["discord_execution"]["config"]["missing"]
