"""
mcp_engine/quest.py — Quest Lifecycle

MainQuest auto-creation: deterministic hash of (repo_root_path + git_branch).
Same repo + branch always maps to the same quest_id across all adapters.

SideQuest: manually declared via branch_quest tool, linked to parent MainQuest
via BELONGS_TO edge.

Quest context retrieval: structured summary of recent decisions/constraints
for injection into the assistant system prompt (Graph-Native RAG read flow).
"""

from __future__ import annotations
import hashlib
import uuid
from datetime import datetime, timezone

from mcp_engine.graph import embeddings as emb


def compute_quest_id(repo_root: str, git_branch: str) -> str:
    """
    Deterministic quest_id from repo root path + branch name.
    All adapters connected to the same repo+branch share the same MainQuest.
    Returns a 32-char hex string used as the quest PRIMARY KEY.
    """
    raw = f"{repo_root.strip()}:{git_branch.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def get_or_create_main_quest(db, repo_root: str, git_branch: str,
                                    embedding_model: str, now: str) -> str:
    """
    MERGE a MainQuest node by its deterministic quest_id.
    ON CREATE: embed the quest name, set all initial fields.
    ON MATCH:  update last_active_at to track inactivity for auto-complete.
    Returns the quest_id string.
    """
    quest_id = compute_quest_id(repo_root, git_branch)
    name     = f"{_basename(repo_root)} [{git_branch}]"

    # Always compute embedding — needed by ON CREATE branch
    vector = emb.embed(name, model_name=embedding_model)

    try:
        await db.execute_write(
            """
            MERGE (q:MainQuest {quest_id: $quest_id})
            ON CREATE SET q.name             = $name,
                          q.status           = 'active',
                          q.completed_at     = null,
                          q.purpose          = $purpose,
                          q.text_raw         = $name,
                          q.embedding        = $embedding,
                          q.embedding_model  = $embedding_model,
                          q.embedding_dim    = $embedding_dim,
                          q.confidence       = 1.0,
                          q.confidence_low   = false,
                          q.pathway_strength = 1.0,
                          q.archived         = false,
                          q.created_at       = timestamp($now),
                          q.last_active_at   = timestamp($now)
            ON MATCH SET  q.last_active_at   = timestamp($now)
            """,
            {
                "quest_id":        quest_id,
                "name":            name,
                "purpose":         f"Project work on {name}",
                "embedding":       vector,
                "embedding_model": embedding_model,
                "embedding_dim":   len(vector),
                "now":             now,
            }
        )
    except Exception:
        pass

    return quest_id


async def get_or_create_session(db, session_id: str, quest_id: str, now: str) -> None:
    """
    MERGE a Session node and link it to the active quest via WORKING_ON.
    Called on every notify_turn to ensure the session is tracked.
    """
    try:
        # MERGE session
        await db.execute_write(
            """
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at     = timestamp($now),
                          s.last_active_at = timestamp($now),
                          s.onboarded      = false,
                          s.purpose        = ''
            ON MATCH SET  s.last_active_at = timestamp($now)
            """,
            {"sid": session_id, "now": now}
        )

        # Link session → quest
        await db.execute_write(
            """
            MATCH (s:Session {session_id: $sid}),
                  (q:MainQuest {quest_id: $qid})
            MERGE (s)-[:WORKING_ON]->(q)
            """,
            {"sid": session_id, "qid": quest_id}
        )
    except Exception:
        pass


async def create_side_quest(db, name: str, purpose: str, parent_quest_id: str,
                             embedding_model: str, now: str) -> str:
    """
    Create a SideQuest node and link it to its parent MainQuest via BELONGS_TO.
    Returns the new side quest_id.
    """
    side_quest_id = str(uuid.uuid4())[:32]
    vector = emb.embed(f"{name}: {purpose}", model_name=embedding_model)

    try:
        await db.execute_write(
            """
            CREATE (sq:SideQuest {
                quest_id:         $quest_id,
                name:             $name,
                status:           'active',
                completed_at:     null,
                purpose:          $purpose,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                confidence:       1.0,
                confidence_low:   false,
                pathway_strength: 1.0,
                archived:         false,
                created_at:       timestamp($created_at)
            })
            """,
            {
                "quest_id":       side_quest_id,
                "name":           name,
                "purpose":        purpose,
                "text_raw":       f"{name}: {purpose}",
                "embedding":      vector,
                "embedding_model": embedding_model,
                "embedding_dim":  len(vector),
                "created_at":     now,
            }
        )

        await db.execute_write(
            """
            MATCH (sq:SideQuest {quest_id: $sqid}),
                  (mq:MainQuest {quest_id: $mqid})
            CREATE (sq)-[:BELONGS_TO]->(mq)
            """,
            {"sqid": side_quest_id, "mqid": parent_quest_id}
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
        r = db.execute(
            "MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.status",
            {"qid": quest_id}
        )
        if r.has_next():
            row = r.get_next()
            ctx["quest_name"] = row[0] or ""
            ctx["status"]     = row[1] or "active"

        # Recent Decisions via quest sessions
        ctx["recent_decisions"] = _query_artifacts(
            db, quest_id, "Decision", "decision_id", limit
        )

        # Recent Constraints via quest sessions
        ctx["recent_constraints"] = _query_artifacts(
            db, quest_id, "Constraint", "constraint_id", limit
        )

        # Open loops — confidence_low concepts not yet promoted
        r = db.execute(
            """
            MATCH (c:Concept {confidence_low: true, archived: false})
            WHERE c.created_at IS NOT NULL
            RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
            {"limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            ctx["open_loops"].append({
                "concept_id": row[0],
                "text_raw":   row[1],
                "gist_class": row[2],
                "confidence": row[3],
            })

        # Active SideQuests belonging to this MainQuest
        r = db.execute(
            """
            MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest {quest_id: $qid})
            WHERE sq.status = 'active'
            RETURN sq.quest_id, sq.name, sq.purpose
            LIMIT $limit
            """,
            {"qid": quest_id, "limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            ctx["side_quests"].append({
                "quest_id": row[0],
                "name":     row[1],
                "purpose":  row[2],
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

def _query_artifacts(db, quest_id: str, label: str, pk: str,
                      limit: int) -> list[dict]:
    """
    Fetch recent artifacts of a given type linked to sessions working on this quest.
    Falls back to recency-ordered global query if quest has no sessions yet.
    """
    results = []
    try:
        r = db.execute(
            f"""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {{quest_id: $qid}})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:{label} {{archived: false}})
            RETURN a.{pk}, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
            {"qid": quest_id, "limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            results.append({
                "node_id":        row[0],
                "text_raw":       row[1],
                "confidence_low": row[2],
                "pathway_strength": row[3],
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
        r = db.execute(
            "MATCH (m:Message {message_id: $mid})-[:SENT_IN]->(s:Session) "
            "RETURN s.session_id, s.purpose",
            {"mid": message_id},
        )
        if r.has_next():
            row = r.get_next()
            session_id     = row[0] or ""
            session_purpose = row[1]
    except Exception:
        return False

    if not session_id:
        return False  # message not linked to a session

    # Skip if purpose already synthesized for this session
    if session_purpose:
        return False

    # Look up the MainQuest this session is working on
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
            "RETURN q.quest_id, q.name",
            {"sid": session_id},
        )
        if r.has_next():
            row = r.get_next()
            quest_id   = row[0] or ""
            quest_name = row[1] or ""
    except Exception:
        pass

    # Gather recent messages from this session for context (up to 8)
    context_messages = []
    try:
        r = db.execute(
            "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
            "RETURN m.text_raw, m.role "
            "ORDER BY m.created_at ASC "
            "LIMIT 8",
            {"sid": session_id},
        )
        while r.has_next():
            row = r.get_next()
            context_messages.append(f"{row[1] or 'user'}: {row[0] or ''}")
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
        await db.execute_write(
            "MATCH (s:Session {session_id: $sid}) SET s.purpose = $purpose",
            {"sid": session_id, "purpose": purpose},
        )
    except Exception:
        pass

    # Write purpose to MainQuest if it doesn't already have one
    if quest_id:
        try:
            await db.execute_write(
                "MATCH (q:MainQuest {quest_id: $qid}) "
                "WHERE q.purpose = $default OR q.purpose IS NULL "
                "SET q.purpose = $purpose",
                {
                    "qid":     quest_id,
                    "default": f"Project work on {quest_name}",
                    "purpose": purpose,
                },
            )
        except Exception:
            pass

    return True


def _basename(path: str) -> str:
    """Return the last path component (repo name)."""
    return path.rstrip("/\\").split("/")[-1].split("\\")[-1] or path
