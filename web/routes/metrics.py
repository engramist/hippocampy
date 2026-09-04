from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from campy.brain.hippocampus.graph.gateway import GraphGateway, get_gateway
from campy.brain.thalamus.working_memory import (
    DEFAULT_TOKEN_LIMIT,
    get_session_token_timeline,
)


def _gateway(db: Any) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return get_gateway(db)


def _row_val(row: Any, idx: int, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if isinstance(row, (list, tuple)) and idx < len(row):
        return row[idx]
    return getattr(row, key, None)


def register_token_metrics_routes(app: FastAPI, db: Any) -> None:
    """Register the token efficiency dashboard endpoints."""

    @app.get("/api/token-metrics")
    def token_metrics(recent: int = 5, timeline_limit: int = 40):
        """Return recent session token usage plus dedup savings."""
        sessions: list[dict[str, Any]] = []
        try:
            gw = _gateway(db)
            rows = gw.run_sync("web.recent_sessions_token_metrics", limit=recent)
            for row in rows:
                session_id = _row_val(row, 0, "s.session_id") or _row_val(row, 0, "session_id")
                started_at = _row_val(row, 1, "s.started_at") or _row_val(row, 1, "started_at")
                last_active_at = _row_val(row, 2, "s.last_active_at") or _row_val(row, 2, "last_active_at")
                token_estimate = int(_row_val(row, 3, "s.token_estimate") or _row_val(row, 3, "token_estimate") or 0)
                raw_limit = _row_val(row, 4, "s.token_limit") or _row_val(row, 4, "token_limit")
                token_limit = int(raw_limit) if raw_limit else DEFAULT_TOKEN_LIMIT
                loaded_nodes = int(_row_val(row, 5, "s.loaded_node_count") or _row_val(row, 5, "loaded_node_count") or 0)
                injection_count = int(_row_val(row, 6, "s.injection_count") or _row_val(row, 6, "injection_count") or 0)
                dedup_saved = int(_row_val(row, 7, "s.dedup_tokens_saved") or _row_val(row, 7, "dedup_tokens_saved") or 0)

                session = {
                    "session_id": session_id,
                    "started_at": str(started_at) if started_at else None,
                    "last_active_at": str(last_active_at) if last_active_at else None,
                    "token_limit": token_limit,
                    "token_estimate": token_estimate,
                    "loaded_node_count": loaded_nodes,
                    "injection_count": injection_count,
                    "dedup_tokens_saved": dedup_saved,
                    "baseline_tokens": token_estimate + dedup_saved,
                }
                session["timeline"] = get_session_token_timeline(
                    db, session_id, limit=timeline_limit
                )
                sessions.append(session)
        except Exception:
            # Fall back to empty list, avoid crashing the dashboard
            sessions = []

        total_tokens = sum(s["token_estimate"] for s in sessions)
        total_saved = sum(s["dedup_tokens_saved"] for s in sessions)
        total_baseline = sum(s["baseline_tokens"] for s in sessions)

        summary = {
            "total_sessions": len(sessions),
            "total_tokens_injected": total_tokens,
            "total_tokens_saved": total_saved,
            "total_baseline_projection": total_baseline,
        }

        return {
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "sessions": sessions,
            "summary": summary,
        }
