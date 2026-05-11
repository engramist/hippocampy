import json

import pytest

from mcp_engine.capture import (
    CaptureJournal,
    ClaudeCodeSessionConnector,
    CodexSessionConnector,
    VSCodeChatSessionConnector,
    parse_claude_code_session_file,
    parse_codex_session_file,
    parse_vscode_chat_session_file,
)


def _write_codex_session(path, *, session_id="sess-1", cwd="/repo"):
    rows = [
        {
            "timestamp": "2026-05-08T01:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd},
        },
        {
            "timestamp": "2026-05-08T01:00:01Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hello sidequests"},
        },
        {
            "timestamp": "2026-05-08T01:00:02Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command"},
        },
        {
            "timestamp": "2026-05-08T01:00:03Z",
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "hello back"},
        },
        "{malformed",
    ]
    with path.open("w") as f:
        for row in rows:
            if isinstance(row, str):
                f.write(row + "\n")
            else:
                f.write(json.dumps(row) + "\n")


def _write_claude_code_session(path, *, session_id="claude-1", cwd="/repo"):
    rows = [
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-05-08T01:00:00Z",
            "cwd": cwd,
            "sessionId": session_id,
            "message": {"role": "user", "content": "hello from claude"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "timestamp": "2026-05-08T01:00:01Z",
            "cwd": cwd,
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "text", "text": "hello back from claude"},
                    {"type": "tool_use", "name": "Bash"},
                ],
            },
        },
        {
            "type": "user",
            "uuid": "tool-result",
            "timestamp": "2026-05-08T01:00:02Z",
            "cwd": cwd,
            "sessionId": session_id,
            "toolUseResult": {"stdout": "ignore"},
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "ignore me"}],
            },
        },
    ]
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_vscode_session(path, *, session_id="vscode-1"):
    rows = [
        {
            "kind": 0,
            "v": {
                "sessionId": session_id,
                "requests": [],
            },
        },
        {
            "kind": 2,
            "v": [
                {
                    "requestId": "req-1",
                    "timestamp": 1778165734621,
                    "message": {"text": "hello from vscode"},
                    "response": [
                        {"kind": "thinking", "value": "hidden"},
                        {"kind": None, "value": "hello back from vscode"},
                        {"kind": "toolInvocationSerialized", "value": "ignore"},
                    ],
                }
            ],
        },
    ]
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_parse_codex_session_file_extracts_user_and_agent_messages(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_codex_session(session)

    events, offset = parse_codex_session_file(session, max_events=10)

    assert offset == session.stat().st_size
    assert [event.role for event in events] == ["user", "assistant"]
    assert [event.content for event in events] == ["hello sidequests", "hello back"]
    assert {event.source_session_id for event in events} == {"sess-1"}
    assert {event.repo_root for event in events} == {"/repo"}


def test_parse_claude_code_session_file_extracts_human_messages_only(tmp_path):
    session = tmp_path / "claude.jsonl"
    _write_claude_code_session(session)

    events, offset = parse_claude_code_session_file(session, max_events=10)

    assert offset == session.stat().st_size
    assert [event.role for event in events] == ["user", "assistant"]
    assert [event.content for event in events] == [
        "hello from claude",
        "hello back from claude",
    ]
    assert {event.source_app for event in events} == {"claude_code"}
    assert {event.source_session_id for event in events} == {"claude-1"}
    assert {event.repo_root for event in events} == {"/repo"}


def test_parse_vscode_chat_session_file_extracts_request_and_response(tmp_path):
    session = tmp_path / "vscode.jsonl"
    _write_vscode_session(session)

    events, offset = parse_vscode_chat_session_file(session, max_events=10)

    assert offset == session.stat().st_size
    assert [event.role for event in events] == ["user", "assistant"]
    assert [event.content for event in events] == [
        "hello from vscode",
        "hello back from vscode",
    ]
    assert {event.source_app for event in events} == {"vscode"}
    assert {event.source_session_id for event in events} == {"vscode-1"}


@pytest.mark.asyncio
async def test_codex_connector_journals_and_dedupes_events(tmp_path):
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    session = sessions_root / "session.jsonl"
    _write_codex_session(session)
    journal = CaptureJournal(tmp_path / "capture")
    connector = CodexSessionConnector(
        sessions_root=sessions_root,
        journal=journal,
        max_events_per_scan=10,
        initial_backfill_events=10,
    )
    ingested = []

    async def ingest(event):
        ingested.append(event.event_id)

    first = await connector.scan_once(ingest=ingest)
    second = await connector.scan_once(ingest=ingest)

    assert first == {"scanned": 2, "journaled": 2, "ingested": 2}
    assert second == {"scanned": 0, "journaled": 0, "ingested": 0}
    assert len(ingested) == 2
    assert len(journal.events_path.read_text().splitlines()) == 2


@pytest.mark.asyncio
async def test_claude_code_connector_journals_and_dedupes_events(tmp_path):
    sessions_root = tmp_path / "claude"
    sessions_root.mkdir()
    session = sessions_root / "session.jsonl"
    _write_claude_code_session(session)
    journal = CaptureJournal(tmp_path / "capture")
    connector = ClaudeCodeSessionConnector(
        sessions_root=sessions_root,
        journal=journal,
        max_events_per_scan=10,
        initial_backfill_events=10,
    )

    first = await connector.scan_once()
    second = await connector.scan_once()

    assert first == {"scanned": 2, "journaled": 2, "ingested": 0}
    assert second == {"scanned": 0, "journaled": 0, "ingested": 0}
    assert len(journal.events_path.read_text().splitlines()) == 2


@pytest.mark.asyncio
async def test_vscode_connector_journals_and_dedupes_events(tmp_path):
    sessions_root = tmp_path / "Code" / "User"
    session_dir = sessions_root / "workspaceStorage" / "abc" / "chatSessions"
    session_dir.mkdir(parents=True)
    session = session_dir / "session.jsonl"
    _write_vscode_session(session)
    journal = CaptureJournal(tmp_path / "capture")
    connector = VSCodeChatSessionConnector(
        sessions_root=sessions_root,
        journal=journal,
        max_events_per_scan=10,
        initial_backfill_events=10,
    )

    first = await connector.scan_once()
    second = await connector.scan_once()

    assert first == {"scanned": 2, "journaled": 2, "ingested": 0}
    assert second == {"scanned": 0, "journaled": 0, "ingested": 0}
    assert "hello from vscode" in journal.events_path.read_text()


@pytest.mark.asyncio
async def test_codex_connector_tails_new_events_after_cursor(tmp_path):
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    session = sessions_root / "session.jsonl"
    _write_codex_session(session)
    journal = CaptureJournal(tmp_path / "capture")
    connector = CodexSessionConnector(
        sessions_root=sessions_root,
        journal=journal,
        max_events_per_scan=10,
        initial_backfill_events=0,
    )

    first = await connector.scan_once()
    with session.open("a") as f:
        f.write(json.dumps({
            "timestamp": "2026-05-08T01:00:04Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "new tail event"},
        }) + "\n")
    second = await connector.scan_once()

    assert first == {"scanned": 0, "journaled": 0, "ingested": 0}
    assert second == {"scanned": 1, "journaled": 1, "ingested": 0}
    assert "new tail event" in journal.events_path.read_text()


@pytest.mark.asyncio
async def test_codex_connector_backfills_only_newest_file_by_default(tmp_path):
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    older = sessions_root / "older.jsonl"
    newer = sessions_root / "newer.jsonl"
    _write_codex_session(older, session_id="older")
    _write_codex_session(newer, session_id="newer")
    older.touch()
    newer.touch()

    journal = CaptureJournal(tmp_path / "capture")
    connector = CodexSessionConnector(
        sessions_root=sessions_root,
        journal=journal,
        max_events_per_scan=10,
        initial_backfill_events=10,
        max_initial_backfill_files=1,
    )

    summary = await connector.scan_once()

    assert summary == {"scanned": 2, "journaled": 2, "ingested": 0}
    text = journal.events_path.read_text()
    assert '"source_session_id": "newer"' in text
    assert '"source_session_id": "older"' not in text
