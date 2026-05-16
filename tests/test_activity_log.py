import json

from mcp_engine.activity_log import (
    activity_log_path,
    classify_method,
    compact_details,
    emit_activity,
    format_activity,
    read_recent,
)


def test_activity_log_path_can_be_configured(tmp_path):
    path = tmp_path / "campy.activity.jsonl"

    assert activity_log_path({"activity": {"log_path": str(path)}}) == path


def test_classify_method_groups_operator_lanes():
    assert classify_method("notify_turn") == "write"
    assert classify_method("current_truth") == "recall"
    assert classify_method("recall_plans") == "recall"
    assert classify_method("tools/list") == "status"
    assert classify_method("some_future_tool") == "tool"


def test_compact_details_redacts_content_but_keeps_counts():
    details = compact_details(
        "notify_turn",
        {
            "content": "secret full message",
            "role": "user",
            "session_id": "session-123",
            "precomputed": {"source_app": "codex", "capture_event_id": "abcdef1234567890"},
        },
    )

    assert details["chars"] == len("secret full message")
    assert details["role"] == "user"
    assert details["source"] == "codex"
    assert "content" not in details


def test_emit_and_read_recent_activity(tmp_path):
    path = tmp_path / "activity.log"
    config = {"activity": {"log_path": str(path)}}

    record = emit_activity(
        "tool",
        config=config,
        method="current_truth",
        status="ok",
        details={"query": "sidequests status"},
    )

    rows = read_recent(path, lines=10)
    assert rows == [record]
    assert json.loads(path.read_text())["method"] == "current_truth"


def test_format_activity_is_watchable():
    text = format_activity(
        {
            "ts": "2026-05-10T12:00:00+00:00",
            "lane": "write",
            "method": "notify_turn",
            "status": "ok",
            "details": {"source": "codex", "chars": 42},
        }
    )

    assert "[2026-05-10 12:00:00Z]" in text
    assert "WRITE notify_turn ok" in text
    assert "source=codex" in text
    assert "chars=42" in text
