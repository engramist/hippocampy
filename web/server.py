"""
web/server.py — Memory Control Panel (M7)

FastAPI memory/UI surface plus MCP HTTP transport.

Auth model:
    - Loopback with [server].auth = "none": local-only mode, no auth checks.
    - Non-loopback with [server].auth != "none": enforced by
        campy.brain_daemon._enforce_bind_guard, with per-request auth checks in
        _global_http_auth_middleware() below.

Endpoints:
  GET  /                                → Single-page UI (index.html)
  GET  /api/stats                       → Node counts per table
  GET  /api/graph                       → {nodes, edges} for D3.js force graph
  GET  /api/open-loops                  → Soft-lock queue (confidence_low=true)
  POST /api/confirm/{node_id}           → Confirm a soft-lock node
  POST /api/reject/{node_id}            → Archive (reject) a soft-lock node
  GET  /api/merge-events                → Recent MergeEvents (rollback list)
  DELETE /api/merge-events/{id}         → Rollback a MergeEvent
  GET  /api/export/constraint-ledger    → Markdown export
  GET  /api/export/constraint-ledger.json → JSON export
  GET  /api/quests                      → MainQuest + SideQuest hierarchy
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from campy.brain.auth import LocalSingleUserResolver, Principal, TransportContext
from campy.brain.hippocampus.graph.gateway import get_gateway
from web.routes.metrics import register_token_metrics_routes

_logger = logging.getLogger(__name__)

# Registry of active SSE connections: connection_id → asyncio.Queue
_sse_connections: dict[str, asyncio.Queue] = {}

# SSE keepalive interval. The deprecated /sse stream blocks this long between
# disconnect checks, so closing a client stalls up to this duration — tests
# patch it down to avoid the wait.
_SSE_KEEPALIVE_SECONDS = 30.0

STATIC_DIR = Path(__file__).parent / "static"
WEB_VERSION = "0.1.0"

def _row_val(row, idx: int, key: str):
    if isinstance(row, dict):
        # `key` matches Kuzu's real column name for a simple property
        # RETURN (e.g. "n.text_raw"), but Kuzu does not name computed
        # expression columns after their literal text (e.g. RETURN label(r)
        # is not a "label(r)" column) — fall back to position for those.
        if key in row:
            return row[key]
        vals = list(row.values())
        return vals[idx] if idx < len(vals) else None
    if isinstance(row, (list, tuple)) and idx < len(row):
        return row[idx]
    return getattr(row, key, None)

# ---------------------------------------------------------------------------
# Artifact table registry (table_name → primary_key_column)
# ---------------------------------------------------------------------------

ARTIFACT_TABLES = [
    ("Concept",     "concept_id"),
    ("Decision",    "decision_id"),
    ("Constraint",  "constraint_id"),
    ("Requirement", "requirement_id"),
    ("ActionItem",  "action_item_id"),
]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(db, config: dict | None = None, *, principal_resolver=None, router=None) -> FastAPI:
    """
    Create the FastAPI app with a db reference and optional config dict.
    Called by BrainDaemon.start() with the live KuzuClient.
    For tests, pass a mock db that implements .execute() and .execute_write().

    config is used by the SSE /mcp endpoint to pass to tool handlers.

    B325: `principal_resolver` (a `campy.brain.auth.PrincipalResolver`) is
    what the streamable-HTTP `/mcp` transport uses to derive a Principal
    from each request's headers, before its body is parsed — the same
    structural rule `campy/brain_daemon.py::_handle_connection` follows
    for the Unix socket transport. Defaults to `LocalSingleUserResolver()`
    so every existing caller of `create_app(db)` (tests included) keeps
    working exactly as before; `BrainDaemon.start()` passes the resolver
    built from `[server].auth` once the B325 bind guard has passed.

    B316: `router` (a `campy.brain.hippocampus.graph.router.WorkspaceRouter`)
    is what `tools/call` resolves its database from, keyed on
    `principal.workspace_id` — the same routing the Unix-socket transport
    does in `BrainDaemon._dispatch`. `None` (the default — every existing
    test) falls back to the fixed `db` this function was called with,
    matching pre-B316 behavior exactly.
    """
    _config = config or {}
    _server_cfg = _config.get("server", {}) if isinstance(_config.get("server"), dict) else {}
    _auth_mode = str(_server_cfg.get("auth", "none")).lower()
    _auth_required = _auth_mode != "none"
    _dashboard_enabled_raw = _server_cfg.get("dashboard_enabled", True)
    _dashboard_enabled = str(_dashboard_enabled_raw).strip().lower() not in {
        "0", "false", "no", "off"
    }
    _principal_resolver = principal_resolver or LocalSingleUserResolver()
    _router = router
    gw = get_gateway(db)
    app = FastAPI(
        title="SideQuest Memory Control Panel",
        version=WEB_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def _global_http_auth_middleware(request: Request, call_next):
        if not _auth_required or request.url.path == "/health":
            return await call_next(request)

        transport_ctx = TransportContext(transport="http", headers=dict(request.headers))
        try:
            principal = await _principal_resolver.resolve(transport_ctx)
        except Exception as e:
            if request.url.path == "/mcp" and request.method.upper() == "POST":
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32001, "message": f"Unauthorized: {e}"},
                    },
                    status_code=401,
                )
            return JSONResponse({"detail": f"Unauthorized: {e}"}, status_code=401)

        request.state.principal = principal
        return await call_next(request)

    # Serve static assets (CSS, JS, icons)
    if STATIC_DIR.exists() and _dashboard_enabled:
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ------------------------------------------------------------------
    # Main UI & Deep-links
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health():
        """Lightweight liveness probe used by hook scripts and setup smoke tests."""
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(
            "<h1>SideQuest Memory Control Panel</h1><p>UI not found.</p>"
        )

    @app.get("/memory/node/{node_id}", response_class=HTMLResponse)
    async def node_detail_page(node_id: str, context: str | None = None):
        """Deep-link entry point. Serves index.html; client-side JS handles the rest."""
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return HTMLResponse(
            "<h1>SideQuest Memory Control Panel</h1><p>UI not found.</p>"
        )

    # ------------------------------------------------------------------
    # Stats & Node Details
    # ------------------------------------------------------------------

    @app.get("/api/node/{node_id}")
    def get_node_detail(node_id: str):
        """Fetch a single node's details and its immediate neighbors."""
        # Find which table this node belongs to
        node_data = None
        node_table = None
        pk_col = None

        for table, pk in ARTIFACT_TABLES + [
            ("Message",     "message_id"),
            ("Document",    "document_id"),
            ("MainQuest",   "quest_id"),
            ("SideQuest",   "quest_id"),
            ("Lesson",      "lesson_id"),
        ]:
            try:
                rows = gw.run_sync(f"web.get_node_{table.lower()}", id=node_id)
                if rows:
                    node_data = _row_val(rows[0], 0, "n")
                    node_table = table
                    pk_col = pk
                    break
            except Exception:
                continue

        if not node_data:
            raise HTTPException(status_code=404, detail="Node not found")

        # Convert Kuzu node to dict, handling timestamp/UUID if needed
        result = {
            "id": node_id,
            "type": node_table,
            "properties": node_data,
            "neighbors": []
        }

        # Fetch 1-hop neighbors
        try:
            rows = gw.run_sync(f"web.get_neighbors_{node_table.lower()}", id=node_id)
            for row in rows:
                neighbor_node = _row_val(row, 0, "m")
                neighbor_label = _row_val(row, 1, "label(m)")
                rel_label = _row_val(row, 2, "label(r)")

                # Get neighbor's ID (might be different PK columns)
                nid = "unknown"
                if isinstance(neighbor_node, dict):
                    for _, pk in ARTIFACT_TABLES + [("Message", "message_id"), ("Document", "document_id"), ("MainQuest", "quest_id"), ("SideQuest", "quest_id"), ("Lesson", "lesson_id")]:
                        if pk in neighbor_node:
                            nid = neighbor_node[pk]
                            break
                    text_val = neighbor_node.get("text_raw", neighbor_node.get("name", ""))[:100]
                else:
                    text_val = ""

                result["neighbors"].append({
                    "id": nid,
                    "type": neighbor_label,
                    "relation": rel_label,
                    "text": text_val
                })
        except Exception:
            pass

        return result

    @app.get("/api/stats")
    def get_stats():  # W1: sync → FastAPI runs in threadpool
        """Return node counts for all artifact tables."""
        counts = {}
        for table, pk in ARTIFACT_TABLES + [
            ("Message",     "message_id"),
            ("Document",    "document_id"),
            ("MergeEvent",  "merge_event_id"),
            ("MainQuest",   "quest_id"),
            ("SideQuest",   "quest_id"),
        ]:
            key = table.lower()
            try:
                query_name = (
                    f"web.count_total_{key}"
                    if table in ("Document", "MergeEvent")
                    else f"web.count_active_{key}"
                )
                rows = gw.run_sync(query_name)
                counts[key] = _row_val(rows[0], 0, "count(n)") if rows else 0
            except Exception:
                counts[key] = 0
        return counts

    register_token_metrics_routes(app, db)

    # ------------------------------------------------------------------
    # Graph visualization
    # ------------------------------------------------------------------

    @app.get("/api/graph")
    def get_graph():  # W1: sync → FastAPI runs in threadpool
        """
        Return nodes + edges for a D3.js force-directed graph.
        Samples the strongest/most recent nodes from each artifact table.
        """
        nodes = []
        edges = []
        seen_ids: set[str] = set()

        def _add_node(nid, label, node_type, **extra):
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append({"id": nid, "label": (label or "")[:60],
                               "type": node_type, **extra})

        # Concept nodes (top 30 by strength)
        try:
            rows = gw.run_sync("web.graph_concepts")
            for row in rows:
                _add_node(_row_val(row, 0, "c.concept_id") or _row_val(row, 0, "concept_id"),
                          _row_val(row, 1, "c.text_raw") or _row_val(row, 1, "text_raw") or "",
                          "Concept",
                          gist_class=_row_val(row, 2, "c.gist_class") or _row_val(row, 2, "gist_class"),
                          confidence=_row_val(row, 3, "c.confidence") or _row_val(row, 3, "confidence"),
                          pathway_strength=_row_val(row, 4, "c.pathway_strength") or _row_val(row, 4, "pathway_strength"),
                          soft_lock=bool(_row_val(row, 5, "c.confidence_low") or _row_val(row, 5, "confidence_low")))
        except Exception:
            pass

        # Decision nodes
        try:
            rows = gw.run_sync("web.graph_decisions")
            for row in rows:
                _add_node(_row_val(row, 0, "d.decision_id") or _row_val(row, 0, "decision_id"),
                          _row_val(row, 1, "d.text_raw") or _row_val(row, 1, "text_raw") or "",
                          "Decision",
                          confidence=_row_val(row, 2, "d.confidence") or _row_val(row, 2, "confidence"),
                          pathway_strength=_row_val(row, 3, "d.pathway_strength") or _row_val(row, 3, "pathway_strength"),
                          soft_lock=bool(_row_val(row, 4, "d.confidence_low") or _row_val(row, 4, "confidence_low")))
        except Exception:
            pass

        # Constraint nodes
        try:
            rows = gw.run_sync("web.graph_constraints")
            for row in rows:
                _add_node(_row_val(row, 0, "c.constraint_id") or _row_val(row, 0, "constraint_id"),
                          _row_val(row, 1, "c.text_raw") or _row_val(row, 1, "text_raw") or "",
                          "Constraint",
                          confidence=_row_val(row, 2, "c.confidence") or _row_val(row, 2, "confidence"),
                          pathway_strength=_row_val(row, 3, "c.pathway_strength") or _row_val(row, 3, "pathway_strength"),
                          soft_lock=bool(_row_val(row, 4, "c.confidence_low") or _row_val(row, 4, "confidence_low")))
        except Exception:
            pass

        # MainQuest nodes
        try:
            rows = gw.run_sync("web.graph_main_quests")
            for row in rows:
                _add_node(_row_val(row, 0, "q.quest_id") or _row_val(row, 0, "quest_id"),
                          _row_val(row, 1, "q.name") or _row_val(row, 1, "name") or "",
                          "MainQuest",
                          status=_row_val(row, 2, "q.status") or _row_val(row, 2, "status"))
        except Exception:
            pass

        # SideQuest nodes
        try:
            rows = gw.run_sync("web.graph_side_quests")
            for row in rows:
                _add_node(_row_val(row, 0, "q.quest_id") or _row_val(row, 0, "quest_id"),
                          _row_val(row, 1, "q.name") or _row_val(row, 1, "name") or "",
                          "SideQuest",
                          status=_row_val(row, 2, "q.status") or _row_val(row, 2, "status"))
        except Exception:
            pass

        # --- Edges ---

        # CO_OCCURS_WITH (Concept ↔ Concept)
        try:
            rows = gw.run_sync("web.graph_co_occurs_with")
            for row in rows:
                src = _row_val(row, 0, "a.concept_id") or _row_val(row, 0, "concept_id")
                tgt = _row_val(row, 1, "b.concept_id") or _row_val(row, 1, "concept_id")
                strength = _row_val(row, 2, "r.strength") or _row_val(row, 2, "strength")
                count = _row_val(row, 3, "r.count") or _row_val(row, 3, "count")
                if src in seen_ids and tgt in seen_ids:
                    edges.append({"source": src, "target": tgt,
                                  "type": "CO_OCCURS_WITH",
                                  "strength": strength, "count": count})
        except Exception:
            pass

        # DEPRECATED_BY (Concept → Concept)
        try:
            rows = gw.run_sync("web.graph_deprecated_by")
            for row in rows:
                src = _row_val(row, 0, "old.concept_id") or _row_val(row, 0, "concept_id")
                tgt = _row_val(row, 1, "new.concept_id") or _row_val(row, 1, "concept_id")
                if src in seen_ids and tgt in seen_ids:
                    edges.append({"source": src, "target": tgt,
                                  "type": "DEPRECATED_BY"})
        except Exception:
            pass

        # BELONGS_TO (SideQuest → MainQuest)
        try:
            rows = gw.run_sync("web.graph_belongs_to")
            for row in rows:
                edges.append({"source": _row_val(row, 0, "sq.quest_id") or _row_val(row, 0, "quest_id"),
                              "target": _row_val(row, 1, "mq.quest_id") or _row_val(row, 1, "quest_id"),
                              "type": "BELONGS_TO"})
        except Exception:
            pass

        return {"nodes": nodes, "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges)}

    # ------------------------------------------------------------------
    # Open Loops — soft-lock confirmation queue
    # ------------------------------------------------------------------

    @app.get("/api/open-loops")
    def get_open_loops():  # W1: sync → FastAPI runs in threadpool
        """
        Return all nodes with confidence_low=true and archived=false.
        These await user confirmation or rejection in the UI.
        """
        items = []

        for table, id_col in ARTIFACT_TABLES:
            try:
                rows = gw.run_sync(f"web.open_loops_{table.lower()}")
                for row in rows:
                    items.append({
                        "node_id":    _row_val(row, 0, f"n.{id_col}") or _row_val(row, 0, id_col),
                        "node_type":  table,
                        "text_raw":   _row_val(row, 1, "n.text_raw") or _row_val(row, 1, "text_raw"),
                        "confidence": _row_val(row, 2, "n.confidence") or _row_val(row, 2, "confidence"),
                        "created_at": str(_row_val(row, 3, "n.created_at") or _row_val(row, 3, "created_at")),
                    })
            except Exception:
                pass

        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"items": items, "count": len(items)}

    @app.post("/api/confirm/{node_id}")
    async def confirm_node(node_id: str):
        """
        Confirm a soft-lock node: set confidence_low=false, confidence=0.95.
        Searches all artifact tables to find the node.
        """
        for table, id_col in ARTIFACT_TABLES:
            try:
                rows = await gw.run(f"web.find_soft_lock_{table.lower()}", nid=node_id)
                if rows:
                    await gw.run(f"web.confirm_soft_lock_{table.lower()}", nid=node_id)
                    return {"confirmed": True, "node_id": node_id,
                            "node_type": table}
            except Exception:
                continue
        raise HTTPException(status_code=404,
                            detail=f"Node '{node_id}' not found")

    @app.post("/api/reject/{node_id}")
    async def reject_node(node_id: str):
        """Archive a soft-lock node (user rejects the extraction)."""
        for table, id_col in ARTIFACT_TABLES:
            try:
                rows = await gw.run(f"web.find_soft_lock_{table.lower()}", nid=node_id)
                if rows:
                    await gw.run(f"web.reject_soft_lock_{table.lower()}", nid=node_id)
                    return {"rejected": True, "node_id": node_id,
                            "node_type": table}
            except Exception:
                continue
        raise HTTPException(status_code=404,
                            detail=f"Node '{node_id}' not found")

    # ------------------------------------------------------------------
    # Merge Events — rollback UI
    # ------------------------------------------------------------------

    @app.get("/api/merge-events")
    def get_merge_events():  # W1: sync → FastAPI runs in threadpool
        """List recent MergeEvents with rollback metadata."""
        events = []
        try:
            rows = gw.run_sync("web.list_merge_events")
            for row in rows:
                meta = _row_val(row, 3, "me.metadata_patch") or ""
                already_rolled_back = "rolled_back=true" in meta
                merge_type = ("contradiction" if "contradiction" in meta
                              else "additive")
                events.append({
                    "merge_event_id":         _row_val(row, 0, "me.merge_event_id"),
                    "pre_pathway_strength":   _row_val(row, 1, "me.pre_pathway_strength"),
                    "delta_pathway_strength": _row_val(row, 2, "me.delta_pathway_strength"),
                    "merge_type":             merge_type,
                    "metadata_patch":         meta,
                    "already_rolled_back":    already_rolled_back,
                    "created_at":             str(_row_val(row, 4, "me.created_at")),
                })
        except Exception:
            pass
        return {"events": events, "count": len(events)}

    @app.delete("/api/merge-events/{merge_event_id}")
    async def rollback_merge(merge_event_id: str):
        """
        Rollback a contradiction MergeEvent:
          1. Un-archive the old Concept, restore pre_pathway_strength
          2. Archive the new Concept
          3. Mark MergeEvent metadata as rolled_back=true
        Additive MergeEvents: only restore strength on linked Concept.
        """
        try:
            rows = await gw.run("web.get_merge_event", meid=merge_event_id)
            if not rows:
                raise HTTPException(
                    status_code=404,
                    detail=f"MergeEvent '{merge_event_id}' not found"
                )
            row = rows[0]
            metadata     = _row_val(row, 0, "me.metadata_patch") or ""
            pre_strength = float(_row_val(row, 1, "me.pre_pathway_strength") or 0.5)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if "rolled_back=true" in metadata:
            raise HTTPException(status_code=409,
                                detail="MergeEvent already rolled back")

        result = {"rolled_back": True, "merge_event_id": merge_event_id}

        # Contradiction rollback
        if "contradiction" in metadata:
            try:
                # Parse "contradiction:old=<old_id>,new=<new_id>"
                after_colon = metadata.split(":old=", 1)[1]
                old_id, new_id = after_colon.split(",new=", 1)
                new_id = new_id.split(";")[0]  # strip any trailing metadata
            except (IndexError, ValueError):
                old_id = new_id = None

            if old_id and new_id:
                try:
                    await gw.run("web.rollback_restore_old_concept", id=old_id, strength=pre_strength)
                    await gw.run("web.rollback_archive_new_concept", id=new_id)
                    await gw.run("web.rollback_delete_deprecated_by", old_id=old_id, new_id=new_id)
                    result.update({"old_concept_restored": old_id,
                                   "new_concept_archived": new_id})
                except Exception as e:
                    raise HTTPException(status_code=500,
                                        detail=f"Rollback failed: {e}")

        # Mark as rolled back
        try:
            await gw.run("web.rollback_mark_merge_event", meid=merge_event_id, meta=metadata + ";rolled_back=true")
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Constraint Ledger export
    # ------------------------------------------------------------------

    def _collect_ledger() -> list[dict]:
        """Fetch all active Constraints + GlobalConstraints sorted by strength."""
        rows = []
        for table, query_name in [
            ("Constraint",       "web.ledger_constraint"),
            ("GlobalConstraint", "web.ledger_global_constraint"),
        ]:
            try:
                res_rows = gw.run_sync(query_name)
                for row in res_rows:
                    rows.append({
                        "constraint_id":    _row_val(row, 0, "c.constraint_id") or _row_val(row, 0, "c.global_constraint_id"),
                        "table":            table,
                        "text_raw":         _row_val(row, 1, "c.text_raw"),
                        "confidence":       _row_val(row, 2, "c.confidence"),
                        "confidence_low":   bool(_row_val(row, 3, "c.confidence_low")),
                        "pathway_strength": _row_val(row, 4, "c.pathway_strength"),
                        "created_at":       str(_row_val(row, 5, "c.created_at")),
                    })
            except Exception:
                pass
        rows.sort(key=lambda r: r.get("pathway_strength") or 0, reverse=True)
        return rows

    @app.get("/api/export/constraint-ledger")
    async def export_ledger_md():
        """Export all active constraints as Markdown (downloadable)."""
        rows = _collect_ledger()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            "# SideQuest Constraint Ledger",
            f"\nExported: {now}  ",
            f"Total active constraints: {len(rows)}\n",
        ]
        if rows:
            lines.append("| # | Status | Strength | Constraint |")
            lines.append("|---|--------|----------|------------|")
            for i, row in enumerate(rows, 1):
                status   = "?" if row["confidence_low"] else "✓"
                strength = f"{row['pathway_strength']:.2f}"
                text     = row["text_raw"].replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {i} | {status} | {strength} | {text} |")
        else:
            lines.append("_No active constraints._")

        md = "\n".join(lines) + "\n"
        return Response(
            content=md,
            media_type="text/markdown",
            headers={
                "Content-Disposition": "attachment; filename=constraint-ledger.md"
            },
        )

    @app.get("/api/export/constraint-ledger.json")
    async def export_ledger_json():
        """Export all active constraints as JSON (downloadable)."""
        rows = _collect_ledger()
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count":       len(rows),
            "constraints": rows,
        }
        return JSONResponse(
            content=payload,
            headers={
                "Content-Disposition": "attachment; filename=constraint-ledger.json"
            },
        )

    # ------------------------------------------------------------------
    # Quests
    # ------------------------------------------------------------------

    @app.get("/api/quests")
    def get_quests():  # W1: sync → FastAPI runs in threadpool
        """List all MainQuests with nested SideQuests."""
        quests    = []
        quest_map: dict[str, dict] = {}

        try:
            rows = gw.run_sync("web.quests_main")
            for row in rows:
                quest = {
                    "quest_id":   _row_val(row, 0, "q.quest_id"),
                    "name":       _row_val(row, 1, "q.name"),
                    "status":     _row_val(row, 2, "q.status"),
                    "purpose":    _row_val(row, 3, "q.purpose"),
                    "created_at": str(_row_val(row, 4, "q.created_at")),
                    "type":       "MainQuest",
                    "side_quests": [],
                }
                quests.append(quest)
                quest_map[quest["quest_id"]] = quest
        except Exception:
            pass

        try:
            rows = gw.run_sync("web.quests_side_belongs_to")
            for row in rows:
                sq = {
                    "quest_id":   _row_val(row, 0, "sq.quest_id"),
                    "name":       _row_val(row, 1, "sq.name"),
                    "status":     _row_val(row, 2, "sq.status"),
                    "purpose":    _row_val(row, 3, "sq.purpose"),
                    "created_at": str(_row_val(row, 4, "sq.created_at")),
                    "type":       "SideQuest",
                }
                parent_id = _row_val(row, 5, "mq.quest_id")
                if parent_id in quest_map:
                    quest_map[parent_id]["side_quests"].append(sq)
                else:
                    quests.append({**sq, "side_quests": []})
        except Exception:
            pass

        return {"quests": quests, "count": len(quests)}

    # ------------------------------------------------------------------
    # B39 — Thinking tab data (decisions, concepts, open loops)
    # ------------------------------------------------------------------

    @app.get("/api/thinking")
    def get_thinking():  # W1: sync → FastAPI runs in threadpool
        """
        Return rich cognition data for the Mission Control Thinking tab.
        Includes top decisions, top concepts, and open loop count.
        """
        result = {
            "decisions": [],
            "concepts": [],
            "open_loops_count": 0,
            "constraints": [],
            "stats": {},
        }

        # Top decisions (by pathway_strength)
        try:
            rows = gw.run_sync("web.thinking_decisions")
            for row in rows:
                result["decisions"].append({
                    "id": _row_val(row, 0, "d.decision_id"),
                    "text": _row_val(row, 1, "d.text_raw"),
                    "confidence": round(float(_row_val(row, 2, "d.confidence") or 0), 3),
                    "strength": round(float(_row_val(row, 3, "d.pathway_strength") or 0), 3),
                    "soft_lock": bool(_row_val(row, 4, "d.confidence_low")),
                    "created_at": str(_row_val(row, 5, "d.created_at")),
                })
        except Exception:
            pass

        # Top concepts (by pathway_strength, for tag cloud)
        try:
            rows = gw.run_sync("web.thinking_concepts")
            for row in rows:
                result["concepts"].append({
                    "id": _row_val(row, 0, "c.concept_id"),
                    "text": _row_val(row, 1, "c.text_raw"),
                    "gist_class": _row_val(row, 2, "c.gist_class"),
                    "strength": round(float(_row_val(row, 3, "c.pathway_strength") or 0), 3),
                    "soft_lock": bool(_row_val(row, 4, "c.confidence_low")),
                })
        except Exception:
            pass

        # Active constraints
        try:
            rows = gw.run_sync("web.thinking_constraints")
            for row in rows:
                result["constraints"].append({
                    "id": _row_val(row, 0, "c.constraint_id"),
                    "text": _row_val(row, 1, "c.text_raw"),
                    "confidence": round(float(_row_val(row, 2, "c.confidence") or 0), 3),
                    "strength": round(float(_row_val(row, 3, "c.pathway_strength") or 0), 3),
                    "soft_lock": bool(_row_val(row, 4, "c.confidence_low")),
                })
        except Exception:
            pass

        # Open loops count (confidence_low nodes not yet confirmed)
        try:
            total = 0
            for table in ["Concept", "Decision", "Constraint"]:
                rows = gw.run_sync(f"web.count_open_loops_{table.lower()}")
                if rows:
                    total += _row_val(rows[0], 0, "count(n)") or 0
            result["open_loops_count"] = total
        except Exception:
            pass

        # Node counts for stats panel
        try:
            for table, key in [
                ("Concept", "concepts"),
                ("Decision", "decisions"),
                ("Constraint", "constraints"),
                ("MainQuest", "quests"),
                ("Message", "messages"),
            ]:
                rows = gw.run_sync(f"web.count_active_{table.lower()}")
                result["stats"][key] = _row_val(rows[0], 0, "count(n)") if rows else 0
        except Exception:
            pass

        return result

    @app.get("/sse")
    async def mcp_sse(request: Request):
        """
        Deprecated MCP SSE stream.

        Legacy clients still use this endpoint to discover a connection-specific
        POST URL, but new clients should use POST /mcp directly.
        """
        connection_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        _sse_connections[connection_id] = queue

        async def event_generator():
            try:
                # First event: tell client where to POST
                yield f"event: endpoint\ndata: /mcp?connection_id={connection_id}\n\n"

                while True:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(
                            queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                        )
                        yield f"event: message\ndata: {json.dumps(data)}\n\n"
                    except asyncio.TimeoutError:
                        # Keepalive — SSE comment (colon prefix = no-op to client)
                        yield ": keepalive\n\n"
            finally:
                _sse_connections.pop(connection_id, None)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "Deprecation": "true",
                "Sunset": "2026-09-01",
                "Link": '</mcp>; rel="successor-version"',
            },
        )

    async def _mcp_post_legacy_sse(request: Request, connection_id: str, principal: Principal):
        """Legacy SSE transport (MCP 2024-11-05). Kept for ChatGPT Desktop adapter."""
        queue = _sse_connections.get(connection_id)
        if not queue:
            return JSONResponse(
                {"error": "No active SSE connection for this connection_id"},
                status_code=400
            )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        response = await _dispatch_mcp(body, db, _config, principal, _router)
        if response is not None:
            await queue.put(response)

        return JSONResponse({"status": "ok"})

    @app.post("/mcp")
    async def mcp_post(request: Request):
        """
        Streamable HTTP transport (MCP 2025-03-26).

        Accepts JSON-RPC 2.0 requests and returns results directly in the
        HTTP response body. No connection_id or SSE stream needed.

        Also supports legacy SSE transport via connection_id query param
        for backwards compatibility with ChatGPT Desktop adapter.
        """
        expected_token = os.environ.get("SIDEQUESTS_BRAIN_TOKEN")
        if expected_token:
            auth = request.headers.get("authorization", "")
            header_token = request.headers.get("x-sidequests-token", "")
            bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if expected_token not in {header_token, bearer}:
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32001, "message": "Unauthorized"}},
                    status_code=401,
                )

        principal = getattr(request.state, "principal", None)
        if principal is None:
            # Backstop for tests/alternate wiring that bypass middleware.
            transport_ctx = TransportContext(transport="http", headers=dict(request.headers))
            try:
                principal = await _principal_resolver.resolve(transport_ctx)
            except Exception as e:
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32001, "message": f"Unauthorized: {e}"}},
                    status_code=401,
                )

        # Legacy SSE transport — if connection_id is present, use old flow
        connection_id = request.query_params.get("connection_id")
        if connection_id:
            return await _mcp_post_legacy_sse(request, connection_id, principal)

        # Streamable HTTP transport — return result directly
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )

        result = await _dispatch_mcp(body, db, _config, principal, _router)

        # Notifications return no result
        if result is None:
            return Response(status_code=202)

        return JSONResponse(result)

    @app.get("/mcp")
    async def mcp_get(request: Request):
        """Streamable HTTP GET placeholder for server-initiated streams."""
        accept = request.headers.get("accept", "")
        if "text/event-stream" not in accept:
            return JSONResponse(
                {"error": "Accept header must include text/event-stream"},
                status_code=406,
            )
        return Response(status_code=405)

    # ------------------------------------------------------------------
    # REST API endpoints (B262)
    # ------------------------------------------------------------------
    from campy.brain.brainstem.rest_api import create_router
    
    rest_routes = create_router(db=db, config=_config)
    for route in rest_routes:
        app.routes.append(route)

    if not _dashboard_enabled:
        allowed_paths = {"/health", "/mcp", "/sse"}
        app.router.routes = [
            route for route in app.router.routes
            if getattr(route, "path", None) in allowed_paths
        ]

    return app


def _inject_sse_context(tool_args: dict) -> dict:
    """Inject context for SSE clients (no git repo, no workspace)."""
    enriched = dict(tool_args)
    enriched.setdefault("repo_root", "")
    enriched.setdefault("git_branch", "")
    enriched.setdefault("workspace_path", str(Path.home()))
    enriched.setdefault("token_limit", 128000)  # GPT-4o default
    return enriched


async def _dispatch_mcp(request: dict, _db, _cfg: dict, principal: Principal,
                         _router=None) -> dict | None:
    """
    Dispatch a JSON-RPC MCP request to tool handlers.

    B325: `tools/call` now routes through `campy.brain_daemon.route_tool_call`
    — the exact same chokepoint the Unix-socket IPC dispatcher
    (`brain_daemon.py::_dispatch`) uses — instead of calling
    `TOOL_HANDLERS[name]` directly. That was the "IPC Dispatch Divergence"
    documented in docs/transport-audit.md: this HTTP path used to skip
    B315's forbidden-key guard and principal threading entirely. `principal`
    is resolved by the caller (`mcp_post`, from HTTP headers, before this
    function ever sees the parsed body) and threaded through exactly as the
    socket transport does.

    B316: when `_router` is given, `tools/call` resolves its database from
    it (keyed on `principal.workspace_id`) instead of the fixed `_db` —
    the same workspace routing `BrainDaemon._dispatch` does. `_router=None`
    (every call site before B316, and every test that doesn't pass one)
    keeps using `_db` unchanged.
    """
    from campy.brain.thalamus.tool_schemas import TOOLS as _TOOLS
    from campy.brain_daemon import ForbiddenParamError, UnknownMethodError, route_tool_call

    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hippocampy-brain", "version": WEB_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": _TOOLS})

    if method == "tools/call":
        from campy.brain.brainstem.activity_log import emit_activity, compact_details
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        tool_args = _inject_sse_context(tool_args)

        # B316: resolve this call's database from the router, keyed on the
        # transport-derived principal.workspace_id — mirrors
        # BrainDaemon._dispatch exactly. Falls back to the fixed `_db`
        # when no router was given (pre-B316 behavior, every existing test).
        if _router is not None:
            try:
                db = await _router.get(principal.workspace_id)
            except ValueError as e:
                return err(-32602, f"Invalid workspace: {e}")
        else:
            db = _db

        try:
            result = await route_tool_call(tool_name, tool_args, db, _cfg, principal)
            emit_activity(
                "tool", config=_cfg, method=tool_name, status="ok",
                details=compact_details(tool_name, tool_args),
            )
            return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
        except UnknownMethodError:
            return err(-32601, f"Unknown tool: {tool_name}")
        except ForbiddenParamError as e:
            emit_activity(
                "tool", config=_cfg, method=tool_name, status="error",
                details={**compact_details(tool_name, tool_args), "error": str(e)[:160]},
            )
            return err(-32602, str(e))
        except Exception as e:
            _logger.exception("MCP tool dispatch error for %s", tool_name)
            emit_activity(
                "tool", config=_cfg, method=tool_name, status="error",
                details={**compact_details(tool_name, tool_args), "error": str(e)[:160]},
            )
            return err(-32000, str(e))
        finally:
            if _router is not None:
                _router.release(principal.workspace_id)

    return err(-32601, f"Unknown method: {method}")
