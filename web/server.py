"""
web/server.py — Memory Control Panel (M7)

FastAPI server bound strictly to 127.0.0.1 — never 0.0.0.0.
No authentication needed (local-only access by design).

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
from datetime import datetime, timezone
from pathlib import Path

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from web.routes.metrics import register_token_metrics_routes

_logger = logging.getLogger(__name__)

# Registry of active SSE connections: connection_id → asyncio.Queue
_sse_connections: dict[str, asyncio.Queue] = {}

STATIC_DIR = Path(__file__).parent / "static"
WEB_VERSION = "0.1.0"

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

def create_app(db, config: dict | None = None) -> FastAPI:
    """
    Create the FastAPI app with a db reference and optional config dict.
    Called by BrainDaemon.start() with the live KuzuClient.
    For tests, pass a mock db that implements .execute() and .execute_write().

    config is used by the SSE /mcp endpoint to pass to tool handlers.
    """
    _config = config or {}
    app = FastAPI(
        title="SideQuest Memory Control Panel",
        version=WEB_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    # Serve static assets (CSS, JS, icons)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ------------------------------------------------------------------
    # Main UI & Deep-links
    # ------------------------------------------------------------------

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
                r = db.execute(f"MATCH (n:{table}) WHERE n.{pk} = $id RETURN n", {"id": node_id})
                if r.has_next():
                    node_data = r.get_next()[0]
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
            r = db.execute(
                f"MATCH (n:{node_table})-[r]-(m) WHERE n.{pk_col} = $id "
                "RETURN m, label(m), label(r) LIMIT 20",
                {"id": node_id}
            )
            while r.has_next():
                row = r.get_next()
                neighbor_node = row[0]
                neighbor_label = row[1]
                rel_label = row[2]
                
                # Get neighbor's ID (might be different PK columns)
                nid = "unknown"
                for _, pk in ARTIFACT_TABLES + [("Message", "message_id"), ("Document", "document_id"), ("MainQuest", "quest_id"), ("SideQuest", "quest_id"), ("Lesson", "lesson_id")]:
                    if pk in neighbor_node:
                        nid = neighbor_node[pk]
                        break

                result["neighbors"].append({
                    "id": nid,
                    "type": neighbor_label,
                    "relation": rel_label,
                    "text": neighbor_node.get("text_raw", neighbor_node.get("name", ""))[:100]
                })
        except Exception:
            pass

        return result

    @app.get("/api/stats")
    def get_stats():
        """Node counts per artifact table (archived=false only)."""
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
                r = db.execute(
                    f"MATCH (n:{table}) WHERE n.archived = false RETURN count(n)"
                    if table not in ("Document", "MergeEvent")
                    else f"MATCH (n:{table}) RETURN count(n)"
                )
                counts[key] = r.get_next()[0] if r.has_next() else 0
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
                nodes.append({"id": nid, "label": label[:60],
                               "type": node_type, **extra})

        # Concept nodes (top 30 by strength)
        try:
            r = db.execute(
                "MATCH (c:Concept) WHERE c.archived = false "
                "RETURN c.concept_id, c.text_raw, c.gist_class, "
                "       c.confidence, c.pathway_strength, c.confidence_low "
                "ORDER BY c.pathway_strength DESC LIMIT 30"
            )
            while r.has_next():
                row = r.get_next()
                _add_node(row[0], row[1], "Concept",
                          gist_class=row[2], confidence=row[3],
                          pathway_strength=row[4], soft_lock=bool(row[5]))
        except Exception:
            pass

        # Decision nodes
        try:
            r = db.execute(
                "MATCH (d:Decision) WHERE d.archived = false "
                "RETURN d.decision_id, d.text_raw, d.confidence, "
                "       d.pathway_strength, d.confidence_low "
                "ORDER BY d.pathway_strength DESC LIMIT 20"
            )
            while r.has_next():
                row = r.get_next()
                _add_node(row[0], row[1], "Decision",
                          confidence=row[2], pathway_strength=row[3],
                          soft_lock=bool(row[4]))
        except Exception:
            pass

        # Constraint nodes
        try:
            r = db.execute(
                "MATCH (c:Constraint) WHERE c.archived = false "
                "RETURN c.constraint_id, c.text_raw, c.confidence, "
                "       c.pathway_strength, c.confidence_low "
                "ORDER BY c.pathway_strength DESC LIMIT 20"
            )
            while r.has_next():
                row = r.get_next()
                _add_node(row[0], row[1], "Constraint",
                          confidence=row[2], pathway_strength=row[3],
                          soft_lock=bool(row[4]))
        except Exception:
            pass

        # MainQuest nodes
        try:
            r = db.execute(
                "MATCH (q:MainQuest) WHERE q.archived = false "
                "RETURN q.quest_id, q.name, q.status LIMIT 10"
            )
            while r.has_next():
                row = r.get_next()
                _add_node(row[0], row[1], "MainQuest", status=row[2])
        except Exception:
            pass

        # SideQuest nodes
        try:
            r = db.execute(
                "MATCH (q:SideQuest) WHERE q.archived = false "
                "RETURN q.quest_id, q.name, q.status LIMIT 10"
            )
            while r.has_next():
                row = r.get_next()
                _add_node(row[0], row[1], "SideQuest", status=row[2])
        except Exception:
            pass

        # --- Edges ---

        # CO_OCCURS_WITH (Concept ↔ Concept)
        try:
            r = db.execute(
                "MATCH (a:Concept)-[r:CO_OCCURS_WITH]->(b:Concept) "
                "WHERE a.archived = false AND b.archived = false "
                "RETURN a.concept_id, b.concept_id, r.strength, r.count "
                "ORDER BY r.strength DESC LIMIT 60"
            )
            while r.has_next():
                row = r.get_next()
                src, tgt = row[0], row[1]
                if src in seen_ids and tgt in seen_ids:
                    edges.append({"source": src, "target": tgt,
                                  "type": "CO_OCCURS_WITH",
                                  "strength": row[2], "count": row[3]})
        except Exception:
            pass

        # DEPRECATED_BY (Concept → Concept)
        try:
            r = db.execute(
                "MATCH (old:Concept)-[:DEPRECATED_BY]->(new:Concept) "
                "RETURN old.concept_id, new.concept_id LIMIT 30"
            )
            while r.has_next():
                row = r.get_next()
                src, tgt = row[0], row[1]
                if src in seen_ids and tgt in seen_ids:
                    edges.append({"source": src, "target": tgt,
                                  "type": "DEPRECATED_BY"})
        except Exception:
            pass

        # BELONGS_TO (SideQuest → MainQuest)
        try:
            r = db.execute(
                "MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
                "RETURN sq.quest_id, mq.quest_id"
            )
            while r.has_next():
                row = r.get_next()
                edges.append({"source": row[0], "target": row[1],
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
                r = db.execute(
                    f"MATCH (n:{table}) "
                    f"WHERE n.confidence_low = true AND n.archived = false "
                    f"RETURN n.{id_col}, n.text_raw, n.confidence, n.created_at "
                    f"ORDER BY n.created_at DESC LIMIT 50"
                )
                while r.has_next():
                    row = r.get_next()
                    items.append({
                        "node_id":    row[0],
                        "node_type":  table,
                        "text_raw":   row[1],
                        "confidence": row[2],
                        "created_at": str(row[3]),
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
                # W1 fix: run blocking db.execute() in threadpool
                r = await asyncio.to_thread(
                    db.execute,
                    f"MATCH (n:{table} {{{id_col}: $nid}}) RETURN n.{id_col}",
                    {"nid": node_id}
                )
                if r.has_next():
                    await db.execute_write(
                        f"MATCH (n:{table} {{{id_col}: $nid}}) "
                        "SET n.confidence_low = false, n.confidence = 0.95",
                        {"nid": node_id}
                    )
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
                # W1 fix: run blocking db.execute() in threadpool
                r = await asyncio.to_thread(
                    db.execute,
                    f"MATCH (n:{table} {{{id_col}: $nid}}) RETURN n.{id_col}",
                    {"nid": node_id}
                )
                if r.has_next():
                    await db.execute_write(
                        f"MATCH (n:{table} {{{id_col}: $nid}}) "
                        "SET n.archived = true",
                        {"nid": node_id}
                    )
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
            r = db.execute(
                "MATCH (me:MergeEvent) "
                "RETURN me.merge_event_id, me.pre_pathway_strength, "
                "       me.delta_pathway_strength, me.metadata_patch, me.created_at "
                "ORDER BY me.created_at DESC LIMIT 50"
            )
            while r.has_next():
                row = r.get_next()
                meta = row[3] or ""
                already_rolled_back = "rolled_back=true" in meta
                merge_type = ("contradiction" if "contradiction" in meta
                              else "additive")
                events.append({
                    "merge_event_id":        row[0],
                    "pre_pathway_strength":  row[1],
                    "delta_pathway_strength": row[2],
                    "merge_type":            merge_type,
                    "metadata_patch":        meta,
                    "already_rolled_back":   already_rolled_back,
                    "created_at":            str(row[4]),
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
        # Fetch MergeEvent — W1 fix: use to_thread for blocking read
        try:
            r = await asyncio.to_thread(
                db.execute,
                "MATCH (me:MergeEvent {merge_event_id: $meid}) "
                "RETURN me.metadata_patch, me.pre_pathway_strength",
                {"meid": merge_event_id}
            )
            if not r.has_next():
                raise HTTPException(
                    status_code=404,
                    detail=f"MergeEvent '{merge_event_id}' not found"
                )
            row = r.get_next()
            metadata     = row[0] or ""
            pre_strength = float(row[1] or 0.5)
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
                    await db.execute_write(
                        "MATCH (c:Concept {concept_id: $id}) "
                        "SET c.archived = false, c.pathway_strength = $strength",
                        {"id": old_id, "strength": pre_strength}
                    )
                    await db.execute_write(
                        "MATCH (c:Concept {concept_id: $id}) "
                        "SET c.archived = true",
                        {"id": new_id}
                    )
                    # W2 fix: remove DEPRECATED_BY edge to restore clean graph state
                    await db.execute_write(
                        "MATCH (old:Concept {concept_id: $old_id})"
                        "-[d:DEPRECATED_BY]->"
                        "(new:Concept {concept_id: $new_id}) "
                        "DELETE d",
                        {"old_id": old_id, "new_id": new_id}
                    )
                    result.update({"old_concept_restored": old_id,
                                   "new_concept_archived": new_id})
                except Exception as e:
                    raise HTTPException(status_code=500,
                                        detail=f"Rollback failed: {e}")

        # Mark as rolled back
        try:
            await db.execute_write(
                "MATCH (me:MergeEvent {merge_event_id: $meid}) "
                "SET me.metadata_patch = $meta",
                {"meid": merge_event_id,
                 "meta": metadata + ";rolled_back=true"}
            )
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Constraint Ledger export
    # ------------------------------------------------------------------

    def _collect_ledger() -> list[dict]:
        """Fetch all active Constraints + GlobalConstraints sorted by strength."""
        rows = []
        for table, id_col in [
            ("Constraint",       "constraint_id"),
            ("GlobalConstraint", "global_constraint_id"),
        ]:
            try:
                r = db.execute(
                    f"MATCH (c:{table}) WHERE c.archived = false "
                    f"RETURN c.{id_col}, c.text_raw, c.confidence, "
                    f"       c.confidence_low, c.pathway_strength, c.created_at "
                    f"ORDER BY c.pathway_strength DESC"
                )
                while r.has_next():
                    row = r.get_next()
                    rows.append({
                        "constraint_id":    row[0],
                        "table":            table,
                        "text_raw":         row[1],
                        "confidence":       row[2],
                        "confidence_low":   bool(row[3]),
                        "pathway_strength": row[4],
                        "created_at":       str(row[5]),
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
            r = db.execute(
                "MATCH (q:MainQuest) WHERE q.archived = false "
                "RETURN q.quest_id, q.name, q.status, q.purpose, q.created_at "
                "ORDER BY q.created_at DESC"
            )
            while r.has_next():
                row = r.get_next()
                quest = {
                    "quest_id":   row[0],
                    "name":       row[1],
                    "status":     row[2],
                    "purpose":    row[3],
                    "created_at": str(row[4]),
                    "type":       "MainQuest",
                    "side_quests": [],
                }
                quests.append(quest)
                quest_map[row[0]] = quest
        except Exception:
            pass

        try:
            r = db.execute(
                "MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
                "WHERE sq.archived = false "
                "RETURN sq.quest_id, sq.name, sq.status, sq.purpose, "
                "       sq.created_at, mq.quest_id"
            )
            while r.has_next():
                row = r.get_next()
                sq = {
                    "quest_id":   row[0],
                    "name":       row[1],
                    "status":     row[2],
                    "purpose":    row[3],
                    "created_at": str(row[4]),
                    "type":       "SideQuest",
                }
                parent_id = row[5]
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
            r = db.execute(
                "MATCH (d:Decision) WHERE d.archived = false "
                "RETURN d.decision_id, d.text_raw, d.confidence, "
                "       d.pathway_strength, d.confidence_low, d.created_at "
                "ORDER BY d.pathway_strength DESC LIMIT 10"
            )
            while r.has_next():
                row = r.get_next()
                result["decisions"].append({
                    "id": row[0],
                    "text": row[1],
                    "confidence": round(float(row[2] or 0), 3),
                    "strength": round(float(row[3] or 0), 3),
                    "soft_lock": bool(row[4]),
                    "created_at": str(row[5]),
                })
        except Exception:
            pass

        # Top concepts (by pathway_strength, for tag cloud)
        try:
            r = db.execute(
                "MATCH (c:Concept) WHERE c.archived = false "
                "RETURN c.concept_id, c.text_raw, c.gist_class, "
                "       c.pathway_strength, c.confidence_low "
                "ORDER BY c.pathway_strength DESC LIMIT 25"
            )
            while r.has_next():
                row = r.get_next()
                result["concepts"].append({
                    "id": row[0],
                    "text": row[1],
                    "gist_class": row[2],
                    "strength": round(float(row[3] or 0), 3),
                    "soft_lock": bool(row[4]),
                })
        except Exception:
            pass

        # Active constraints
        try:
            r = db.execute(
                "MATCH (c:Constraint) WHERE c.archived = false "
                "RETURN c.constraint_id, c.text_raw, c.confidence, "
                "       c.pathway_strength, c.confidence_low "
                "ORDER BY c.pathway_strength DESC LIMIT 10"
            )
            while r.has_next():
                row = r.get_next()
                result["constraints"].append({
                    "id": row[0],
                    "text": row[1],
                    "confidence": round(float(row[2] or 0), 3),
                    "strength": round(float(row[3] or 0), 3),
                    "soft_lock": bool(row[4]),
                })
        except Exception:
            pass

        # Open loops count (confidence_low nodes not yet confirmed)
        try:
            total = 0
            for table, _ in [("Concept", "concept_id"), ("Decision", "decision_id"),
                              ("Constraint", "constraint_id")]:
                r = db.execute(
                    f"MATCH (n:{table}) WHERE n.confidence_low = true "
                    f"AND n.archived = false RETURN count(n)"
                )
                if r.has_next():
                    total += r.get_next()[0] or 0
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
                r = db.execute(
                    f"MATCH (n:{table}) WHERE n.archived = false RETURN count(n)"
                )
                result["stats"][key] = r.get_next()[0] if r.has_next() else 0
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # B3 — MCP-over-SSE transport (ChatGPT Desktop / any SSE-capable client)
    #
    # Usage:
    #   1. Client connects to GET /sse → receives "event: endpoint" with POST URL
    #   2. Client POSTs JSON-RPC requests to /mcp?connection_id=<id>
    #   3. Server dispatches to tool handlers, streams response back via SSE
    #
    # Security: endpoint bound to 127.0.0.1 by the server runner — same as all
    # other endpoints. No token auth needed (local-only access by design).
    # ------------------------------------------------------------------

    @app.get("/sse")
    async def mcp_sse(request: Request):
        """
        Open an MCP SSE stream. First event tells the client where to POST requests.
        Sends keepalive comments every 30 s to prevent proxy/firewall timeout.
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
                        data = await asyncio.wait_for(queue.get(), timeout=30.0)
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
            },
        )

    async def _mcp_post_legacy_sse(request: Request, connection_id: str):
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

        response = await _dispatch_mcp(body, db, _config)
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
        # Legacy SSE transport — if connection_id is present, use old flow
        connection_id = request.query_params.get("connection_id")
        if connection_id:
            return await _mcp_post_legacy_sse(request, connection_id)
        
        # Streamable HTTP transport — return result directly
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )
        
        result = await _dispatch_mcp(body, db, _config)
        
        # Notifications return no result
        if result is None:
            return Response(status_code=202)
        
        return JSONResponse(result)

    return app


def _inject_sse_context(tool_args: dict) -> dict:
    """Inject context for SSE clients (no git repo, no workspace)."""
    enriched = dict(tool_args)
    enriched.setdefault("repo_root", "")
    enriched.setdefault("git_branch", "")
    enriched.setdefault("workspace_path", str(Path.home()))
    enriched.setdefault("token_limit", 128000)  # GPT-4o default
    return enriched


async def _dispatch_mcp(request: dict, _db, _cfg: dict) -> dict | None:
    """
    Dispatch a JSON-RPC MCP request to tool handlers — same logic as
    the brain_daemon IPC dispatcher but runs in-process (no socket hop).
    Handles: initialize, notifications/initialized, tools/list, tools/call.
    """
    from mcp_engine.tools import TOOL_HANDLERS
    from mcp_engine.tool_schemas import TOOLS as _TOOLS

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
            "serverInfo": {"name": "sidequests-brain-sse", "version": WEB_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": _TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        tool_args = _inject_sse_context(tool_args)
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return err(-32601, f"Unknown tool: {tool_name}")
        try:
            result = await handler(tool_args, _db, _cfg)
            return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
        except Exception as e:
            _logger.exception("SSE tool dispatch error for %s", tool_name)
            return err(-32000, str(e))

    return err(-32601, f"Unknown method: {method}")
