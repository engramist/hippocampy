"""Work artifact registration handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_ARTIFACT_TYPE_MAP = {
    "backlog/plans": "plan",
    "docs/superpowers/specs": "spec",
    "docs/superpowers": "spec",
    "backlog": "backlog_card",
    "docs": "spec",
}

def _infer_document_type(file_path: str) -> str:
    """Infer document_type from repo-relative file path."""
    for prefix, doc_type in _ARTIFACT_TYPE_MAP.items():
        if file_path.startswith(prefix):
            return doc_type
    name = file_path.lower()
    if "readme" in name:
        return "readme"
    if "adr" in name or "architecture" in name:
        return "adr"
    return "other"


async def register_artifact(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Upsert a WorkArtifact node for a structured document.

    params: {
        file_path     STRING  required — repo-relative path
        document_type STRING  optional — inferred from path if absent
        title         STRING  optional
        summary       STRING  optional
        linked_card   STRING  optional — e.g. "B290"
        session_id    STRING  optional
        agent_source  STRING  optional
    }
    """
    import uuid as _uuid

    file_path = (params.get("file_path") or "").strip()
    if not file_path:
        return {"status": "skipped", "reason": "file_path required"}

    session_id = params.get("session_id", "unknown")
    agent_source = params.get("agent_source", "mcp")
    document_type = params.get("document_type") or _infer_document_type(file_path)
    title = params.get("title", "")
    summary = params.get("summary", "")
    linked_card = params.get("linked_card", "")

    # Infer linked_card from filename if not provided
    if not linked_card:
        import re as _re
        m = _re.search(r'\bB\d+\b', file_path)
        if m:
            linked_card = m.group(0)

    now_iso = datetime.now(timezone.utc).isoformat()

    # Check for existing node by file_path
    existing = await db.execute_read(
        "MATCH (wa:WorkArtifact {file_path: $fp}) RETURN wa.artifact_id",
        {"fp": file_path},
    )

    if existing:
        artifact_id = existing[0].get("wa.artifact_id") or existing[0].get("artifact_id")
        set_parts = ["wa.last_modified_at = timestamp($ts)"]
        up: dict = {"fp": file_path, "ts": now_iso}
        if title:
            set_parts.append("wa.title = $ti"); up["ti"] = title
        if summary:
            set_parts.append("wa.summary = $su"); up["su"] = summary
        if linked_card:
            set_parts.append("wa.linked_card = $lc"); up["lc"] = linked_card
        if document_type:
            set_parts.append("wa.document_type = $dt"); up["dt"] = document_type
        await db.execute_write(
            f"MATCH (wa:WorkArtifact {{file_path: $fp}}) SET {', '.join(set_parts)}",
            up,
        )
    else:
        artifact_id = str(_uuid.uuid4())
        await db.execute_write(
            "CREATE (wa:WorkArtifact {"
            "  artifact_id: $aid, file_path: $fp, document_type: $dt, "
            "  title: $ti, summary: $su, linked_card: $lc, "
            "  session_id: $sess, agent_source: $as, "
            "  created_at: timestamp($ts), last_modified_at: timestamp($ts)"
            "})",
            {
                "aid": artifact_id, "fp": file_path, "dt": document_type,
                "ti": title, "su": summary, "lc": linked_card,
                "sess": session_id, "as": agent_source, "ts": now_iso,
            },
        )
        # Link to Session if known
        if session_id and session_id != "unknown":
            try:
                await db.execute_write(
                    "MATCH (wa:WorkArtifact {artifact_id: $aid}), "
                    "      (s:Session {session_id: $sid}) "
                    "MERGE (wa)-[:CREATED_IN]->(s)",
                    {"aid": artifact_id, "sid": session_id},
                )
            except Exception:
                pass

    return {"status": "ok", "artifact_id": artifact_id, "file_path": file_path}
