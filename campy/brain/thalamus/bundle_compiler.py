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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_logger = logging.getLogger(__name__)


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
            cypher = f"""
                MATCH (n:{label})
                WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30
                RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence
                LIMIT $limit
            """
            result = db.execute(cypher, {"query_embedding": query_embedding, "limit": limit})
            while result.has_next():
                rows.append(result.get_next())

        rows = rows[:limit]

        content = []
        node_ids = []
        for text, node_type, confidence in rows:
            content.append({
                "text": text,
                "type": node_type,
                "confidence": confidence if confidence is not None else 0.5,
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
            cypher = f"""
                MATCH (n:{label})
                WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.40
                RETURN n.text_raw as text, label(n) as node_type,
                       n.pathway_strength as pathway_strength, n.confidence as confidence,
                       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist
                ORDER BY dist ASC
                LIMIT $limit
            """
            result = db.execute(cypher, {"query_embedding": query_embedding, "limit": limit})
            while result.has_next():
                rows.append(result.get_next())

        rows.sort(key=lambda row: row[4])
        rows = rows[:limit]

        content = []
        node_ids = []
        for text, node_type, pathway_strength, confidence, _dist in rows:
            content.append({
                "text": text if text is not None else "",
                "type": node_type if node_type is not None else "Unknown",
                "pathway_strength": pathway_strength if pathway_strength is not None else 0.5,
                "confidence": confidence if confidence is not None else 0.5,
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


async def _stage_plans(db, query: str, config: dict, tier_config: dict) -> Optional[BundleSection]:
    """
    Stage 2: Retrieve plan lane context using the same ranking as recall_plans.

    PlanStep is not separately retrievable here; steps are carried inline with
    parent Plan records to preserve execution context.
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


async def _stage_graph_structure(
    db, query: str, config: dict, tier_config: dict, existing_sources: list[str]
) -> Optional[BundleSection]:
    """
    Stage 3: Extract graph structure (relationships) from top semantic results.

    Returns: structured connections like "Decision X → REQUIRES → Concept Y"
    """
    try:
        # For now, return minimal structure
        # In production, would traverse 1-2 hops from semantic result nodes
        return BundleSection(
            section_type="graph",
            content=[],  # Placeholder
            token_estimate=0,
            source_node_ids=[],
        )
    except Exception as e:
        print(f"Error in _stage_graph_structure: {e}")
        return None


async def _stage_tabular_data(
    db, query: str, config: dict, tier_config: dict, existing_sources: list[str], remaining_budget: int
) -> Optional[BundleSection]:
    """
    Stage 4: Include tabular data if semantic results link to Dataset nodes.

    Returns schema summaries and sample rows if within budget.
    """
    try:
        # Check if any semantic results have DESCRIBED_BY_DATASET edges
        # If so, call tabular_store.get_table_summary() and include
        return BundleSection(
            section_type="tabular",
            content=[],  # Placeholder
            token_estimate=0,
            source_node_ids=[],
        )
    except Exception as e:
        print(f"Error in _stage_tabular_data: {e}")
        return None


async def _stage_summaries(
    db, query: str, config: dict, existing_sources: list[str], remaining_budget: int
) -> Optional[BundleSection]:
    """
    Stage 5: Include wiki summaries or LLM-generated summaries of top results.
    """
    try:
        # Check if wiki projection has pages for relevant entities
        # If yes, include rendered summary text
        return BundleSection(
            section_type="summary",
            content=[],  # Placeholder
            token_estimate=0,
            source_node_ids=[],
        )
    except Exception as e:
        print(f"Error in _stage_summaries: {e}")
        return None
