from __future__ import annotations
from campy.brain.hippocampus.graph.gateway import get_gateway
"""Work artifact registration handlers."""


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

    # B338: Scrub secrets from title and summary before storing
    from campy.brain.brainstem.secret_scrubber import scrub_before_ingest
    title, _ = await scrub_before_ingest(title)
    summary, _ = await scrub_before_ingest(summary)

    # Infer linked_card from filename if not provided
    if not linked_card:
        import re as _re
        m = _re.search(r'\bB\d+\b', file_path)
        if m:
            linked_card = m.group(0)

    now_iso = datetime.now(timezone.utc).isoformat()

    # Check for existing node by file_path
    gw = get_gateway(db)
    existing = await gw.run("thalamus.artifacts_find_existing", fp=file_path)

    if existing:
        artifact_id = existing[0].get("wa.artifact_id") or existing[0].get("artifact_id")
        await gw.run(
            "thalamus.artifacts_update",
            fp=file_path, ts=now_iso,
            ti=title, su=summary, lc=linked_card, dt=document_type,
        )
    else:
        artifact_id = str(_uuid.uuid4())
        await gw.run(
            "thalamus.artifacts_create",
            aid=artifact_id, fp=file_path, dt=document_type,
            ti=title, su=summary, lc=linked_card,
            sess=session_id, ag_src=agent_source, ts=now_iso,
        )
        # Link to Session if known
        if session_id and session_id != "unknown":
            try:
                await gw.run("thalamus.artifacts_link_session", aid=artifact_id, sid=session_id)
            except Exception:
                pass

    return {"status": "ok", "artifact_id": artifact_id, "file_path": file_path}
