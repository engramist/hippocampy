"""
mcp_engine/analogical.py — Cross-Quest Analogical Reasoning (M8)

Named IP Claim: Cross-Quest Analogical Reasoning
  "Humans recognize patterns across past projects and reuse learned constraints.
   This module gives AI assistants the same cross-project institutional memory."

Broadened RAG that searches across ALL historical MainQuests — not just the
current branch scope — surfacing decisions and constraints from past projects
that are semantically similar to the current query.

Two main capabilities:

  1. analogical_search(params, db, config)
       Cross-quest vector search across Decision, Constraint, Requirement nodes.
       Returns ranked results with quest attribution where available.
       Skips results from the current quest (already covered by current_truth).

  2. find_similar_quests(current_quest_id, db, config, limit)
       Finds MainQuests whose overall embedding is most similar to the current
       quest — useful for bootstrapping context when starting a new quest that
       resembles past work.

Quest attribution is attempted via the ESTABLISHED → SENT_IN → WORKING_ON
relationship chain. Degrades gracefully to {quest_id: "", quest_name: ""}
if the chain is not present (e.g. artifacts created before attribution was wired).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

from campy.brain.hippocampus.graph import embeddings as emb


# Artifact tables to search across quests.
# GlobalConstraint / GlobalPreference are workspace-scope, always included.
# Lesson nodes (B11) included for cross-project lesson recall.
CROSS_QUEST_TABLES = [
    ("Decision",         "decision_emb_idx",          "decision_id"),
    ("Constraint",       "constraint_emb_idx",         "constraint_id"),
    ("Requirement",      "requirement_emb_idx",        "requirement_id"),
    ("GlobalConstraint", "globalconstraint_emb_idx",   "global_constraint_id"),
    ("GlobalPreference", "globalpreference_emb_idx",   "global_preference_id"),
    ("Lesson",           "lesson_emb_idx",             "lesson_id"),   # B11
]

# Default thresholds
DEFAULT_MIN_SIMILARITY = 0.70  # B279: true cosine similarity floor for analogical recall
DEFAULT_LIMIT = 5


# ---------------------------------------------------------------------------
# Quest attribution
# ---------------------------------------------------------------------------

def _get_quest_for_artifact(db, table: str, pk_col: str, node_id: str) -> dict:
    """
    Attempt to attribute an artifact to a MainQuest via the relationship chain:
      (Artifact) <-[ESTABLISHED]- (Message) -[SENT_IN]-> (Session)
                                                -[WORKING_ON]-> (MainQuest)

    Returns {quest_id, quest_name} or {} if the chain is not present.
    Fails gracefully on any DB error.
    """
    try:
        result = db.execute(
            f"""
            MATCH (art:{table} {{{pk_col}: $nid}})
            MATCH (msg:Message)-[:ESTABLISHED]->(art)
            MATCH (msg)-[:SENT_IN]->(sess:Session)
            MATCH (sess)-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id, q.name
            LIMIT 1
            """,
            {"nid": node_id}
        )
        if result.has_next():
            row = result.get_next()
            return {"quest_id": row[0] or "", "quest_name": row[1] or ""}
    except Exception:
        pass
    return {"quest_id": "", "quest_name": ""}


# ---------------------------------------------------------------------------
# analogical_search
# ---------------------------------------------------------------------------

async def analogical_search(params: dict, db, config: dict) -> dict:
    """
    Cross-quest semantic search.

    Searches Decision, Constraint, Requirement, GlobalConstraint, GlobalPreference
    nodes across ALL MainQuests. Skips results from current_quest_id (those are
    already accessible via current_truth with branch scope).

    params: {query, current_quest_id?, limit, min_similarity?}

    Returns:
        {
            results: [
                {node_id, node_type, text_raw, similarity,
                 confidence, pathway_strength,
                 quest_id, quest_name}
            ],
            query: str,
            cross_quest: true,
            searched_tables: [str],
        }
    """
    query            = params.get("query", "").strip()
    current_quest_id = params.get("current_quest_id", "")
    limit            = int(params.get("limit", DEFAULT_LIMIT))
    min_similarity   = float(params.get("min_similarity", DEFAULT_MIN_SIMILARITY))

    if not query:
        return {"results": [], "query": query, "cross_quest": True,
                "searched_tables": []}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    query_vector = emb.embed(query, model_name=embedding_model)

    all_results = []
    per_table   = max(limit * 2, 10)
    searched    = []

    for table_name, index_name, pk_col in CROSS_QUEST_TABLES:
        try:
            rows = db.vector_search(table_name, index_name, query_vector, per_table)
        except Exception:
            continue

        searched.append(table_name)

        for row in rows:
            node       = row["node"]
            similarity = row["score"]

            if node.get("archived", False):
                continue
            if similarity < min_similarity:
                continue

            node_id = (
                node.get("decision_id")
                or node.get("constraint_id")
                or node.get("requirement_id")
                or node.get("global_constraint_id")
                or node.get("global_preference_id")
                or node.get("lesson_id", "unknown")
            )

            # Attempt quest attribution (degrades to empty dict gracefully)
            quest_info = _get_quest_for_artifact(db, table_name, pk_col, node_id)

            # Skip if this result is from the current quest (not analogical)
            if current_quest_id and quest_info.get("quest_id") == current_quest_id:
                continue

            all_results.append({
                "node_id":          node_id,
                "node_type":        table_name,
                "text_raw":         node.get("text_raw", ""),
                "similarity":       similarity,
                "confidence":       node.get("confidence", 0.0),
                "pathway_strength": node.get("pathway_strength", 0.0),
                "quest_id":         quest_info.get("quest_id", ""),
                "quest_name":       quest_info.get("quest_name", ""),
            })

    all_results.sort(key=lambda r: r["similarity"], reverse=True)

    return {
        "results":         all_results[:limit],
        "query":           query,
        "cross_quest":     True,
        "searched_tables": searched,
    }


# ---------------------------------------------------------------------------
# find_similar_quests
# ---------------------------------------------------------------------------

def find_similar_quests(current_quest_id: str, db, config: dict,
                        limit: int = 3) -> list[dict]:
    """
    Find MainQuests whose embedding is most similar to the current quest.
    Useful for bootstrapping cross-quest context when starting a new project
    that resembles past work.

    Returns list of {quest_id, name, similarity, purpose, status} dicts,
    excluding the current quest. Empty list on any error.

    Note: Uses db.vector_search on the mainquest_emb_idx (if available).
    Falls back to a Cypher MATCH if vector search is unavailable.
    """
    if not current_quest_id:
        return []

    try:
        # Get current quest embedding
        result = db.execute(
            "MATCH (q:MainQuest {quest_id: $qid}) "
            "RETURN q.embedding, q.name",
            {"qid": current_quest_id}
        )
        if not result.has_next():
            return []

        row = result.get_next()
        current_embedding = row[0]
        if not current_embedding:
            return []

    except Exception:
        return []

    # Vector search for similar quests
    similar = []
    try:
        rows = db.vector_search("MainQuest", "mainquest_emb_idx", current_embedding, limit + 1)
        for row in rows:
            node = row["node"]
            qid  = node.get("quest_id", "")
            if qid == current_quest_id:
                continue
            similar.append({
                "quest_id":   qid,
                "name":       node.get("name", ""),
                "similarity": row["score"],
                "purpose":    node.get("purpose", ""),
                "status":     node.get("status", ""),
            })
            if len(similar) >= limit:
                break
    except Exception:
        pass

    return similar
