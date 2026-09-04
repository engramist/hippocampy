from __future__ import annotations

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
    < 0.75 true cosine similarity        → no match, new concept stands alone
    0.75 – 0.92 true cosine similarity   → gray zone → trigger Step 6 contradiction arbitration
    > 0.92 true cosine similarity        → strong match → additive update via Step 7

Index: Concept embedding HNSW index (derived from table registry)
"""

import logging
import math

from campy.brain.hippocampus.table_registry import get_table
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


_logger = logging.getLogger(__name__)

_CONCEPT_TABLE = get_table("Concept")
assert _CONCEPT_TABLE is not None and _CONCEPT_TABLE.vector_index is not None
_CONCEPT_INDEX = _CONCEPT_TABLE.vector_index
_ARCHIVED_RATIOS: dict[str, float] = {}

MATCH_THRESHOLD  = 0.75   # B279: true cosine similarity below this → no match
GRAY_ZONE_UPPER  = 0.92   # B279: true cosine similarity above this → additive match

# B159: Topological overlap tuning
TOPO_SEARCH_FLOOR    = 0.55   # B279: true cosine similarity floor for topo checks
TOPO_JACCARD_WEIGHT  = 0.30   # how much jaccard overlap boosts similarity
MIN_JACCARD_BOOST    = 0.50   # min jaccard to apply any boost
# L10 note: headroom is kept for self-exclusion only. Archived nodes are
# excluded by the HNSW projected graph at the call site (future M5 upgrade).
# For now, increase headroom so postfilter has more room after archived removal.
def set_archived_ratios(report: dict[str, dict]) -> None:
    """Update cached archived-ratio data from sweep index hygiene reports."""
    global _ARCHIVED_RATIOS
    _ARCHIVED_RATIOS = {
        table: float(data.get("archived_ratio", 0.0) or 0.0)
        for table, data in (report or {}).items()
    }


def _headroom(limit: int, archived_ratio: float) -> int:
    """Adaptive fetch budget using archived ratio (B285).

    Returns the total fetch count (not just extra rows). The +5 floor keeps
    room for the self/exclude_ids postfilter even before the first sweep
    populates _ARCHIVED_RATIOS (ratio 0); without it, fetch == limit and the
    exclusion filter can starve the candidate set.
    """
    return max(limit + 5, min(50, math.ceil(limit * (1 + 2 * archived_ratio))))


def retrieve_candidates(embedding: list[float], exclude_id: str,
                        db, limit: int = 5,
                        exclude_ids: list[str] | None = None) -> list[dict]:
    """
    Search the Concept embedding index for existing Concept nodes similar to embedding.
    Excludes the newly-created node (exclude_id) and archived nodes.

    Returns list of:
        {concept_id, text_raw, similarity, pathway_strength, confidence,
         gist_class, schema_org_type, created_at}
    sorted descending by similarity, filtered to similarity >= MATCH_THRESHOLD.

    quest_id scoping is deferred to M5 (MainQuest wiring).
    """
    try:
        archived_ratio = float(_ARCHIVED_RATIOS.get("Concept", 0.0) or 0.0)
        fetch_k = _headroom(limit, archived_ratio)
        raw = db.vector_search("Concept", _CONCEPT_INDEX, embedding, fetch_k)
    except Exception:
        # L9 fix: log the error so persistent index failures are visible.
        # Returning [] causes the orchestrator to treat this as "no match",
        # which will create new nodes — a graph fill with duplicates is the
        # failure mode. Operators must monitor these logs.
        _logger.exception(
            "Vector search on %s failed — returning empty candidates (may cause duplicate nodes)",
            _CONCEPT_INDEX,
        )
        return []

    # L8 fix: build full exclusion set including previously-created concepts
    # from the same run to prevent same-message self-matching.
    _exclude = set()
    if exclude_id:
        _exclude.add(exclude_id)
    if exclude_ids:
        _exclude.update(exclude_ids)

    results = []
    topo_candidates = []
    for row in raw:
        node = row.get("node") or {}
        sim  = row.get("score") or 0.0

        # Basic filters
        cid = node.get("concept_id")
        if sim < TOPO_SEARCH_FLOOR:
            continue
        if cid in _exclude:
            continue
        if node.get("archived", False):
            continue

        candidate = {
            "concept_id":       cid or "",
            "text_raw":         node.get("text_raw", ""),
            "similarity":       sim,
            "pathway_strength": node.get("pathway_strength", 0.0),
            "confidence":       node.get("confidence", 0.0),
            "gist_class":       node.get("gist_class", ""),
            "schema_org_type":  node.get("schema_org_type", ""),
            "created_at":       node.get("created_at", ""),
        }

        if sim >= MATCH_THRESHOLD:
            results.append(candidate)
        else:
            # sim is between TOPO_SEARCH_FLOOR and MATCH_THRESHOLD
            topo_candidates.append(candidate)

    # B158: Filter out candidates that are DISTINCT_FROM any of the exclude_ids
    if exclude_ids and results:
        try:
            distinct_pairs = _get_distinct_pairs(db, exclude_ids)
            if distinct_pairs:
                results = [h for h in results if h["concept_id"] not in distinct_pairs]
        except Exception:
            _logger.exception("_get_distinct_pairs failed")

    # B159: Check topological overlap for sub-threshold candidates and promote
    # those with sufficiently high neighborhood Jaccard similarity.
    if topo_candidates and exclude_ids:
        try:
            incoming_neighbors = _get_neighbor_set(db, exclude_ids)
            # limit neighbor set size for performance (deterministic sampling)
            if len(incoming_neighbors) > 50:
                incoming_neighbors = set(sorted(incoming_neighbors)[:50])

            for candidate in topo_candidates:
                try:
                    cand_neighbors = _get_neighbor_set(db, [candidate["concept_id"]])
                    # cap candidate neighbor set size for performance
                    if len(cand_neighbors) > 50:
                        cand_neighbors = set(sorted(cand_neighbors)[:50])
                    jaccard = _jaccard_similarity(incoming_neighbors, cand_neighbors)
                    if jaccard >= MIN_JACCARD_BOOST:
                        orig_sim = candidate.get("similarity", 0.0)
                        boosted_sim = orig_sim + (jaccard * TOPO_JACCARD_WEIGHT)
                        if boosted_sim >= MATCH_THRESHOLD:
                            # preserve original similarity for Step 6 reference
                            candidate["orig_similarity"] = orig_sim
                            candidate["similarity"] = boosted_sim
                            candidate["boosted_similarity"] = boosted_sim
                            candidate["topo_boosted"] = True
                            candidate["jaccard_overlap"] = jaccard
                            results.append(candidate)
                            _logger.info(
                                "B159: Topological boost: '%s' (%.2f→%.2f, jaccard=%.2f)",
                                candidate.get("text_raw", ""),
                                orig_sim,
                                boosted_sim, jaccard
                            )
                except Exception:
                    _logger.exception("_get_neighbor_set or boost calc failed for %s", candidate.get("concept_id"))
        except Exception:
            _logger.exception("Topological candidate check failed")

    # Sort by similarity descending, cap to requested limit
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:limit]


def _get_distinct_pairs(db, concept_ids: list[str]) -> set:
    """Get concept IDs that are DISTINCT_FROM any of the given IDs."""
    if not concept_ids:
        return set()
    try:
        gw = GraphGateway(db, REGISTRY) if not isinstance(db, GraphGateway) else db
        rows = gw.run_sync("retrieval.get_distinct_pairs", ids=concept_ids)
        out = set()
        for row in rows:
            cid = row.get("b.concept_id") if hasattr(row, "get") else row[0]
            if cid:
                out.add(cid)
        return out
    except Exception:
        _logger.exception("_get_distinct_pairs query failed")
        return set()


def _get_neighbor_set(db, concept_ids: list[str]) -> set:
    """Get the set of 1-hop neighbor concept_ids for a list of concepts.

    Considers named edges (REQUIRES, ENABLES, etc.) and strong CO_OCCURS_WITH (count >= 3).
    Returns a set of neighbor concept_ids (strings).
    """
    if not concept_ids:
        return set()

    out = set()
    try:
        gw = GraphGateway(db, REGISTRY) if not isinstance(db, GraphGateway) else db
        # Named edges (any relationship to neighbor)
        rows = gw.run_sync("retrieval.get_neighbor_concepts", ids=concept_ids)
        for row in rows:
            cid = row.get("n.concept_id") if hasattr(row, "get") else row[0]
            if cid:
                out.add(cid)

        # Strong CO_OCCURS_WITH neighbors (count >= 3)
        co_rows = gw.run_sync("retrieval.get_co_occurring_neighbors", ids=concept_ids)
        for crow in co_rows:
            cid = crow.get("n.concept_id") if hasattr(crow, "get") else crow[0]
            if cid:
                out.add(cid)
    except Exception:
        _logger.exception("_get_neighbor_set query failed")

    return out


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity: |intersection| / |union|.

    Returns 0.0 when both sets empty.
    """
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    try:
        return len(intersection) / len(union) if union else 0.0
    except Exception:
        return 0.0
