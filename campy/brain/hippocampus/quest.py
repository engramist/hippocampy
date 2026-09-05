from __future__ import annotations

"""
mcp_engine/quest.py — Quest Lifecycle

MainQuest auto-creation: deterministic hash of (repo_root_path + git_branch).
Same repo + branch always maps to the same quest_id across all adapters.

SideQuest: manually declared via branch_quest tool, linked to parent MainQuest
via BELONGS_TO edge.

Quest context retrieval: structured summary of recent decisions/constraints
for injection into the assistant system prompt (Graph-Native RAG read flow).
"""

import hashlib
import uuid
from datetime import datetime, timezone

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)
import uuid
from datetime import datetime, timezone

from campy.brain.hippocampus.graph import embeddings as emb


def compute_quest_id(repo_root: str, git_branch: str) -> str:
    """
    LEGACY: Deterministic quest_id from repo root path only.
    Kept for backward compatibility with existing git-anchored quests.
    New quests use UUID via hippocampus.create_new_quest().
    """
    raw = repo_root.strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def get_or_create_main_quest(db, repo_root: str, git_branch: str,
                                    embedding_model: str, now: str) -> str:
    """
    Ensure a MainQuest node exists by its deterministic quest_id.
    ON CREATE: embed the quest name, set all initial fields.
    ON MATCH:  update last_active_at to track inactivity for auto-complete.
    Returns the quest_id string.
    """
    quest_id = compute_quest_id(repo_root, git_branch)
    name     = f"{_basename(repo_root)} [{git_branch}]"

    # Check if MainQuest already exists
    exists_rows = await _gateway(db).run("quests.get_main_quest_by_id", qid=quest_id)
    exists = bool(exists_rows)

    if exists:
        await _gateway(db).run("quests.touch_main_quest", quest_id=quest_id, now=now)
    else:
        vector = emb.embed(name, model_name=embedding_model)
        await _gateway(db).run(
            "quests.create_main_quest",
            quest_id=quest_id,
            name=name,
            status="active",
            purpose=f"Project work on {name}",
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            created_at=now,
            last_active_at=now,
            git_repo_root=repo_root,
            purpose_embedding=vector,
            routing_method="git",
        )

    return quest_id


async def get_or_create_session(db, session_id: str, quest_id: str, now: str) -> None:
    """
    Ensure a Session node exists and link it to the active quest via WORKING_ON.
    Called on every notify_turn to ensure the session is tracked.
    """
    try:
        await _gateway(db).run(
            "quests.merge_session_git_locked",
            sid=session_id,
            now=now,
        )
        await _gateway(db).run(
            "quests.link_session_quest",
            sid=session_id,
            qid=quest_id,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "get_or_create_session failed for session_id=%s quest_id=%s",
            session_id, quest_id,
        )


async def create_side_quest(db, name: str, purpose: str, parent_quest_id: str,
                             embedding_model: str, now: str) -> str:
    """
    Create a SideQuest node and link it to its parent MainQuest via BELONGS_TO.
    Returns the new side quest_id.
    """
    side_quest_id = str(uuid.uuid4())[:32]
    vector = emb.embed(f"{name}: {purpose}", model_name=embedding_model)

    try:
        await _gateway(db).run(
            "quests.create_side_quest",
            quest_id=side_quest_id,
            name=name,
            purpose=purpose,
            text_raw=f"{name}: {purpose}",
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            created_at=now,
        )
        await _gateway(db).run(
            "quests.link_side_quest",
            sqid=side_quest_id,
            mqid=parent_quest_id,
        )
    except Exception:
        pass

    return side_quest_id


def get_quest_context(db, quest_id: str, limit: int = 5) -> dict:
    """
    Retrieve a structured quest context snapshot for system prompt injection.
    Returns:
        {quest_id, quest_name, status, recent_decisions, recent_constraints,
         open_loops, side_quests}

    Uses direct Cypher traversal (not vector search) — returns most recent
    artifacts linked to sessions that worked on this quest.
    """
    ctx = {
        "quest_id":           quest_id,
        "quest_name":         "",
        "status":             "unknown",
        "recent_decisions":   [],
        "recent_constraints": [],
        "open_loops":         [],
        "side_quests":        [],
    }

    try:
        # Quest name + status
        rows = _gateway(db).run_sync("quests.get_quest_name_and_status", qid=quest_id)
        if rows:
            row = rows[0]
            ctx["quest_name"] = (row.get("q.name") if isinstance(row, dict) else row[0]) or ""
            ctx["status"]     = (row.get("q.status") if isinstance(row, dict) else row[1]) or "active"

        # Recent Decisions via quest sessions
        ctx["recent_decisions"] = _query_artifacts(
            db, quest_id, "Decision", "decision_id", limit
        )

        # Recent Constraints via quest sessions
        ctx["recent_constraints"] = _query_artifacts(
            db, quest_id, "Constraint", "constraint_id", limit
        )

        # Open loops — confidence_low concepts not yet promoted
        rows = _gateway(db).run_sync("quests.get_open_loop_concepts", limit=limit)
        for row in rows:
            cid = row.get("c.concept_id") if isinstance(row, dict) else row[0]
            txt = row.get("c.text_raw") if isinstance(row, dict) else row[1]
            gist = row.get("c.gist_class") if isinstance(row, dict) else row[2]
            conf = row.get("c.confidence") if isinstance(row, dict) else row[3]
            if not _passes_signal_floor(txt):
                continue
            ctx["open_loops"].append({
                "concept_id": cid,
                "text_raw":   txt,
                "gist_class": gist,
                "confidence": conf,
            })

        # Active SideQuests belonging to this MainQuest
        rows = _gateway(db).run_sync("quests.get_active_side_quests", qid=quest_id, limit=limit)
        for row in rows:
            sqid = row.get("sq.quest_id") if isinstance(row, dict) else row[0]
            name = row.get("sq.name") if isinstance(row, dict) else row[1]
            purpose = row.get("sq.purpose") if isinstance(row, dict) else row[2]
            ctx["side_quests"].append({
                "quest_id": sqid,
                "name":     name,
                "purpose":  purpose,
            })

    except Exception:
        pass

    return ctx


def format_context_for_prompt(ctx: dict) -> str:
    """
    Render the quest context as a compact system prompt block.
    Injected by adapters before the assistant responds.
    """
    if not ctx.get("quest_name"):
        return ""

    lines = [
        f"[SideQuest Brain | Quest: {ctx['quest_name']} | {ctx['status'].upper()}]",
    ]

    if ctx["recent_decisions"]:
        lines.append("Decisions:")
        for d in ctx["recent_decisions"]:
            conf = "✓" if not d.get("confidence_low") else "?"
            lines.append(f"  {conf} {d['text_raw']}")

    if ctx["recent_constraints"]:
        lines.append("Constraints:")
        for c in ctx["recent_constraints"]:
            conf = "✓" if not c.get("confidence_low") else "?"
            lines.append(f"  {conf} {c['text_raw']}")

    if ctx["open_loops"]:
        lines.append(f"Open loops (unconfirmed): {len(ctx['open_loops'])}")

    if ctx["side_quests"]:
        sq_names = ", ".join(sq["name"] for sq in ctx["side_quests"])
        lines.append(f"Active side quests: {sq_names}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _passes_signal_floor(text_raw: str | None) -> bool:
    """
    B300: a single token under 6 chars (e.g. "four", "maoc") carries no
    standalone meaning and pollutes quest_context/current_truth. Nodes still
    exist in the graph — this only keeps them out of this presentation layer.
    """
    if not text_raw:
        return True
    stripped = text_raw.strip()
    if ' ' not in stripped and len(stripped) < 6:
        return False
    return True


def _query_artifacts(db, quest_id: str, label: str, pk: str,
                      limit: int) -> list[dict]:
    """
    Fetch recent artifacts of a given type linked to sessions working on this quest.
    Falls back to recency-ordered global query if quest has no sessions yet.
    """
    results = []
    try:
        qname = f"quests.get_quest_{label.lower()}s"
        rows = _gateway(db).run_sync(qname, qid=quest_id, limit=limit)
        for row in rows:
            if isinstance(row, dict):
                vals = list(row.values())
                nid, txt, clow, pstr = vals[0], vals[1], vals[2], vals[3]
            else:
                nid, txt, clow, pstr = row[0], row[1], row[2], row[3]
            if not _passes_signal_floor(txt):
                continue
            results.append({
                "node_id":        nid,
                "text_raw":       txt,
                "confidence_low": clow,
                "pathway_strength": pstr,
            })
    except Exception:
        pass

    return results


async def maybe_synthesize_purpose(db, message_id: str, artifact_text: str,
                                    llm_client, embedding_model: str, now: str) -> bool:
    """
    M5: Synthesize Quest/Session purpose after the first confirmed (>90%) artifact.

    Checks if Session.purpose is already set. If empty, gathers recent messages
    from the session, calls LLM for a 1-2 sentence purpose, and writes it to
    both Session.purpose and MainQuest.purpose (both confidence_low=true — inferred,
    not user-confirmed).

    Returns True if synthesis was performed, False if skipped (already set or
    no session found).
    """
    if llm_client is None:
        return False

    # Look up the session this message was sent in
    session_id = quest_id = quest_name = ""
    session_purpose = None
    try:
        rows = _gateway(db).run_sync("quests.get_session_by_message", mid=message_id)
        if rows:
            row = rows[0]
            session_id     = (row.get("s.session_id") if isinstance(row, dict) else row[0]) or ""
            session_purpose = row.get("s.purpose") if isinstance(row, dict) else row[1]
    except Exception:
        return False

    if not session_id:
        return False  # message not linked to a session

    # Skip if purpose already synthesized for this session
    if session_purpose:
        return False

    # Look up the MainQuest this session is working on
    try:
        rows = _gateway(db).run_sync("quests.get_quest_by_session", sid=session_id)
        if rows:
            row = rows[0]
            quest_id   = (row.get("q.quest_id") if isinstance(row, dict) else row[0]) or ""
            quest_name = (row.get("q.name") if isinstance(row, dict) else row[1]) or ""
    except Exception:
        pass

    # Gather recent messages from this session for context (up to 8)
    context_messages = []
    try:
        rows = _gateway(db).run_sync("quests.get_session_messages", sid=session_id, limit=8)
        for row in rows:
            txt = row.get("m.text_raw") if isinstance(row, dict) else row[0] or ""
            role = row.get("m.role") if isinstance(row, dict) else row[1] or "user"
            context_messages.append(f"{role}: {txt}")
    except Exception:
        pass

    prompt = (
        f"You are summarizing the purpose of a software development session.\n\n"
        f"Quest name: {quest_name or 'Unknown'}\n"
        f"First confirmed artifact: {artifact_text}\n\n"
        f"Recent messages:\n" + "\n".join(context_messages[-5:]) + "\n\n"
        f"Write a 1-2 sentence purpose statement describing what this session/quest "
        f"is trying to accomplish. Be specific and concrete. "
        f"Respond with the purpose statement only, no preamble."
    )

    purpose = ""
    try:
        # S1 fix: use achat() to avoid blocking the event loop
        if hasattr(llm_client, 'achat'):
            purpose = (await llm_client.achat([{"role": "user", "content": prompt}])).strip()
        else:
            purpose = llm_client.chat([{"role": "user", "content": prompt}]).strip()
        if not purpose:
            return False
    except Exception:
        return False

    # Write purpose to Session (confidence_low=true — inferred)
    try:
        await _gateway(db).run("quests.set_session_purpose", sid=session_id, purpose=purpose)
    except Exception:
        pass

    # Write purpose to MainQuest if it doesn't already have one
    if quest_id:
        try:
            await _gateway(db).run(
                "quests.set_main_quest_purpose",
                qid=quest_id,
                default=f"Project work on {quest_name}",
                purpose=purpose,
            )
        except Exception:
            pass

    return True


def _basename(path: str) -> str:
    """Return the last path component (repo name)."""
    return path.rstrip("/\\").split("/")[-1].split("\\")[-1] or path
