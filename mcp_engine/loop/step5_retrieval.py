"""
Step 5 — Dual-Scope Candidate Retrieval (Availability Heuristic)

Check for existing nodes that match the incoming concept.
Branch scope first (same MainQuest), then global scope (GlobalConstraint/GlobalPreference).

Used to detect:
  - Duplicates / additive updates (strengthen existing node)
  - Contradictions (trigger Step 6 arbitration)
  - Global constraints that apply regardless of quest scope

Similarity thresholds:
  < 0.75              → no match, treat as new concept
  0.75 – 0.92         → gray zone → trigger Step 6 contradiction arbitration
  > 0.92              → strong match → additive update (Step 7)

Search uses kuzu_client.vector_search() with projected graphs
(active nodes only — archived excluded from retrieval).

M4 scope: implement this step.
"""

MATCH_THRESHOLD = 0.75
GRAY_ZONE_UPPER = 0.92


def retrieve_candidates(embedding: list[float], quest_id: str,
                        scope: str = "branch") -> list[dict]:
    """
    Search branch scope then global scope for existing matching nodes.
    Returns list of {node_id, node_type, text_raw, similarity, pathway_strength}.
    """
    # TODO M4: implement via kuzu_client.vector_search()
    pass
