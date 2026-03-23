from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MISSION_CONTROL_SERVER = ROOT / "mission-control" / "server.py"


def load_mission_control_module():
    spec = importlib.util.spec_from_file_location("mission_control_server", MISSION_CONTROL_SERVER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_card_detail_surfaces_summary_and_blocker_reason(tmp_path):
    mc = load_mission_control_module()

    kanban_path = tmp_path / "kanban.json"
    kanban_path.write_text(json.dumps({
        "tasks": [
            {
                "id": "MC-TEST",
                "title": "Fix the thing",
                "column": "in_progress",
                "priority": "critical",
                "agent": "Claws",
                "phase": "blocked",
                "waiting_on": "dj_decision",
                "notes": "This card updates the slideout so people can quickly understand the work.",
                "card_type": "implementation",
            }
        ]
    }))

    mc.KANBAN_PATH = kanban_path
    client = TestClient(mc.app)

    response = client.get("/api/kanban/card/MC-TEST")

    assert response.status_code == 200
    assert "What this card is doing" in response.text
    assert "This card updates the slideout so people can quickly understand the work." in response.text
    assert "Why it is blocked" in response.text
    assert "Waiting on dj decision." in response.text


def test_board_keeps_auto_refresh_in_js_guard_instead_of_meta_refresh():
    mc = load_mission_control_module()
    client = TestClient(mc.app)

    response = client.get("/board")

    assert response.status_code == 200
    assert "window.setInterval" in response.text
    assert "if (!isSlideoutOpen())" in response.text
    assert 'http-equiv="refresh"' not in response.text
