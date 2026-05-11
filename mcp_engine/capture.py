"""
Durable passive capture connectors.

The capture layer is intentionally below MCP. MCP remains the preferred agent
control surface, while this module provides a replayable fallback for clients
that persist local transcripts but do not reliably call notify_turn.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureEvent:
    event_id: str
    source_app: str
    source_session_id: str
    role: str
    content: str
    timestamp: str
    source_path: str
    source_offset: int
    content_hash: str
    repo_root: str = ""

    def notify_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "session_id": self.source_session_id,
            "workspace_path": self.repo_root,
        }
        if self.repo_root:
            params["repo_root"] = self.repo_root
        return params


class CaptureJournal:
    """Append-only event journal plus a compact cursor/seen state file."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root).expanduser() if root else Path.home() / ".sidequests" / "capture"
        self.events_path = self.root / "events.jsonl"
        self.state_path = self.root / "state.json"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"sources": {}, "seen_event_ids": []}
        try:
            state = json.loads(self.state_path.read_text())
        except json.JSONDecodeError:
            _logger.warning("Capture state is malformed; starting with empty state")
            return {"sources": {}, "seen_event_ids": []}
        state.setdefault("sources", {})
        state.setdefault("seen_event_ids", [])
        return state

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.state_path)

    def get_source_state(self, source_key: str) -> dict[str, Any]:
        return dict(self._state.get("sources", {}).get(source_key, {}))

    def set_source_state(self, source_key: str, state: dict[str, Any]) -> None:
        self._state.setdefault("sources", {})[source_key] = dict(state)

    def has_seen(self, event_id: str) -> bool:
        return event_id in set(self._state.get("seen_event_ids", []))

    def append_event(self, event: CaptureEvent) -> bool:
        """Append event if unseen. Returns True when newly journaled."""
        if self.has_seen(event.event_id):
            return False
        record = asdict(event)
        record["ingestion_status"] = "journaled"
        record["journaled_at"] = datetime.now(timezone.utc).isoformat()
        with self.events_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        seen = list(self._state.get("seen_event_ids", []))
        seen.append(event.event_id)
        # Keep state compact; the journal remains the durable audit trail.
        self._state["seen_event_ids"] = seen[-10000:]
        return True


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event_id(*parts: object) -> str:
    raw = "\0".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _codex_content(payload: dict[str, Any]) -> tuple[str, str] | None:
    event_type = payload.get("type")
    if event_type == "user_message":
        return "user", str(payload.get("message") or "")
    if event_type == "agent_message":
        return "assistant", str(payload.get("message") or "")
    return None


def _content_parts_to_text(content: Any, *, include_tool_results: bool = False) -> str:
    """Extract human-readable text from common transcript content shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
                continue
            if not isinstance(part, dict):
                continue
            part_type = part.get("type") or part.get("kind")
            if part_type in {"tool_use", "thinking"}:
                continue
            if part_type == "tool_result" and not include_tool_results:
                continue
            text = part.get("text")
            if text is None and include_tool_results:
                text = part.get("content")
            if isinstance(text, str):
                pieces.append(text)
        return "\n".join(piece for piece in pieces if piece)
    return ""


def parse_codex_session_file(
    path: Path,
    *,
    start_offset: int = 0,
    max_events: int = 100,
) -> tuple[list[CaptureEvent], int]:
    """Parse Codex JSONL transcript events from start_offset."""
    events: list[CaptureEvent] = []
    source_session_id = path.stem
    repo_root = ""
    offset = start_offset

    with path.open("rb") as f:
        f.seek(max(start_offset, 0))
        while len(events) < max_events:
            line_offset = f.tell()
            line = f.readline()
            if not line:
                offset = f.tell()
                break
            offset = f.tell()
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            payload = row.get("payload") or {}
            row_type = row.get("type")
            if row_type == "session_meta":
                source_session_id = str(payload.get("id") or source_session_id)
                repo_root = str(payload.get("cwd") or repo_root)
                continue
            if row_type == "turn_context":
                repo_root = str(payload.get("cwd") or repo_root)
                continue
            if row_type != "event_msg":
                continue

            parsed = _codex_content(payload)
            if not parsed:
                continue
            role, content = parsed
            content = content.strip()
            if not content:
                continue
            timestamp = str(row.get("timestamp") or datetime.now(timezone.utc).isoformat())
            content_hash = _hash_text(content)
            event_id = _event_id("codex", path, line_offset, role, timestamp, content_hash)
            events.append(
                CaptureEvent(
                    event_id=event_id,
                    source_app="codex",
                    source_session_id=source_session_id,
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    source_path=str(path),
                    source_offset=line_offset,
                    content_hash=content_hash,
                    repo_root=repo_root,
                )
            )
    return events, offset


def _claude_content(row: dict[str, Any]) -> tuple[str, str] | None:
    row_type = row.get("type")
    if row_type not in {"user", "assistant"}:
        return None

    # Claude writes tool results, injected skill text, and other meta chatter as
    # user rows too. Those are transport artifacts, not conversation memories.
    if row.get("toolUseResult") is not None or row.get("sourceToolAssistantUUID"):
        return None
    if row.get("isMeta") or row.get("sourceToolUseID"):
        return None

    message = row.get("message") or {}
    role = message.get("role") or row_type
    if role not in {"user", "assistant"}:
        return None

    content = _content_parts_to_text(message.get("content"))
    if not content:
        return None
    return role, content


def parse_claude_code_session_file(
    path: Path,
    *,
    start_offset: int = 0,
    max_events: int = 100,
) -> tuple[list[CaptureEvent], int]:
    """Parse Claude Code JSONL transcript events from start_offset."""
    events: list[CaptureEvent] = []
    source_session_id = path.stem
    repo_root = ""
    offset = start_offset

    with path.open("rb") as f:
        f.seek(max(start_offset, 0))
        while len(events) < max_events:
            line_offset = f.tell()
            line = f.readline()
            if not line:
                offset = f.tell()
                break
            offset = f.tell()
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            source_session_id = str(row.get("sessionId") or source_session_id)
            repo_root = str(row.get("cwd") or repo_root)
            parsed = _claude_content(row)
            if not parsed:
                continue
            role, content = parsed
            content = content.strip()
            if not content:
                continue
            timestamp = str(row.get("timestamp") or datetime.now(timezone.utc).isoformat())
            content_hash = _hash_text(content)
            row_id = row.get("uuid") or line_offset
            event_id = _event_id("claude_code", path, row_id, role, timestamp, content_hash)
            events.append(
                CaptureEvent(
                    event_id=event_id,
                    source_app="claude_code",
                    source_session_id=source_session_id,
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    source_path=str(path),
                    source_offset=line_offset,
                    content_hash=content_hash,
                    repo_root=repo_root,
                )
            )
    return events, offset


def _vscode_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        # VS Code chat sessions store milliseconds since epoch.
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return str(value or datetime.now(timezone.utc).isoformat())


def _vscode_response_text(response: Any) -> str:
    if not isinstance(response, list):
        return ""
    pieces: list[str] = []
    for part in response:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind")
        if kind in {
            "thinking",
            "toolInvocationSerialized",
            "mcpServersStarting",
            "progressTaskSerialized",
        }:
            continue
        value = part.get("value")
        if value is None:
            value = part.get("text")
        if isinstance(value, str) and value.strip():
            pieces.append(value)
    return "\n".join(pieces)


def _vscode_request_events(
    request: dict[str, Any],
    *,
    path: Path,
    source_session_id: str,
    repo_root: str,
    line_offset: int,
) -> list[CaptureEvent]:
    events: list[CaptureEvent] = []
    request_id = str(request.get("requestId") or line_offset)
    timestamp = _vscode_timestamp(request.get("timestamp"))

    message = request.get("message") or {}
    user_text = str(message.get("text") or "").strip()
    if user_text:
        content_hash = _hash_text(user_text)
        events.append(
            CaptureEvent(
                event_id=_event_id("vscode", path, request_id, "user", content_hash),
                source_app="vscode",
                source_session_id=source_session_id,
                role="user",
                content=user_text,
                timestamp=timestamp,
                source_path=str(path),
                source_offset=line_offset,
                content_hash=content_hash,
                repo_root=repo_root,
            )
        )

    assistant_text = _vscode_response_text(request.get("response")).strip()
    if assistant_text:
        content_hash = _hash_text(assistant_text)
        events.append(
            CaptureEvent(
                event_id=_event_id("vscode", path, request_id, "assistant", content_hash),
                source_app="vscode",
                source_session_id=source_session_id,
                role="assistant",
                content=assistant_text,
                timestamp=timestamp,
                source_path=str(path),
                source_offset=line_offset,
                content_hash=content_hash,
                repo_root=repo_root,
            )
        )
    return events


def parse_vscode_chat_session_file(
    path: Path,
    *,
    start_offset: int = 0,
    max_events: int = 100,
) -> tuple[list[CaptureEvent], int]:
    """Parse VS Code / Copilot Chat JSONL session events from start_offset."""
    events: list[CaptureEvent] = []
    source_session_id = path.stem
    repo_root = ""
    offset = start_offset

    with path.open("rb") as f:
        f.seek(max(start_offset, 0))
        while len(events) < max_events:
            line_offset = f.tell()
            line = f.readline()
            if not line:
                offset = f.tell()
                break
            offset = f.tell()
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            value = row.get("v")
            requests: list[dict[str, Any]] = []
            if isinstance(value, dict):
                source_session_id = str(value.get("sessionId") or source_session_id)
                maybe_requests = value.get("requests")
                if isinstance(maybe_requests, list):
                    requests = [r for r in maybe_requests if isinstance(r, dict)]
            elif isinstance(value, list):
                requests = [r for r in value if isinstance(r, dict) and "message" in r]

            for request in requests:
                for event in _vscode_request_events(
                    request,
                    path=path,
                    source_session_id=source_session_id,
                    repo_root=repo_root,
                    line_offset=line_offset,
                ):
                    events.append(event)
                    if len(events) >= max_events:
                        break
                if len(events) >= max_events:
                    break
    return events, offset


class Parser(Protocol):
    def __call__(
        self,
        path: Path,
        *,
        start_offset: int = 0,
        max_events: int = 100,
    ) -> tuple[list[CaptureEvent], int]:
        ...


class JsonlSessionConnector:
    """Scans JSONL transcript files into the durable capture journal."""

    source_app = "jsonl"
    default_root = Path.home()
    glob_pattern = "**/*.jsonl"
    parser: Parser

    def __init__(
        self,
        *,
        sessions_root: Path | str | None = None,
        journal: CaptureJournal | None = None,
        max_events_per_scan: int = 100,
        initial_backfill_events: int = 20,
        max_initial_backfill_files: int = 1,
    ):
        self.sessions_root = Path(sessions_root).expanduser() if sessions_root else self.default_root
        self.journal = journal or CaptureJournal()
        self.max_events_per_scan = max_events_per_scan
        self.initial_backfill_events = initial_backfill_events
        self.max_initial_backfill_files = max_initial_backfill_files

    def iter_session_files(self) -> Iterable[Path]:
        if not self.sessions_root.exists():
            return []
        return sorted(
            self.sessions_root.glob(self.glob_pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _initial_offset(self, path: Path) -> int:
        """Start near the tail for pre-existing files to avoid giant backfills."""
        if self.initial_backfill_events <= 0:
            return path.stat().st_size
        offsets: list[int] = []
        with path.open("rb") as f:
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    break
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if self.row_has_event(row):
                    offsets.append(pos)
        if len(offsets) <= self.initial_backfill_events:
            return 0
        return offsets[-self.initial_backfill_events]

    def row_has_event(self, row: dict[str, Any]) -> bool:
        """Cheap parser probe for backfill calculations."""
        # Default to conservative behavior if a subclass has not provided a
        # row probe: count all JSON rows as possible transcript events.
        return True

    async def scan_once(
        self,
        ingest: Callable[[CaptureEvent], Any] | None = None,
    ) -> dict[str, int]:
        scanned = 0
        journaled = 0
        ingested = 0

        for file_index, path in enumerate(self.iter_session_files()):
            if scanned >= self.max_events_per_scan:
                break
            key = str(path)
            state = self.journal.get_source_state(key)
            current_size = path.stat().st_size
            offset = int(state.get("offset", -1))
            if offset < 0:
                if file_index < self.max_initial_backfill_files:
                    offset = self._initial_offset(path)
                else:
                    offset = current_size
            if offset > current_size:
                offset = 0

            events, new_offset = self.parser(
                path,
                start_offset=offset,
                max_events=self.max_events_per_scan - scanned,
            )
            scanned += len(events)
            for event in events:
                if self.journal.append_event(event):
                    journaled += 1
                    if ingest is not None:
                        await ingest(event)
                        ingested += 1
            self.journal.set_source_state(
                key,
                {
                    "offset": new_offset,
                    "size": current_size,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        self.journal.save()
        return {"scanned": scanned, "journaled": journaled, "ingested": ingested}


class CodexSessionConnector(JsonlSessionConnector):
    """Scans Codex session JSONL files into the durable capture journal."""

    source_app = "codex"
    default_root = Path.home() / ".codex" / "sessions"
    glob_pattern = "**/*.jsonl"
    parser = staticmethod(parse_codex_session_file)

    def row_has_event(self, row: dict[str, Any]) -> bool:
        if row.get("type") == "event_msg":
            payload = row.get("payload") or {}
            if payload.get("type") in {"user_message", "agent_message"}:
                return True
        return False


class ClaudeCodeSessionConnector(JsonlSessionConnector):
    """Scans Claude Code project JSONL files into the durable capture journal."""

    source_app = "claude_code"
    default_root = Path.home() / ".claude" / "projects"
    glob_pattern = "**/*.jsonl"
    parser = staticmethod(parse_claude_code_session_file)

    def row_has_event(self, row: dict[str, Any]) -> bool:
        return _claude_content(row) is not None


class VSCodeChatSessionConnector(JsonlSessionConnector):
    """Scans VS Code / Copilot Chat JSONL files into the durable capture journal."""

    source_app = "vscode"
    default_root = Path.home() / "Library" / "Application Support" / "Code" / "User"
    glob_pattern = "**/chatSessions/*.jsonl"
    parser = staticmethod(parse_vscode_chat_session_file)

    def iter_session_files(self) -> Iterable[Path]:
        if not self.sessions_root.exists():
            return []
        files = {
            *self.sessions_root.glob("**/chatSessions/*.jsonl"),
            *self.sessions_root.glob("**/emptyWindowChatSessions/*.jsonl"),
        }
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def row_has_event(self, row: dict[str, Any]) -> bool:
        value = row.get("v")
        if isinstance(value, dict) and value.get("requests"):
            return True
        if isinstance(value, list) and any(isinstance(r, dict) and "message" in r for r in value):
            return True
        return False
