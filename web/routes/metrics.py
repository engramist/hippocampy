from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from mcp_engine.working_memory import (
    DEFAULT_TOKEN_LIMIT,
    get_session_token_timeline,
)


def register_token_metrics_routes(app: FastAPI, db: Any) -> None:
    """Register the token efficiency dashboard endpoints."""

    @app.get("/api/token-metrics")
    def token_metrics(recent: int = 5, timeline_limit: int = 40):
        """Return recent session token usage plus dedup savings."""
        sessions: list[dict[str, Any]] = []
        try:
            cursor = db.execute(
                """
                MATCH (s:Session)
                RETURN s.session_id, s.started_at, s.last_active_at,
                       s.token_estimate, s.token_limit,
                       s.loaded_node_count, s.injection_count,
                       s.dedup_tokens_saved
                ORDER BY s.last_active_at DESC
                LIMIT $limit
                """,
                {"limit": recent},
            )
            while cursor.has_next():
                row = cursor.get_next()
                session_id = row[0]
                token_estimate = int(row[3] or 0)
                token_limit = int(row[4]) if row[4] else DEFAULT_TOKEN_LIMIT
                loaded_nodes = int(row[5] or 0)
                injection_count = int(row[6] or 0)
                dedup_saved = int(row[7] or 0)

                session = {
                    "session_id": session_id,
                    "started_at": str(row[1]) if row[1] else None,
                    "last_active_at": str(row[2]) if row[2] else None,
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
