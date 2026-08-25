"""
campy/brain/thalamus/bundle_compiler.py — Retrieval Intelligence Layer

Assembles heterogeneous context from all memory types into shaped ContextBundles,
compressed to fit the requesting agent's token budget.

Pipeline stages:
1. Exact facts (GlobalConstraint + GlobalPreference)
2. Semantic context (current_truth results)
3. Graph structure (relationship traversals)
4. Tabular data (if Dataset links exist)
5. Summaries (wiki projection or LLM-generated)
6. App continuity (B321 — earlier sessions of the same platform App;
   exact-id join, not similarity, and omitted entirely when the calling
   session has no `external_app_id`)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from campy.brain.hippocampus.provenance import authority_of

_logger = logging.getLogger(__name__)


def _table_has_authority(db, table: str) -> bool:
    """B313: best-effort check for whether `table` already has the
    `authority` column, so the exact-fact / semantic-context stages below
    can include it in their RETURN when present without hard-failing (a
    Kuzu binder exception) against a schema that predates B313 — e.g. the
    reduced fixture tables some tests build directly rather than going
    through campy.brain.hippocampus.schema.NODE_TABLES. Mirrors the
    exception-tolerant `_column_exists()` pattern in schema.py's migration
    step.
    """
    try:
        r = db.execute(f"CALL table_info('{table}') RETURN *")
        while r.has_next():
            row = r.get_next()
            if str(row[1]).lower() == "authority":
                return True
    except Exception:
        pass
    return False


def _table_has_flagged_for_review(db, table: str) -> bool:
    """Same tolerance as `_table_has_authority`, for `flagged_for_review`
    (B339's anomaly flag, now consulted at recall time). Reduced fixture
    tables built directly by tests don't always carry every column the
    real schema.py-generated tables do."""
    try:
        r = db.execute(f"CALL table_info('{table}') RETURN *")
        while r.has_next():
            row = r.get_next()
            if str(row[1]).lower() == "flagged_for_review":
                return True
    except Exception:
        pass
    return False


@dataclass
class BundleSection:
    """One section of a ContextBundle."""
    section_type: str  # "exact_fact", "plans", "semantic", "graph", "tabular", "summary"
    content: list[dict]
    token_estimate: int
    source_node_ids: list[str] = field(default_factory=list)


@dataclass
class ContextBundle:
    """Assembled context from all memory types."""
    query: str
    sections: list[BundleSection]
    total_token_estimate: int
    token_budget: int
    truncated: bool  # True if budget forced compression
    sources: list[str] = field(default_factory=list)
    compilation_ms: float = 0.0

    def to_dict(self) -> dict:
        """Serialize for MCP response."""
        return {
            "query": self.query,
            "sections": [
                {
                    "type": s.section_type,
                    "content": s.content,
                    "token_estimate": s.token_estimate,
                    "source_node_ids": s.source_node_ids,
                }
                for s in self.sections
            ],
            "total_token_estimate": self.total_token_estimate,
            "token_budget": self.token_budget,
            "truncated": self.truncated,
            "sources": self.sources,
            "compilation_ms": self.compilation_ms,
        }


BUDGET_TIERS = {
    "small": {
        "max_semantic": 3,
        "max_graph_hops": 1,
        "include_tabular_summary": True,
        "include_raw_tabular": False,
    },
    "medium": {
        "max_semantic": 10,
        "max_graph_hops": 2,
        "include_tabular_summary": True,
        "include_raw_tabular": True,
        "max_tabular_rows": 20,
    },
    "large": {
        "max_semantic": 25,
        "max_graph_hops": 2,
        "include_tabular_summary": True,
        "include_raw_tabular": True,
        "max_tabular_rows": 100,
    },
}


def _get_tier(token_budget: int) -> str:
    """Determine budget tier from token count."""
    if token_budget <= 8000:
        return "small"
    elif token_budget <= 128000:
        return "medium"
    return "large"


async def compile_bundle(
    query: str,
    db,
    config: dict,
    token_budget: int = 32000,
    agent_type: Optional[str] = None,
    quest_id: Optional[str] = None,
    session_id: Optional[str] = None,
    include_tabular: bool = True,
    include_summaries: bool = True,
) -> ContextBundle:
    """
    Compile a context bundle from all memory types.

    Pipeline stages (in priority order):
    1. Exact facts (GlobalConstraint + GlobalPreference)
    2. Plan lane (Plan + PlanStep outcomes)
    3. Semantic context (current_truth results)
    4. Graph structure (relationship traversals)
    5. Tabular data (if 249 complete and include_tabular=True)
    6. Summaries (wiki projection, if available)
    7. App continuity (B321 — earlier sessions of the same App, keyed off
       `session_id`; requires `Session.external_app_id` to be set, so this
       is a no-op for local Campy)

    Returns:
        ContextBundle with assembled and prioritized context
    """
    import time
    start_time = time.time()

    tier = _get_tier(token_budget)
    tier_config = BUDGET_TIERS[tier]

    sections = []
    sources = []
    cumulative_tokens = 0

    # Stage 1: Exact facts
    exact_facts_section = await _stage_exact_facts(db, query, config, tier_config)
    if exact_facts_section and exact_facts_section.content:
        sections.append(exact_facts_section)
        cumulative_tokens += exact_facts_section.token_estimate
        sources.extend(exact_facts_section.source_node_ids)

    if cumulative_tokens >= token_budget * 0.9:  # 90% of budget
        bundle = ContextBundle(
            query=query,
            sections=sections,
            total_token_estimate=cumulative_tokens,
            token_budget=token_budget,
            truncated=True,
            sources=sources,
            compilation_ms=(time.time() - start_time) * 1000,
        )
        return bundle

    # Stage 2: Plan lane
    plans_section = await _stage_plans(db, query, config, tier_config)
    if plans_section and plans_section.content:
        sections.append(plans_section)
        cumulative_tokens += plans_section.token_estimate
        sources.extend(plans_section.source_node_ids)

    if cumulative_tokens >= token_budget * 0.9:
        bundle = ContextBundle(
            query=query,
            sections=sections,
            total_token_estimate=cumulative_tokens,
            token_budget=token_budget,
            truncated=True,
            sources=sources,
            compilation_ms=(time.time() - start_time) * 1000,
        )
        return bundle

    # Stage 3: Semantic context
    semantic_section = await _stage_semantic_context(db, query, config, tier_config)
    if semantic_section and semantic_section.content:
        sections.append(semantic_section)
        cumulative_tokens += semantic_section.token_estimate
        sources.extend(semantic_section.source_node_ids)

    if cumulative_tokens >= token_budget * 0.9:
        bundle = ContextBundle(
            query=query,
            sections=sections,
            total_token_estimate=cumulative_tokens,
            token_budget=token_budget,
            truncated=True,
            sources=sources,
            compilation_ms=(time.time() - start_time) * 1000,
        )
        return bundle

    # Stage 4: Graph structure
    graph_section = await _stage_graph_structure(db, query, config, tier_config, sources)
    if graph_section and graph_section.content:
        sections.append(graph_section)
        cumulative_tokens += graph_section.token_estimate
        sources.extend(graph_section.source_node_ids)

    if cumulative_tokens >= token_budget * 0.9:
        bundle = ContextBundle(
            query=query,
            sections=sections,
            total_token_estimate=cumulative_tokens,
            token_budget=token_budget,
            truncated=True,
            sources=sources,
            compilation_ms=(time.time() - start_time) * 1000,
        )
        return bundle

    # Stage 5: Tabular data
    if include_tabular:
        tabular_section = await _stage_tabular_data(
            db, query, config, tier_config, sources, token_budget - cumulative_tokens
        )
        if tabular_section and tabular_section.content:
            sections.append(tabular_section)
            cumulative_tokens += tabular_section.token_estimate
            sources.extend(tabular_section.source_node_ids)

    if cumulative_tokens >= token_budget * 0.95:
        bundle = ContextBundle(
            query=query,
            sections=sections,
            total_token_estimate=cumulative_tokens,
            token_budget=token_budget,
            truncated=True,
            sources=sources,
            compilation_ms=(time.time() - start_time) * 1000,
        )
        return bundle

    # Stage 6: Summaries
    if include_summaries:
        summaries_section = await _stage_summaries(db, query, config, sources, token_budget - cumulative_tokens)
        if summaries_section and summaries_section.content:
            sections.append(summaries_section)
            cumulative_tokens += summaries_section.token_estimate
            sources.extend(summaries_section.source_node_ids)

    # Stage 7: App continuity (B321). Not budget-gated like the stages
    # above — it's an exact-id join keyed off session_id, not a query
    # embedding pass, so it's cheap regardless of how much budget the
    # earlier stages already spent, and skipping it purely because the
    # budget is nearly exhausted would silently drop the one section
    # whose whole point is "don't start from nothing" continuity.
    if cumulative_tokens < token_budget * 0.95:
        continuity_section = await _stage_app_continuity(db, session_id)
        if continuity_section and continuity_section.content:
            sections.append(continuity_section)
            cumulative_tokens += continuity_section.token_estimate
            sources.extend(continuity_section.source_node_ids)

    truncated = cumulative_tokens >= token_budget * 0.95

    bundle = ContextBundle(
        query=query,
        sections=sections,
        total_token_estimate=cumulative_tokens,
        token_budget=token_budget,
        truncated=truncated,
        sources=list(set(sources)),  # Deduplicate
        compilation_ms=(time.time() - start_time) * 1000,
    )

    return bundle


async def _stage_exact_facts(db, query: str, config: dict, tier_config: dict) -> Optional[BundleSection]:
    """
    Stage 1: Extract exact facts (GlobalConstraint + GlobalPreference nodes).

    Returns only nodes with high similarity to query (threshold: 0.70).
    These are cheap (short text) and high-value, so always include.
    """
    try:
        from campy.brain.hippocampus.graph import embeddings as emb

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        query_embedding = emb.embed(query, model_name=embedding_model)

        # Kuzu/openCypher does not allow `OR` between labels inside a single MATCH
        # pattern, so each label needs its own query. These are issued separately
        # (not joined with UNION) because Kuzu 0.11.3's ORDER BY/LIMIT after a
        # chained UNION binds only to the last branch, not the combined result set
        # - confirmed empirically against the pinned version - so a single UNION'd
        # query cannot enforce a cap across both labels. Distance is cosine distance
        # (1 - cosine similarity), matching the metric the HNSW indexes are pinned
        # to elsewhere (see kuzu_client.py's _INDEX_METRIC); Kuzu has no
        # `vector_distance` function.
        limit = 10
        rows: list[tuple] = []
        for label in ("GlobalConstraint", "GlobalPreference"):
            # B313: include authority when the table has the column (see
            # _table_has_authority docstring for why this is checked rather
            # than assumed).
            has_authority = _table_has_authority(db, label)
            authority_select = ", n.authority as authority" if has_authority else ""
            flagged_filter = (
                " AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                if _table_has_flagged_for_review(db, label) else ""
            )
            cypher = f"""
                MATCH (n:{label})
                WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                  {flagged_filter}
                RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence{authority_select}
                LIMIT $limit
            """
            result = db.execute(cypher, {"query_embedding": query_embedding, "limit": limit})
            while result.has_next():
                row = result.get_next()
                rows.append(row if has_authority else (*row, None))

        rows = rows[:limit]

        content = []
        node_ids = []
        for text, node_type, confidence, authority in rows:
            content.append({
                "text": text,
                "type": node_type,
                "confidence": confidence if confidence is not None else 0.5,
                "authority": authority_of(authority),
            })
            node_ids.append((text or "")[:20])

        if not content:
            return None

        # Estimate tokens (rough: 1 token per word, avg 5 words per fact)
        token_estimate = len(content) * 50

        return BundleSection(
            section_type="exact_fact",
            content=content,
            token_estimate=token_estimate,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_exact_facts: %s", e)
        return None


async def _stage_semantic_context(db, query: str, config: dict, tier_config: dict) -> Optional[BundleSection]:
    """
    Stage 2: Retrieve semantic context as a lightweight semantic preview.

    Note: This stage does not replicate full current_truth fusion logic.

    B305: distance floor tightened from 0.40 to 0.30 (similarity 0.60 → 0.70)
    to match the convention already enforced in `_stage_exact_facts`.
    """
    try:
        from campy.brain.hippocampus.graph import embeddings as emb

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        query_embedding = emb.embed(query, model_name=embedding_model)

        # Simple semantic search across all searchable nodes. Same per-label-query
        # and cosine-distance fix as _stage_exact_facts above (see that function's
        # comment for why UNION isn't used: ORDER BY/LIMIT after a chained UNION
        # binds only to the last branch in Kuzu 0.11.3, not the combined result
        # set, so a single UNION'd query can't produce a true top-N across labels).
        # Each label query is independently ordered/limited (a single MATCH's
        # ORDER BY/LIMIT is unaffected by the UNION issue), then the per-label
        # results are merged and re-sorted by distance in Python for a global
        # top-N cut.
        limit = tier_config.get("max_semantic", 10)
        rows: list[tuple] = []
        for label in ("Concept", "Decision", "Constraint", "Requirement"):
            # B313: include authority when the table has the column — see
            # _table_has_authority docstring.
            has_authority = _table_has_authority(db, label)
            authority_select = ", n.authority as authority" if has_authority else ""
            flagged_filter = (
                " AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                if _table_has_flagged_for_review(db, label) else ""
            )
            cypher = f"""
                MATCH (n:{label})
                WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                  {flagged_filter}
                RETURN n.text_raw as text, label(n) as node_type,
                       n.pathway_strength as pathway_strength, n.confidence as confidence,
                       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist{authority_select}
                ORDER BY dist ASC
                LIMIT $limit
            """
            result = db.execute(cypher, {"query_embedding": query_embedding, "limit": limit})
            while result.has_next():
                row = result.get_next()
                rows.append(row if has_authority else (*row, None))

        rows.sort(key=lambda row: row[4])
        rows = rows[:limit]

        content = []
        node_ids = []
        for text, node_type, pathway_strength, confidence, _dist, authority in rows:
            content.append({
                "text": text if text is not None else "",
                "type": node_type if node_type is not None else "Unknown",
                "pathway_strength": pathway_strength if pathway_strength is not None else 0.5,
                "confidence": confidence if confidence is not None else 0.5,
                "authority": authority_of(authority),
            })
            node_ids.append((text or "")[:20])

        if not content:
            return None

        token_estimate = len(content) * 80  # Semantic results are longer

        return BundleSection(
            section_type="semantic",
            content=content,
            token_estimate=token_estimate,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_semantic_context: %s", e)
        return None


async def _stage_plans(
    db, query: str, config: dict, tier_config: dict, min_similarity: float = 0.70
) -> Optional[BundleSection]:
    """
    Stage 2: Retrieve plan lane context using the same ranking as recall_plans.

    PlanStep is not separately retrievable here; steps are carried inline with
    parent Plan records to preserve execution context.

    B305: plans are ranking-only, no relevance floor — the top-N are handed
    back regardless of match quality, so an off-topic query still gets "the
    best available" plans as if relevant. Only plans whose `similarity` field
    clears `min_similarity` (mirrors the 0.70 convention in
    `_stage_exact_facts`) are kept. B303's lexical identifier bypass
    (`lexical_exact`) is exempt from this floor by design — an exact `\\bB\\d+\\b`
    match is strong evidence regardless of embedding distance.
    """
    try:
        from campy.brain.thalamus.tools.quests import recall_plans_for_query

        limit = tier_config.get("max_semantic", 10)
        plans = await recall_plans_for_query(
            goal_query=query,
            db=db,
            config=config,
            limit=limit,
            min_valence=-1.0,
        )
        plans = [
            plan
            for plan in plans
            if plan.get("lexical_exact") or float(plan.get("similarity") or 0.0) >= min_similarity
        ]
        if not plans:
            return None

        content = []
        node_ids = []
        for plan in plans:
            node_id = plan.get("plan_id")
            if node_id:
                node_ids.append(node_id)
            content.append(
                {
                    "plan_id": node_id,
                    "goal": plan.get("goal", ""),
                    "status": plan.get("status"),
                    "valence": plan.get("valence"),
                    "pathway_strength": plan.get("pathway_strength"),
                    "similarity": plan.get("similarity"),
                    "steps": plan.get("steps", []),
                }
            )

        token_estimate = max(1, len(content)) * 150
        return BundleSection(
            section_type="plans",
            content=content,
            token_estimate=token_estimate,
            source_node_ids=node_ids,
        )
    except Exception as e:
        print(f"Error in _stage_plans: {e}")
        return None



# Concept<->Concept is the schema's only rich set of peer-to-peer semantic
# relationships (Decision/Constraint/Requirement mostly point to Session/Label
# provenance edges, not to each other) - see backlog/B252.md audit findings.
_GRAPH_REL_TYPES = (
    "REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER"
    "|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO"
)


async def _stage_graph_structure(
    db, query: str, config: dict, tier_config: dict, existing_sources: list[str]
) -> Optional[BundleSection]:
    """
    Stage 3: Extract graph structure (relationships) from top semantic results.

    Finds Concept nodes closest to the query (same 0.30 distance convention as
    _stage_exact_facts/_stage_semantic_context), then traverses 1-2 hops of
    Concept<->Concept relationships from each anchor. Hop depth is one MATCH
    per depth level (not Kuzu variable-length syntax) chained in a single
    query per depth, since both ends stay within the Concept table - this
    deliberately avoids UNION ALL across differently-typed node tables, which
    Kuzu 0.11.3's binder rejects (see B280's "Binder exception: a has data
    type NODE but NODE was expected").

    Returns: structured connections like "concept a --REQUIRES--> concept b"
    """
    try:
        from campy.brain.hippocampus.graph import embeddings as emb

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        query_embedding = emb.embed(query, model_name=embedding_model)

        has_flagged = _table_has_flagged_for_review(db, "Concept")
        anchor_flagged_filter = (
            " AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)" if has_flagged else ""
        )
        anchor_cypher = f"""
            MATCH (n:Concept)
            WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
              {anchor_flagged_filter}
            RETURN n.concept_id as id, n.text_raw as text,
                   (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist
            ORDER BY dist ASC
            LIMIT 5
        """
        result = db.execute(anchor_cypher, {"query_embedding": query_embedding})
        anchors: list[tuple] = []
        while result.has_next():
            anchors.append(result.get_next())

        if not anchors:
            return None

        max_hops = max(1, min(2, tier_config.get("max_graph_hops", 1)))

        content = []
        node_ids = []
        seen_edges: set[tuple] = set()
        for anchor_id, anchor_text, _dist in anchors:
            one_hop_flagged_filter = (
                " AND (b.flagged_for_review IS NULL OR b.flagged_for_review = false)" if has_flagged else ""
            )
            one_hop_cypher = f"""
                MATCH (a:Concept)-[r:{_GRAPH_REL_TYPES}]-(b:Concept)
                WHERE a.concept_id = $aid
                  {one_hop_flagged_filter}
                RETURN label(r), b.concept_id, b.text_raw
                LIMIT 10
            """
            result = db.execute(one_hop_cypher, {"aid": anchor_id})
            while result.has_next():
                rel_type, b_id, b_text = result.get_next()
                key = (anchor_id, rel_type, b_id)
                if key not in seen_edges:
                    seen_edges.add(key)
                    content.append({
                        "from": anchor_text,
                        "relationship": rel_type,
                        "to": b_text,
                    })
                    node_ids.append(b_id)

            if max_hops >= 2:
                two_hop_flagged_filter = (
                    " AND (mid.flagged_for_review IS NULL OR mid.flagged_for_review = false)"
                    " AND (c.flagged_for_review IS NULL OR c.flagged_for_review = false)"
                    if has_flagged else ""
                )
                two_hop_cypher = f"""
                    MATCH (a:Concept)-[r1:{_GRAPH_REL_TYPES}]-(mid:Concept)
                          -[r2:{_GRAPH_REL_TYPES}]-(c:Concept)
                    WHERE a.concept_id = $aid AND c.concept_id <> a.concept_id
                      {two_hop_flagged_filter}
                    RETURN label(r1), mid.text_raw, label(r2), c.concept_id, c.text_raw
                    LIMIT 10
                """
                result = db.execute(two_hop_cypher, {"aid": anchor_id})
                while result.has_next():
                    r1_type, mid_text, r2_type, c_id, c_text = result.get_next()
                    key = (anchor_id, r1_type, mid_text, r2_type, c_id)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        content.append({
                            "from": anchor_text,
                            "relationship": f"{r1_type} -> {mid_text} -> {r2_type}",
                            "to": c_text,
                        })
                        node_ids.append(c_id)

        if not content:
            return None

        token_estimate = len(content) * 30

        return BundleSection(
            section_type="graph",
            content=content,
            token_estimate=token_estimate,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_graph_structure: %s", e)
        return None


async def _stage_tabular_data(
    db, query: str, config: dict, tier_config: dict, existing_sources: list[str], remaining_budget: int
) -> Optional[BundleSection]:
    """
    Stage 4: Include tabular data from Dataset nodes linked (via
    DESCRIBED_BY_DATASET) to Concept nodes matching the query.

    Same 0.30 distance convention as the sibling stages. B250's audit found
    that nothing in the ingestion pipeline currently creates a
    DESCRIBED_BY_DATASET edge, so this stage returns None against today's
    real data - the Cypher and SQLite lookup are exercised directly against
    fixture data in tests/test_bundle_compiler_stages.py, and it will start
    surfacing content once B250's key-fact extraction lands.
    """
    try:
        if remaining_budget <= 0:
            return None

        from campy.brain.hippocampus.graph import embeddings as emb
        from campy.brain.sensory_cortex import tabular_store

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        query_embedding = emb.embed(query, model_name=embedding_model)

        cypher = """
            MATCH (n:Concept)-[:DESCRIBED_BY_DATASET]->(d:Dataset)
            WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                  AND d.archived = false
            RETURN DISTINCT d.dataset_id as dataset_id, d.name as name,
                   d.description as description
            LIMIT 5
        """
        result = db.execute(cypher, {"query_embedding": query_embedding})
        datasets: list[tuple] = []
        while result.has_next():
            datasets.append(result.get_next())

        if not datasets:
            return None

        include_raw = tier_config.get("include_raw_tabular", False)
        sample_rows = tier_config.get("max_tabular_rows", 20) if include_raw else 0

        content = []
        node_ids = []
        tokens_used = 0
        for dataset_id, name, description in datasets:
            try:
                summary = tabular_store.get_table_summary(dataset_id, sample_rows=sample_rows)
            except FileNotFoundError:
                continue

            entry = {
                "dataset_id": dataset_id,
                "name": name,
                "description": description,
                "columns": summary["columns"],
                "row_count": summary["row_count"],
            }
            if include_raw:
                entry["sample_rows"] = summary["sample_rows"]

            entry_tokens = 30 + len(summary["columns"]) * 5 + len(entry.get("sample_rows", [])) * 20
            if tokens_used + entry_tokens > remaining_budget:
                break

            content.append(entry)
            node_ids.append(dataset_id)
            tokens_used += entry_tokens

        if not content:
            return None

        return BundleSection(
            section_type="tabular",
            content=content,
            token_estimate=tokens_used,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_tabular_data: %s", e)
        return None


async def _stage_summaries(
    db, query: str, config: dict, existing_sources: list[str], remaining_budget: int
) -> Optional[BundleSection]:
    """
    Stage 5: Include synthesized summaries (Lesson/Procedure nodes) for
    topics relevant to the query.

    Lesson and Procedure are the same node types the wiki projection
    (wiki_projection.py) renders into persona pages - Lesson is filtered to
    lesson_type='synthesis' to mirror that selection convention. Querying
    them live by embedding similarity (same 0.30 distance convention as the
    sibling stages) surfaces the same underlying content without depending
    on the wiki export sweep having run (it's disabled by default -
    config["wiki_projection"]["enabled"]).
    """
    try:
        if remaining_budget <= 0:
            return None

        from campy.brain.hippocampus.graph import embeddings as emb

        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        query_embedding = emb.embed(query, model_name=embedding_model)

        limit = 5
        rows: list[tuple] = []

        lesson_cypher = """
            MATCH (n:Lesson)
            WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                  AND n.archived = false AND n.lesson_type = 'synthesis'
            RETURN n.lesson_id as id, n.text_raw as text, 'Lesson' as node_type,
                   (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist
            ORDER BY dist ASC
            LIMIT $limit
        """
        result = db.execute(lesson_cypher, {"query_embedding": query_embedding, "limit": limit})
        while result.has_next():
            rows.append(result.get_next())

        procedure_cypher = """
            MATCH (n:Procedure)
            WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                  AND n.archived = false
            RETURN n.procedure_id as id, n.description as text, 'Procedure' as node_type,
                   (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist
            ORDER BY dist ASC
            LIMIT $limit
        """
        result = db.execute(procedure_cypher, {"query_embedding": query_embedding, "limit": limit})
        while result.has_next():
            rows.append(result.get_next())

        rows.sort(key=lambda row: row[3])
        rows = rows[:limit]

        content = []
        node_ids = []
        tokens_used = 0
        for node_id, text, node_type, _dist in rows:
            entry_tokens = 60
            if tokens_used + entry_tokens > remaining_budget:
                break
            content.append({"id": node_id, "type": node_type, "summary": text or ""})
            node_ids.append(node_id)
            tokens_used += entry_tokens

        if not content:
            return None

        return BundleSection(
            section_type="summary",
            content=content,
            token_estimate=tokens_used,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_summaries: %s", e)
        return None


def _relative_time_phrase(started_at) -> str:
    """"3 days ago" / "today" from an ISO timestamp string or datetime,
    for `_format_continuity_text`'s retrospective wording. Never raises —
    an unparseable/missing value degrades to "earlier" rather than
    breaking the whole section (B318 fail-open applies inside this
    formatting helper too, not just around the query)."""
    if not started_at:
        return "earlier"
    try:
        from datetime import datetime, timezone

        ts = started_at
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - ts).days
        if days <= 0:
            return "today"
        if days == 1:
            return "1 day ago"
        return f"{days} days ago"
    except Exception:
        return "earlier"


def _format_continuity_text(entry: dict) -> str:
    """Retrospective, advisory wording for one prior session's "Earlier
    work on this app" line — never imperative (B321). This scaffolding is
    the only place the wording is generated, and it must never contain
    "do not", "already claimed", "in progress", "owned by", or "locked" —
    see tests/test_app_continuity.py's denylist test. Prefers decisions
    and lessons over constraints/plan outcomes per the card ("a briefing,
    not a term dump"), and degrades gracefully (never raises) when a
    session has none of the above — bundle_compiler's caller already
    filters out sessions with nothing at all, so this only has to handle
    "some but not all four buckets populated".
    """
    when = _relative_time_phrase(entry.get("started_at"))

    decisions = entry.get("decisions") or []
    constraints = entry.get("constraints") or []
    lessons = entry.get("lessons") or []
    plans = entry.get("plans") or []

    highlights: list[str] = []
    if decisions:
        highlights.append(f"decided {decisions[0]['text']}")
    if lessons:
        highlights.append(f"lesson: {lessons[0]['text']}")
    if not highlights and constraints:
        highlights.append(f"noted a constraint: {constraints[0]['text']}")
    if not highlights and plans:
        highlights.append(f"tried: {plans[0]['text']}")

    body = "; ".join(highlights) if highlights else "recorded earlier activity on this app"

    source = None
    for bucket in (decisions, lessons, constraints, plans):
        if bucket and bucket[0].get("source"):
            source = bucket[0]["source"]
            break

    prefix = f"Session {when} (`{source}`)" if source else f"Session {when}"
    return f"{prefix} — {body}"


async def _stage_app_continuity(db, session_id: Optional[str]) -> Optional[BundleSection]:
    """
    Stage 7 (B321): earlier work on this platform App, surfaced across
    prior sessions sharing the calling session's `Session.external_app_id`.

    Unlike every sibling stage above, this is an **exact-id join**, not a
    similarity match — the `0.30` distance floor those stages use does not
    apply here (see backlog/B321.md). It is also the one stage whose whole
    premise is "no App id, nothing to show": local Campy (the common case)
    never sets `external_app_id`, so this returns `None` — not an empty
    section — for every session outside the platform-evaluation scenario
    this card targets. That distinction matters: an absent section key
    means "not applicable"; a present-but-empty one would read as "checked
    and found nothing", which is not true here.

    Fails open (B318): any error — a missing column on an older schema
    that hasn't run migrations yet, a query timeout, a malformed
    `db` — is caught and logged, and the section is simply omitted. This
    must never be the reason a whole recall fails.
    """
    try:
        if not session_id or session_id == "unknown":
            return None

        from campy.brain.thalamus.tools.context_tools import _gateway, app_continuity

        gw = _gateway(db)

        rows = await gw.run("app_continuity.session_external_app_id", session_id=session_id)
        external_app_id = rows[0].get("external_app_id") if rows else None
        if not external_app_id:
            return None

        result = await app_continuity(
            gw, external_app_id=external_app_id, exclude_session=session_id,
        )
        sessions = result.get("sessions") or []
        if not sessions:
            return None

        content = []
        node_ids = []
        for entry in sessions:
            content.append({
                "session_id": entry["session_id"],
                "external_session_id": entry.get("external_session_id"),
                "started_at": entry.get("started_at"),
                "text": _format_continuity_text(entry),
                "decisions": entry["decisions"],
                "constraints": entry["constraints"],
                "lessons": entry["lessons"],
                "plans": entry["plans"],
            })
            node_ids.append(entry["session_id"])

        token_estimate = len(content) * 80

        return BundleSection(
            section_type="app_continuity",
            content=content,
            token_estimate=token_estimate,
            source_node_ids=node_ids,
        )
    except Exception as e:
        _logger.warning("Error in _stage_app_continuity: %s", e)
        return None
