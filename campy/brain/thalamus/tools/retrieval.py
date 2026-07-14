"""Recall and graph-query tool handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.thalamus.tools.explore_graph import (
    _MAX_DEPTH,
    _NODE_TABLES,
    _TRAVERSABLE_RELS,
    explore_graph,
)

from ._shared import (
    DICTIONARY_PATHS,
    _LESSON_INDEX,
    _PROCEDURE_INDEX,
    _apply_fusion_adjustments,
    _clamp,
    _get_pk_for_node_type,
    _logger,
    _rrf_fuse,
    _safe_result_dict,
    find_dictionary,
    get_quest_context,
    ingest_dictionary,
    load_dictionary,
    tables_with,
)

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient



async def reconstruct_timeline(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Reconstruct the temporal sequence of Messages (and Decisions) for a given topic.

    params: {topic, session_id?, max_hops?, include_decisions?}
    Returns: {timeline: [{message: {message_id, text, created_at}, decisions: [{decision_id, text}]}], truncated: bool}
    """
    topic = (params.get("topic") or "").strip()
    if not topic:
        return {"timeline": []}

    session_id = params.get("session_id", "").strip()
    max_hops = int(params.get("max_hops", 20))
    include_decisions = bool(params.get("include_decisions", True))

    try:
        starts = []
        # 1) Messages whose text contains the topic
        if session_id:
            r = db.execute(
                "MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid}) "
                "WHERE lower(m.text_raw) CONTAINS lower($topic) "
                "RETURN m.message_id, m.text_raw, m.created_at "
                "ORDER BY m.created_at ASC",
                {"sid": session_id, "topic": topic}
            )
        else:
            r = db.execute(
                "MATCH (m:Message) WHERE lower(m.text_raw) CONTAINS lower($topic) "
                "RETURN m.message_id, m.text_raw, m.created_at "
                "ORDER BY m.created_at ASC",
                {"topic": topic}
            )
        while r.has_next():
            row = r.get_next()
            starts.append({"message_id": row[0], "text": row[1], "created_at": row[2]})

        # 2) Messages that established Decisions containing the topic
        r2 = db.execute(
            "MATCH (m:Message)-[:ESTABLISHED]->(d:Decision) "
            "WHERE lower(d.text_raw) CONTAINS lower($topic) "
            "RETURN m.message_id, m.text_raw, m.created_at "
            "ORDER BY m.created_at ASC",
            {"topic": topic}
        )
        while r2.has_next():
            row = r2.get_next()
            if not any(s["message_id"] == row[0] for s in starts):
                starts.append({"message_id": row[0], "text": row[1], "created_at": row[2]})

        if not starts:
            return {"timeline": [], "found_starts": 0}

        # Use the earliest matching start
        start = starts[0]
        timeline = []
        curr_id = start["message_id"]

        def _fetch_message(mid: str):
            try:
                rr = db.execute(
                    "MATCH (m:Message {message_id: $mid}) RETURN m.message_id, m.text_raw, m.created_at",
                    {"mid": mid}
                )
                if rr.has_next():
                    rrow = rr.get_next()
                    return {"message_id": rrow[0], "text": rrow[1], "created_at": str(rrow[2])}
            except Exception:
                pass
            return None

        def _fetch_decisions_for_message(mid: str):
            out = []
            try:
                rd = db.execute(
                    "MATCH (m:Message {message_id: $mid})-[:ESTABLISHED]->(d:Decision) "
                    "RETURN d.decision_id, d.text_raw ORDER BY d.created_at ASC",
                    {"mid": mid}
                )
                while rd.has_next():
                    rdd = rd.get_next()
                    out.append({"decision_id": rdd[0], "text": rdd[1]})
            except Exception:
                pass
            return out

        # Append start message
        msg = _fetch_message(curr_id)
        if msg:
            timeline.append({"message": msg, "decisions": _fetch_decisions_for_message(curr_id) if include_decisions else []})

        # Walk FOLLOWED_BY chain up to max_hops
        for _ in range(max_hops):
            try:
                nr = db.execute(
                    "MATCH (m:Message {message_id: $mid})-[:FOLLOWED_BY]->(n:Message) "
                    "RETURN n.message_id, n.text_raw, n.created_at LIMIT 1",
                    {"mid": curr_id}
                )
                if not nr.has_next():
                    break
                nrow = nr.get_next()
                next_id = nrow[0]
                msg = _fetch_message(next_id)
                if not msg:
                    break
                timeline.append({"message": msg, "decisions": _fetch_decisions_for_message(next_id) if include_decisions else []})
                curr_id = next_id
            except Exception:
                break

        truncated = len(timeline) >= max_hops
        return {"timeline": timeline, "truncated": truncated}

    except Exception:
        _logger.exception("reconstruct_timeline failed")
        return {"timeline": [], "error": "internal"}


async def current_truth(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Retrieve relevant memory for a query.
    M5: branch scope adds quest-linked artifacts to the result set.
    B125: Optional include_rationale includes originating message content.

    params: {query, session_id, scope ("branch"|"global"|"both"), limit,
             quest_id?, repo_root?, git_branch?, include_rationale?}
    """
    query      = params.get("query", "")
    session_id = params.get("session_id", "unknown")
    scope      = params.get("scope", "branch")
    limit      = int(params.get("limit", 10))
    explicit_quest_id = params.get("quest_id", "")
    quest_id   = explicit_quest_id
    repo_root  = params.get("repo_root", "")
    git_branch = params.get("git_branch", "main")
    include_rationale = params.get("include_rationale", False)  # B125

    if not query.strip():
        return {"results": [], "quest_context": {}}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Resolve quest_id: prefer explicit, then git hash, then session binding
    if not quest_id and repo_root:
        from campy.brain.hippocampus.quest import compute_quest_id
        quest_id = compute_quest_id(repo_root, git_branch)
    if not quest_id and session_id != "unknown":
        # Resolve via Session → WORKING_ON → MainQuest
        try:
            r = db.execute(
                "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
                "RETURN q.quest_id",
                {"sid": session_id}
            )
            if r.has_next():
                quest_id = r.get_next()[0] or ""
        except Exception:
            pass

    query_vector = emb.embed(query, model_name=embedding_model)

    # Vector search across artifact tables
    # D6 fix: include Concept nodes — they are the majority of extracted entities
    # and most have not been reified to specific artifact types. Without this,
    # most of the graph is invisible to current_truth.
    artifact_tables = [
        (table.name, table.vector_index, table.pk)
        for table in tables_with("retrievable")
        if table.vector_index is not None
    ]

    all_raw_results = []
    per_table_limit = max(limit, 5)

    for table_name, index_name, pk in artifact_tables:
        try:
            rows = db.vector_search(table_name, index_name, query_vector, per_table_limit)
            for row in rows:
                all_raw_results.append((table_name, pk, row))
        except Exception:
            _logger.exception("current_truth vector search failed for table %s", table_name)

    # Episodic exact-match fallback. Vector search alone is not enough for
    # "what did we just say about X?" because raw Message nodes are deliberately
    # low-confidence/low-strength until consolidation. Exact text hits should
    # still surface as recall evidence.
    lexical_message_ids: set[str] = set()
    retrieval_cfg = config.get("retrieval", {}) or {}
    window_days = max(0.0, float(retrieval_cfg.get("lexical_window_days", 14)))
    lexical_limit = max(1, int(retrieval_cfg.get("lexical_limit", max(limit, 5))))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    def _append_lexical_message(node: dict, *, score: float = 0.0) -> None:
        mid = node.get("message_id")
        if not mid:
            return
        lexical_message_ids.add(mid)
        all_raw_results.append((
            "Message",
            "message_id",
            {
                "node": {
                    "message_id": mid,
                    "text_raw": node.get("text_raw", ""),
                    "role": node.get("role", ""),
                    "confidence": node.get("confidence", 0.0) or 0.0,
                    "confidence_low": True if node.get("confidence_low") is None else bool(node.get("confidence_low")),
                    "pathway_strength": node.get("pathway_strength", 0.0) or 0.0,
                    "created_at": node.get("created_at"),
                    "archived": False,
                },
                "score": score,
                "lexical_exact": True,
            },
        ))

    try:
        lexical_rows = []
        has_fts = getattr(db, "has_fts", None)
        fts_search = getattr(db, "fts_search", None)
        if callable(has_fts):
            try:
                if has_fts() is True and callable(fts_search):
                    lexical_rows = fts_search("Message", "message_fts_idx", query, lexical_limit)
            except Exception:
                lexical_rows = []

        if lexical_rows:
            for row in lexical_rows:
                node = _safe_result_dict(row.get("node", {}))
                # B298: superseded auto-memory versions are archived; the FTS
                # index may still return them, so filter here like the vector
                # path does.
                if node.get("archived", False):
                    continue
                _append_lexical_message(node, score=float(row.get("score", 0.0) or 0.0))
        else:
            rr = db.execute(
                "MATCH (m:Message) "
                "WHERE lower(m.text_raw) CONTAINS lower($query) "
                "  AND m.archived = false "
                "  AND m.created_at > timestamp($cutoff) "
                "RETURN m.message_id, m.text_raw, m.role, m.confidence, "
                "m.confidence_low, m.pathway_strength, m.created_at "
                f"ORDER BY m.created_at DESC LIMIT {lexical_limit}",
                {"query": query, "cutoff": cutoff},
            )
            while rr.has_next():
                mid, text, role, conf, conf_low, ps, created_at = rr.get_next()
                _append_lexical_message({
                    "message_id": mid,
                    "text_raw": text,
                    "role": role,
                    "confidence": conf,
                    "confidence_low": conf_low,
                    "pathway_strength": ps,
                    "created_at": created_at,
                })
    except Exception:
        _logger.debug("current_truth lexical message fallback failed", exc_info=True)

    # Batch outcome signal lookup for retrieved nodes
    # We check both the node itself (if it's a Concept) and the parent Concept
    # (if it's a Reified artifact) to capture all outcome signals.
    outcome_map = {}
    node_ids = []
    for table, pk, r in all_raw_results:
        node = r["node"]
        nid = node.get(pk)
        if nid:
            node_ids.append(nid)

    if node_ids:
        try:
            # Query for signals linked directly to a Concept OR to a Concept 
            # that was REIFIED_AS the artifact.
            ro = db.execute(
                """
                UNWIND $ids AS nid
                OPTIONAL MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept {concept_id: nid})
                OPTIONAL MATCH (ps2:PlanStep)-[o2:OUTCOME_SIGNAL]->(c2:Concept)-[:REIFIED_AS]->(a) 
                WHERE (a.decision_id = nid OR a.constraint_id = nid OR a.requirement_id = nid OR a.action_item_id = nid)
                WITH nid, 
                     CASE WHEN o IS NOT NULL THEN o.valence ELSE o2.valence END AS v
                WHERE v IS NOT NULL
                RETURN nid, avg(v), count(v)
                """,
                {"ids": node_ids},
            )
            while ro.has_next():
                nid, avg_v, count = ro.get_next()
                outcome_map[nid] = (avg_v, count)
        except Exception:
            _logger.exception("current_truth batch outcome lookup failed")

    # B91: Warm Frontier (Passive Graph Pre-Activation)
    warm_nodes = {}
    if session_id != "unknown":
        from campy.brain.temporal_lobe.warm_frontier import get_warm_nodes
        try:
            warm_nodes = get_warm_nodes(db, session_id)
        except Exception:
            pass

    all_results = []
    source_lists: dict[str, list[dict]] = {}
    source_seen_ids: dict[str, set[str]] = {}
    for table_name, pk, row in all_raw_results:
        try:
            node = row["node"]
            if node.get("archived", False):
                continue
            node_id = (node.get("concept_id")
                        or node.get("decision_id") or node.get("constraint_id")
                        or node.get("requirement_id") or node.get("action_item_id")
                        or node.get("plan_id") or node.get("procedure_id")
                        or node.get("global_constraint_id")
                        or node.get("global_preference_id")
                        or node.get("lesson_id")
                        or node.get("message_id")
                        or node.get("extract_id")
                        or "unknown")
            text_raw = (
                node.get("text_raw")
                or node.get("goal")  # Plan rows use goal instead of text_raw
                or node.get("description")  # Procedure rows use description
                or ""
            )
            ps = node.get("pathway_strength", 0.0) or 0.0
            conf = node.get("confidence", 0.0) or 0.0
            similarity = row["score"]
            lexical_exact = bool(row.get("lexical_exact"))

            # B91: Warm boost
            activation_score = warm_nodes.get(node_id, 0.0)
            warm_boost = activation_score * 0.25 # Up to +0.25 boost for hot nodes

            outcome_valence = None
            outcome_warning = None
            outcome_boost = 0.0
            reifiable_types = {"Concept", "Decision", "Constraint", "Requirement", "ActionItem"}
            if table_name in reifiable_types and node_id in outcome_map:
                avg_valence, signal_count = outcome_map[node_id]
                if signal_count and avg_valence is not None:
                    outcome_valence = float(avg_valence)
                    outcome_boost = _clamp(outcome_valence * 0.3, -0.3, 0.3)
                    if outcome_valence < -0.1:
                        outcome_warning = (
                            f"This entity was involved in {int(signal_count)} failed or negative-outcome plan steps."
                        )

            # Architecture invariant: vector search finds candidate nodes, but
            # graph memory ranks them by pathway strength and confidence.
            strength = (ps * conf) if (ps > 0.0 and conf > 0.0) else 0.0
            rank = strength * (1.0 + outcome_boost)

            result_row = {
                "node_id":          node_id,
                "node_type":        table_name,
                "text_raw":         text_raw,
                "confidence":       conf,
                "confidence_low":   node.get("confidence_low", True),
                "pathway_strength": ps,
                "similarity":       similarity,
                "activation_score": activation_score, # B91: expose for debugging/tests
                "outcome_valence":  outcome_valence,
                "outcome_warning":  outcome_warning,
                "lexical_exact":     lexical_exact,
                "_rank":            rank,
            }
            if node.get("status") is not None:
                result_row["status"] = node.get("status")
            if node.get("valence") is not None:
                result_row["valence"] = node.get("valence")

            all_results.append(result_row)

            source_name = "lexical" if lexical_exact else f"vector:{table_name}"
            source_lists.setdefault(source_name, [])
            source_seen_ids.setdefault(source_name, set())
            if node_id not in source_seen_ids[source_name]:
                source_lists[source_name].append({
                    "node_id": node_id,
                    "score": similarity,
                    "node_type": table_name,
                    "lexical_exact": lexical_exact,
                })
                source_seen_ids[source_name].add(node_id)
        except Exception:
            _logger.exception("current_truth processing failed for node %s", node_id)


    # B18: Context Window Awareness (Working Memory) imports
    from campy.brain.thalamus.working_memory import (
        get_loaded_node_ids, deduplicate_results, track_loaded,
        update_token_estimate, estimate_tokens, check_context_health,
        get_session_token_state, get_handoff_context
    )

    fused_entries = _rrf_fuse(source_lists, limit=limit)

    # Keep the richest candidate dict per node for output fields.
    result_by_id: dict[str, dict] = {}
    for item in all_results:
        nid = item.get("node_id", "")
        if not nid:
            continue
        prev = result_by_id.get(nid)
        if prev is None or float(item.get("similarity", 0.0) or 0.0) > float(prev.get("similarity", 0.0) or 0.0):
            result_by_id[nid] = item

    adjusted_entries = _apply_fusion_adjustments(fused_entries, result_by_id, outcome_map)
    all_results = [entry["result"] for entry in sorted(adjusted_entries, key=lambda e: e["final"], reverse=True)]

    debug_ranking = bool(params.get("debug_ranking"))
    if debug_ranking:
        for entry in adjusted_entries:
            nid = entry["node_id"]
            result = result_by_id.get(nid)
            if result is None:
                continue
            result["ranking_signals"] = {
                "sources": entry["sources"],
                "rrf": entry["rrf"],
                "final": entry["final"],
                "pathway_multiplier": entry["pathway_multiplier"],
                "valence_multiplier": entry["valence_multiplier"],
                "valence": entry["valence"],
            }

    # B18: Smart deduplication — demote already-loaded nodes
    # MECHANISM (B44 Token Efficiency): This is where working memory saves tokens as a side effect.
    # Before returning results, we check which nodes are already in this session's context window
    # (via LOADED edges). Nodes that are already visible to the LLM are demoted in ranking
    # (scored at 30% of original rank) so that fresh, unseen nodes rank higher.
    #
    # Token savings: In a long conversation referencing the same decision multiple times,
    # baseline (no dedup) re-injects the same 10 nodes = 2,400 tokens each time (7,200 total).
    # With dedup: Turn 2 injects 0-3 new nodes = 600 tokens; Turn 3 = 200 tokens.
    # Result: 56% token reduction (7,200 → 3,200) over 3 turns.
    #
    # This reduction is NOT the goal — it's a consequence of tracking working memory correctly.
    # The primary goal is decision quality: we demote, not exclude, so important repeated
    # context can still surface if its demoted score ranks high enough.
    if session_id != "unknown":
        try:
            loaded_ids = get_loaded_node_ids(db, session_id)
            if loaded_ids:
                all_results = deduplicate_results(all_results, loaded_ids)
        except Exception:
            _logger.debug("current_truth dedup failed for session %s", session_id)

    for r in all_results:
        if "_rank" in r:
            del r["_rank"]

    # M5: include quest context for branch scope
    quest_ctx = {}
    if quest_id and scope in ("branch", "both"):
        quest_ctx = get_quest_context(db, quest_id, limit=5)

    final_results = all_results[:limit]

    # B125: Add originating message rationale if requested
    if include_rationale and final_results:
        for result in final_results:
            try:
                # Try to find the originating message via ESTABLISHED_IN relationship
                node_id = result.get("node_id")
                node_type = result.get("node_type", "")
                if node_id and node_type:
                    # Simple 1-hop traversal to find originating message
                    query = f"MATCH (n:{node_type})-[r:ESTABLISHED_IN]->(m:Message) WHERE n.{_get_pk_for_node_type(node_type)} = $id RETURN m.content LIMIT 1"
                    try:
                        r = db.execute(query, {"id": node_id})
                        if r.has_next():
                            message_content = r.get_next()[0]
                            if message_content:
                                # Truncate to 200 chars as per B125 spec
                                result["originating_rationale"] = str(message_content)[:200]
                    except Exception:
                        pass
            except Exception:
                pass

    # B18: Add handoff candidates if this is a new session
    # We do this BEFORE track_loaded so loaded_nodes is still 0 for fresh sessions
    handoff_from_prior = None
    if quest_id and session_id != "unknown":
        try:
            state = get_session_token_state(db, session_id)
            if state["loaded_nodes"] == 0:
                # Fresh session — include handoff context
                handoff_from_prior = get_handoff_context(db, quest_id, session_id)
        except Exception:
            pass

    # B18: Track what was loaded into this session
    if session_id != "unknown" and final_results:
        try:
            await track_loaded(db, session_id, final_results, source="current_truth")
            # Update token estimate for all returned content. track_loaded()
            # intentionally skips raw Message / DocumentExtract nodes, but if
            # they were returned, their text still consumed context window.
            injected_tokens = sum(estimate_tokens(r.get("text_raw", "")) for r in final_results)
            await update_token_estimate(db, session_id, injected_tokens)
        except Exception:
            _logger.debug("current_truth load tracking failed for session %s", session_id)

    # B18: Add bloat warning if applicable
    bloat_warning = None
    if session_id != "unknown":
        try:
            bloat_warning = check_context_health(db, session_id)
        except Exception:
            pass

    response = {"results": final_results, "quest_context": quest_ctx}
    if bloat_warning:
        response["bloat_warning"] = bloat_warning
    if handoff_from_prior:
        response["handoff_from_prior_session"] = handoff_from_prior

    # B15: Deep-link panel_url — let the LLM surface a "View in Mission Control" link
    mc_base = (config.get("mission_control", {}) or {}).get("base_url", "http://127.0.0.1:7800")
    
    # Inject memory_link for each node
    for r in final_results:
        r["memory_link"] = f"{mc_base}/memory/node/{r['node_id']}"

    if mc_base:
        # Keep panel_url stable for chat deep-link handoff consumers.
        response["panel_url"] = f"{mc_base}/memory"
        if explicit_quest_id:
            response["panel_url"] = f"{mc_base}/board"
        elif session_id and session_id != "unknown":
            response["panel_url"] = f"{mc_base}/memory?context={session_id}"

    return response


async def diff_since(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return nodes created or modified since a given ISO timestamp.
    Useful for synchronizing adapters after a gap.

    params: {since_iso, quest_id?, limit}
    Returns {decisions, constraints, requirements, action_items, since_iso}.
    """
    since_iso = params.get("since_iso", "")
    quest_id  = params.get("quest_id", "")
    limit     = int(params.get("limit", 20))

    if not since_iso:
        return {"error": "since_iso is required"}

    result = {"since_iso": since_iso, "decisions": [], "constraints": [],
              "requirements": [], "action_items": []}

    table_map = [
        ("Decision",     "decision_id",     "decisions"),
        ("Constraint",   "constraint_id",   "constraints"),
        ("Requirement",  "requirement_id",  "requirements"),
        ("ActionItem",   "action_item_id",  "action_items"),
    ]

    for label, pk, key in table_map:
        try:
            r = db.execute(
                f"""
                MATCH (a:{label})
                WHERE a.archived = false AND a.created_at > $since
                RETURN a.{pk}, a.text_raw, a.confidence, a.confidence_low,
                       a.pathway_strength, a.created_at
                ORDER BY a.created_at DESC
                LIMIT $limit
                """,
                {"since": since_iso, "limit": limit}
            )
            while r.has_next():
                row = r.get_next()
                result[key].append({
                    "node_id":          row[0],
                    "text_raw":         row[1],
                    "confidence":       row[2],
                    "confidence_low":   row[3],
                    "pathway_strength": row[4],
                    "created_at":       str(row[5]),
                })
        except Exception:
            pass

    return result


async def get_knowledge_gaps(params: dict, db: KuzuClient, config: dict) -> dict:
    """B193: Return active KnowledgeGaps for proactive metacognition."""
    limit = int(params.get("limit", 10))
    unresolved_only = bool(params.get("unresolved_only", True))
    min_severity = float(params.get("min_severity", 0.0))

    gaps: list[dict] = []
    try:
        if unresolved_only:
            r = db.execute(
                "MATCH (g:KnowledgeGap) WHERE g.resolved = false AND g.severity >= $min "
                "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
                "ORDER BY g.severity DESC LIMIT $lim",
                {"min": min_severity, "lim": limit},
            )
        else:
            r = db.execute(
                "MATCH (g:KnowledgeGap) WHERE g.severity >= $min "
                "RETURN g.gap_id, g.domain, g.gap_type, g.description, g.severity, g.message_count, g.lesson_count, g.created_at "
                "ORDER BY g.severity DESC LIMIT $lim",
                {"min": min_severity, "lim": limit},
            )

        while r.has_next():
            row = r.get_next()
            gaps.append({
                "gap_id": row[0],
                "domain": row[1],
                "gap_type": row[2],
                "description": row[3],
                "severity": float(row[4] or 0.0),
                "message_count": int(row[5] or 0),
                "lesson_count": int(row[6] or 0),
                "created_at": str(row[7]) if row[7] is not None else None,
            })
    except Exception:
        _logger.exception("get_knowledge_gaps failed")

    return {"gaps": gaps}


async def get_open_loops(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return soft-lock Concept nodes (confidence_low=true, not archived).
    These are candidates awaiting UI confirmation or additional context.

    params: {quest_id?, limit}
    Returns {open_loops: [{concept_id, text_raw, gist_class, confidence}]}
    """
    limit    = int(params.get("limit", 20))
    loops    = []

    try:
        r = db.execute(
            """
            MATCH (c:Concept {confidence_low: true, archived: false})
            RETURN c.concept_id, c.text_raw, c.gist_class, c.schema_org_type,
                   c.confidence, c.pathway_strength, c.created_at
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
            {"limit": limit}
        )
        while r.has_next():
            row = r.get_next()
            loops.append({
                "concept_id":       row[0],
                "text_raw":         row[1],
                "gist_class":       row[2],
                "schema_org_type":  row[3],
                "confidence":       row[4],
                "pathway_strength": row[5],
                "created_at":       str(row[6]),
            })
    except Exception:
        pass

    return {"open_loops": loops}


async def reload_domain_dictionary(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Reload the domain dictionary from disk and ingest new entities/altLabels.

    params: {workspace_root?: string}
    """
    workspace_root = params.get("workspace_root", ".")
    try:
        dict_path = find_dictionary(workspace_root)
        if not dict_path:
            return {"error": "No domain_dictionary.yaml found", "searched": DICTIONARY_PATHS}

        entities = load_dictionary(dict_path)
        if not entities:
            return {"error": "Dictionary is empty or invalid"}

        now = datetime.now(timezone.utc).isoformat()
        result = await ingest_dictionary(entities, db, now)
        return {"status": "ok", "path": str(dict_path), **result}
    except Exception:
        _logger.exception("reload_domain_dictionary failed")
        return {"error": "internal error"}


async def analogical_search(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Cross-quest semantic search (M8).
    Finds similar decisions, constraints, and requirements from ANY historical
    MainQuest — not just the current branch.

    params: {query, current_quest_id?, limit, min_similarity?}
    Returns {results, query, cross_quest, searched_tables}.
    """
    from campy.brain.thalamus.analogical import analogical_search as _search
    return await _search(params, db, config)


async def context_status(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Check the health of the current context window.

    params: {session_id}
    Returns: {token_estimate, token_limit, utilization, loaded_nodes,
              bloat_warning, handoff_available, handoff_nodes}
    """
    session_id = params.get("session_id", "").strip()
    if not session_id:
        return {"error": "session_id is required"}

    from campy.brain.thalamus.working_memory import (
        get_session_token_state, check_context_health, get_handoff_context
    )

    state = get_session_token_state(db, session_id)
    warning = check_context_health(db, session_id)

    # Check for handoff availability
    quest_id = ""
    try:
        r = db.execute(
            "MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest) "
            "RETURN q.quest_id",
            {"sid": session_id}
        )
        if r.has_next():
            quest_id = r.get_next()[0] or ""
    except Exception:
        pass

    handoff_nodes = 0
    if quest_id:
        handoff = get_handoff_context(db, quest_id, session_id)
        handoff_nodes = len(handoff)

    return {
        "token_estimate": state["estimated_tokens"],
        "token_limit": state["token_limit"],
        "utilization": round(state["utilization"], 3),
        "loaded_nodes": state["loaded_nodes"],
        "message_count": state["message_count"],
        "tokens_saved_by_dedup": state.get("dedup_tokens_saved", 0),
        "injection_count": state.get("injection_count", 0),
        "bloat_warning": warning,
        "handoff_available": handoff_nodes > 0,
        "handoff_nodes": handoff_nodes,
    }
