"""Small, durable activity feed for SideQuests operators.

This log is intentionally separate from the daemon log: it is compact,
user-facing, and redacts full message bodies so it can be watched live.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ACTIVITY_LOG = Path.home() / ".sidequests" / "activity.log"

WRITE_METHODS = {
    "notify_turn",
    "ingest_document",
    "ingest_arc_artifacts",
    "publish_mechanic_summary",
    "register_plan",
    "report_outcome",
    "complete_quest",
    "branch_quest",
    "reload_dictionary",
}

RECALL_METHODS = {
    "current_truth",
    "context_status",
    "recall_relevant_lessons",
    "recall_scene_graph_priors",
    "recall_mechanic_priors",
    "recall_plans",
    "recall_procedures",
    "analogical_search",
    "diff_since",
    "get_open_loops",
    "reconstruct_timeline",
}


def activity_log_path(config: dict | None = None) -> Path:
    """Return configured activity-log path, defaulting under ~/.sidequests."""
    path = ((config or {}).get("activity", {}) or {}).get("log_path")
    if path:
        return Path(path).expanduser()
    return DEFAULT_ACTIVITY_LOG


def classify_method(method: str) -> str:
    """Map an MCP method to the operator-facing activity lane."""
    if method in WRITE_METHODS:
        return "write"
    if method in RECALL_METHODS or method.startswith("recall_"):
        return "recall"
    if method in {"initialize", "tools/list"}:
        return "status"
    return "tool"


def compact_details(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Keep useful operational hints without dumping private content."""
    params = params or {}
    details: dict[str, Any] = {}

    if "session_id" in params:
        details["session"] = _short(params.get("session_id"), 28)
    if "role" in params:
        details["role"] = params.get("role")
    if "domain" in params:
        details["domain"] = params.get("domain")
    if "file_path" in params:
        details["file"] = _short_path(params.get("file_path"))
    if "root" in params:
        details["root"] = _short_path(params.get("root"))
    if "source_root" in params:
        details["root"] = _short_path(params.get("source_root"))

    content = params.get("content")
    if isinstance(content, str):
        details["chars"] = len(content)

    query = params.get("query") or params.get("question")
    if isinstance(query, str):
        details["query"] = _short(query.replace("\n", " "), 80)

    precomputed = params.get("precomputed")
    if isinstance(precomputed, dict):
        if precomputed.get("source_app"):
            details["source"] = precomputed.get("source_app")
        if precomputed.get("capture_event_id"):
            details["event"] = _short(precomputed.get("capture_event_id"), 16)

    if method == "notify_turn" and "source" not in details:
        details["source"] = params.get("source_app") or "mcp"

    return {k: v for k, v in details.items() if v not in (None, "")}


def emit_activity(
    event: str,
    *,
    config: dict | None = None,
    method: str | None = None,
    status: str | None = None,
    lane: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one JSONL activity record and return it for tests/callers."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
    }
    if method:
        record["method"] = method
        record["lane"] = lane or classify_method(method)
    elif lane:
        record["lane"] = lane
    if status:
        record["status"] = status
    if details:
        record["details"] = details

    try:
        path = activity_log_path(config)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        # Activity logging is observability only; never break memory operations.
        record["log_write_failed"] = True
    return record


def read_recent(path: Path, lines: int = 40) -> list[dict[str, Any]]:
    """Read the last N activity records from a JSONL file."""
    if not path.exists():
        return []
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    records: list[dict[str, Any]] = []
    for line in raw_lines[-max(lines, 0):]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"ts": "", "event": "malformed", "details": {"line": line}})
    return records


def follow_records(path: Path, poll_seconds: float = 0.5) -> Iterable[dict[str, Any]]:
    """Yield activity records appended after follow starts."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+", encoding="utf-8") as fh:
        fh.seek(0, 2)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(poll_seconds)
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"ts": "", "event": "malformed", "details": {"line": line.rstrip()}}


def format_activity(record: dict[str, Any]) -> str:
    """Render one compact operator-facing activity line."""
    ts = str(record.get("ts", ""))
    if "T" in ts:
        ts = ts.replace("T", " ").replace("+00:00", "Z")
    lane = str(record.get("lane") or record.get("event") or "event").upper()
    method = record.get("method") or record.get("event") or ""
    status = record.get("status")
    parts = [f"[{ts}]", lane, str(method)]
    if status:
        parts.append(str(status))

    details = record.get("details") or {}
    if isinstance(details, dict) and details:
        detail_text = " ".join(f"{key}={_quote(value)}" for key, value in details.items())
        parts.append(detail_text)
    return " ".join(part for part in parts if part)


def _short(value: Any, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _short_path(value: Any) -> str:
    text = str(value)
    try:
        return str(Path(text).expanduser().name or text)
    except Exception:
        return _short(text, 80)


def _quote(value: Any) -> str:
    text = str(value)
    if not text or any(ch.isspace() for ch in text):
        return json.dumps(text)
    return text
