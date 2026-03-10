"""
Step 5 — Dual-Scope Candidate Retrieval (Availability Heuristic)

Named IP Claim: Availability Heuristic — the system preferentially surfaces
recently reinforced and strongly activated nodes (high pathway_strength)
just as the human mind favors what is mentally available over what is
statistically correct.

Check for existing Concept nodes that match the incoming concept's embedding.
Branch scope first (same MainQuest — M5 adds quest_id filter).
Global scope: GlobalConstraint/GlobalPreference (M5).

Similarity thresholds:
  < 0.75        → no match, new concept stands alone
  0.75 – 0.92   → gray zone → trigger Step 6 contradiction arbitration
  > 0.92        → strong match → additive update via Step 7

Index: concept_emb_idx (HNSW on Concept.embedding FLOAT[384])
"""

MATCH_THRESHOLD  = 0.75   # below → no match
GRAY_ZONE_UPPER  = 0.92   # above → strong match (additive, no arbitration)

# Fetch more than needed to have room after filtering archived + self
_FETCH_HEADROOM  = 5


def retrieve_candidates(embedding: list[float], exclude_id: str,
                        db, limit: int = 5) -> list[dict]:
    """
    Search concept_emb_idx for existing Concept nodes similar to embedding.
    Excludes the newly-created node (exclude_id) and archived nodes.

    Returns list of:
        {concept_id, text_raw, similarity, pathway_strength, confidence,
         gist_class, schema_org_type, created_at}
    sorted descending by similarity, filtered to similarity >= MATCH_THRESHOLD.

    quest_id scoping is deferred to M5 (MainQuest wiring).
    """
    try:
        raw = db.vector_search("concept_emb_idx", embedding, limit + _FETCH_HEADROOM)
    except Exception:
        return []

    results = []
    for row in raw:
        node = row["node"]
        sim  = row["score"]

        if sim < MATCH_THRESHOLD:
            continue
        if node.get("concept_id") == exclude_id:
            continue
        if node.get("archived", False):
            continue

        results.append({
            "concept_id":       node.get("concept_id", ""),
            "text_raw":         node.get("text_raw", ""),
            "similarity":       sim,
            "pathway_strength": node.get("pathway_strength", 0.0),
            "confidence":       node.get("confidence", 0.0),
            "gist_class":       node.get("gist_class", ""),
            "schema_org_type":  node.get("schema_org_type", ""),
            "created_at":       node.get("created_at", ""),
        })

    # Sort by similarity descending, cap to requested limit
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:limit]
