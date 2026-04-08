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
  < 0.75        → no match, new concept stands alone
  0.75 – 0.92   → gray zone → trigger Step 6 contradiction arbitration
  > 0.92        → strong match → additive update via Step 7

Index: concept_emb_idx (HNSW on Concept.embedding FLOAT[384])
"""

import logging

_logger = logging.getLogger(__name__)

MATCH_THRESHOLD  = 0.75   # below → no match
GRAY_ZONE_UPPER  = 0.92   # above → strong match (additive, no arbitration)

# B159: Topological overlap tuning
TOPO_SEARCH_FLOOR    = 0.55   # consider these for topological check
TOPO_JACCARD_WEIGHT  = 0.30   # how much jaccard overlap boosts similarity
MIN_JACCARD_BOOST    = 0.50   # min jaccard to apply any boost
# L10 note: headroom is kept for self-exclusion only. Archived nodes are
# excluded by the HNSW projected graph at the call site (future M5 upgrade).
# For now, increase headroom so postfilter has more room after archived removal.
_FETCH_HEADROOM  = 20


def retrieve_candidates(embedding: list[float], exclude_id: str,
                        db, limit: int = 5,
                        exclude_ids: list[str] | None = None) -> list[dict]:
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
        raw = db.vector_search("Concept", "concept_emb_idx", embedding, limit + _FETCH_HEADROOM)
    except Exception:
        # L9 fix: log the error so persistent index failures are visible.
        # Returning [] causes the orchestrator to treat this as "no match",
        # which will create new nodes — a graph fill with duplicates is the
        # failure mode. Operators must monitor these logs.
        _logger.exception(
            "Vector search on concept_emb_idx failed — "
            "returning empty candidates (may cause duplicate nodes)"
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
        rows = db.execute(
            "MATCH (a:Concept)-[:DISTINCT_FROM]-(b:Concept) "
            "WHERE a.concept_id IN $ids "
            "RETURN b.concept_id",
            {"ids": concept_ids}
        )
        out = set()
        while rows.has_next():
            row = rows.get_next()
            out.add(row[0])
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
        # Named edges (any relationship to neighbor)
        rows = db.execute(
            "MATCH (c:Concept)-[r]->(n:Concept) "
            "WHERE c.concept_id IN $ids "
            "  AND n.archived = false "
            "  AND NOT n.concept_id IN $ids "
            "RETURN DISTINCT n.concept_id",
            {"ids": concept_ids}
        )
        while rows.has_next():
            row = rows.get_next()
            out.add(row[0])

        # Strong CO_OCCURS_WITH neighbors (count >= 3)
        co_rows = db.execute(
            "MATCH (c:Concept)-[r:CO_OCCURS_WITH]->(n:Concept) "
            "WHERE c.concept_id IN $ids "
            "  AND r.count >= 3 "
            "  AND n.archived = false "
            "  AND NOT n.concept_id IN $ids "
            "RETURN DISTINCT n.concept_id",
            {"ids": concept_ids}
        )
        while co_rows.has_next():
            crow = co_rows.get_next()
            out.add(crow[0])
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
