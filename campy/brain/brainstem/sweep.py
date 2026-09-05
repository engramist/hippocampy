"""
mcp_engine/sweep.py — Background Sweep
  Synaptic Pruning (H1) + Hebbian Trigger 2 (H2)

Named IP Claims implemented here:
  - Synaptic Pruning: Ebbinghaus Forgetting Curve decay + archive mechanic
    Every sweep interval, each active node's pathway_strength decays by
    decay_rate ^ interval_days. Nodes below archive_threshold are archived
    (never deleted — audit trail preserved).
  - Resurrection: archived nodes re-activated when a similar active node
    is found above resurrection_threshold. Strength reset to threshold value.
  - Hebbian Trigger 2: CO_OCCURS_WITH count threshold → LLM auto-promotion.
    High-count co-occurrence pairs are named by the LLM and written as
    semantic relationship edges with inferred_by="LLM".

Called by BrainDaemon._background_sweep() every sweep_interval_seconds.
All operations use short write-lock windows — one node at a time, one table
at a time. Never holds the write lock for bulk operations.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
import asyncio

_logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING, Optional

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


if TYPE_CHECKING:
    from campy.brain.llm.provider import LLMClient

from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_decay
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.table_registry import tables_with
from campy.brain.thalamus.wiki_projection import export_wiki_projection

# ---------------------------------------------------------------------------
# Sweep table registry
# (table_name, pk_col, decay_config_key, index_name)
# ---------------------------------------------------------------------------

_CAMEL_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _config_key(table_name: str) -> str:
    return _CAMEL_SPLIT_RE.sub("_", table_name).lower()


SWEEP_TABLES = [
    (table.name, table.pk, _config_key(table.name), table.vector_index)
    for table in tables_with("sweepable")
    if table.vector_index is not None
]

# SCAN BUDGET NOTE (B284): sweep-time full-table scans (archived=false filters,
# count(n)) are accepted. Sweeps are background, low-frequency maintenance and
# Kuzu 0.11.x has no secondary property indexes. Hot-path scans are not
# accepted; retrieval.lexical_window_days bounds the episodic fallback instead.

# ---------------------------------------------------------------------------
# B282: batched writes — the global write lock makes every execute_write a
# serialization point, so per-row sweep writes contend with live GCL writes.
# ---------------------------------------------------------------------------

_BATCH_SIZE = 500


async def _batch_write(db, query_name: str, items: list, param_key: str = "ids") -> tuple[int, int]:
    """Execute an UNWIND-based write in chunks of _BATCH_SIZE via GraphGateway named query.

    `query_name` must consume the parameter named `param_key` via UNWIND.
    Returns (submitted_count, errored_chunk_item_count). Errors are counted
    per chunk — a failed chunk counts all its items as errored.
    """
    submitted = errored = 0
    for i in range(0, len(items), _BATCH_SIZE):
        chunk = items[i:i + _BATCH_SIZE]
        try:
            await _gateway(db).run(query_name, **{param_key: chunk})
            submitted += len(chunk)
        except Exception:
            _logger.exception("[Sweep] batch write failed (%d items)", len(chunk))
            errored += len(chunk)
    return submitted, errored


# Named relationship types eligible for Hebbian auto-promotion
_NAMED_REL_TYPES = frozenset([
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
])

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_sweep(db, config: dict, llm_client: Optional[object]) -> dict:
    """
    Run one full background sweep cycle. Returns a summary dict.
    Errors in individual steps are logged and swallowed — one bad table
    never kills the entire sweep.

    Args:
        db: KuzuClient instance (write access)
        config: full campy.toml config dict
        llm_client: LLMClient or None — Hebbian Trigger 2 skipped if None
    """
    from campy.brain.brainstem.phase import set_phase
    set_phase("sweeping")
    try:
        pruning_cfg         = config.get("pruning", {})
        sweep_interval      = pruning_cfg.get("sweep_interval_seconds", 300)
        archive_threshold   = float(pruning_cfg.get("archive_threshold", 0.10))
        resurrection_thresh = float(pruning_cfg.get("resurrection_threshold", 0.85))
        resurrection_candidates_per_sweep = int(
            pruning_cfg.get("resurrection_candidates_per_sweep", _DEFAULT_RESURRECTION_CANDIDATES_PER_SWEEP)
        )
        # B279: vector_search now returns true cosine similarity, so this
        # config value is interpreted directly as a cosine threshold.
        decay_rates         = pruning_cfg.get("decay_rate", {})

        # Express sweep interval as a fraction of a day — decay applied incrementally
        # each run rather than re-computing total decay from node creation date.
        interval_days = sweep_interval / 86400.0

        summary = {
            "decayed": 0, "archived": 0, "resurrected": 0,
            "promoted": 0, "errors": 0,
            "retrospective_plans": 0,
            "patterns_discovered": 0,    # Phase 4
            "pattern_candidates": 0,     # Phase 4
            "frustration_clusters": 0,   # Basal Ganglia: avoidance Procedures
            "maturity_updates": 0,       # Basal Ganglia: maturity lifecycle
            "sweep_at": datetime.now(timezone.utc).isoformat(),
        }

        # Step 1: Decay pathway_strength + archive below threshold
        d, a, e = await _decay_and_archive(db, decay_rates, interval_days, archive_threshold)
        summary["decayed"]  += d
        summary["archived"] += a
        summary["errors"]   += e

        # Step 1.2: B283 degree hotspot report + session cache edge pruning
        try:
            summary["degree_hotspots"] = await _report_degree_hotspots(db, config)
        except Exception:
            _logger.warning("[Sweep] degree hotspot report failed", exc_info=True)
            summary["degree_hotspots"] = []
            summary["errors"] += 1
        try:
            sp, e = await _prune_session_edges(db, config)
            summary["sessions_pruned"] = sp
            summary["errors"] += e
        except Exception:
            _logger.warning("[Sweep] session edge pruning failed", exc_info=True)
            summary["sessions_pruned"] = 0
            summary["errors"] += 1

        # Step 1.5: B74 valence-aware decay adjustment
        v, e = await _apply_valence_decay(db)
        summary["valence_adjusted"] = v
        summary["errors"] += e

        # Step 2: Resurrect archived nodes with active graph similarity
        r, e = await _resurrect_archived(db, resurrection_thresh, resurrection_candidates_per_sweep)
        summary["resurrected"] += r
        summary["errors"]      += e

        # Step 2.5: B285 index hygiene metrics + retrieval headroom telemetry.
        # NOTE: Step 0 capability probe showed that true index hygiene requires
        # row movement (delete from indexed table), which is an architecture
        # decision outside this card's downgraded scope.
        try:
            hygiene_report = await _index_hygiene(db, config)
            summary["index_hygiene"] = hygiene_report
            try:
                from campy.brain.temporal_lobe.loop.step5_retrieval import set_archived_ratios
                set_archived_ratios(hygiene_report)
            except Exception:
                _logger.debug("[IndexHygiene] could not update step5 ratio cache", exc_info=True)
        except Exception:
            summary["errors"] += 1

        # Step 3: Hebbian Trigger 2 — only when LLM is available
        if llm_client is not None:
            hebbian_cfg = config.get("hebbian", {})
            threshold   = int(hebbian_cfg.get("co_occurrence_threshold", 10))
            p, e = await _hebbian_promote(db, llm_client, threshold)
            summary["promoted"] += p
            summary["errors"]   += e

        # Step 3.5: Dream consolidation (synthesis) — only when LLM is available
        if llm_client is not None:
            d, e = await _dream_consolidation(db, config, llm_client)
            summary["synthesized"] = d
            summary["errors"] += e

        # Step 3.75: Consistency audit (B196) — LLM-assisted pairwise lesson contradiction detection
        try:
            a, e = await _audit_consistency(db, config, llm_client)
            summary["consistency_audits"] = a
            summary["errors"] += e
        except Exception:
            summary["errors"] += 1

        # Step 4: Recompute GistClass centroids from accumulated System 2 examples (M4)
        c, e = await _recompute_centroids(db)
        summary["centroids_updated"]  = c
        summary["errors"]            += e

        # Step 5: B68 Layer C retrospective plan inference
        rp, e = await _infer_retrospective_plans(db, config)
        summary["retrospective_plans"] += rp
        summary["errors"] += e

        # Step 6: Knowledge gap detection (B193)
        g, e = await _detect_knowledge_gaps(db, config)
        summary["gaps_detected"] = g
        summary["errors"] += e

        # Step 7: Wiki Projection (B222)
        try:
            wiki_summary = await export_wiki_projection(db, config)
            summary["wiki_projection"] = wiki_summary
        except Exception:
            summary["errors"] += 1

        # Step 7.5: Offline pattern discovery (Phase 4 — Anticipatory Engine)
        try:
            from campy.brain.brainstem.sweep_patterns import discover_patterns
            pat_summary = await discover_patterns(db, config, llm_client)
            summary["patterns_discovered"] = pat_summary.get("triggers_written", 0)
            summary["pattern_candidates"] = pat_summary.get("candidates_found", 0)
            summary["errors"] += pat_summary.get("errors", 0)
        except Exception:
            _logger.warning("[Sweep] Pattern discovery failed", exc_info=True)
            summary["errors"] += 1

        return summary
    finally:
        set_phase("idle")


async def _infer_retrospective_plans(db, config: dict) -> tuple[int, int]:
    """
    Infer plan structure from sequential ActionItems when no explicit plan exists.
    Weak fallback path used by background sweep.
    """
    inferred = errors = 0
    now = datetime.now(timezone.utc).isoformat()
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    try:
        rows = _gateway(db).run_sync("sweep.get_retrospective_action_items")
    except Exception:
        return 0, 1

    by_session: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        if isinstance(row, dict):
            sid = row.get("s.session_id") or ""
            aid = row.get("a.action_item_id") or ""
            txt = (row.get("a.text_raw") or "").strip()
        else:
            sid = row[0] or ""
            aid = row[1] or ""
            txt = (row[2] or "").strip()
        if not sid or not aid or not txt:
            continue
        by_session.setdefault(sid, []).append((aid, txt))

    for session_id, items in by_session.items():
        if len(items) < 3:
            continue

        # Use the first 5 sequential ActionItems as retrospective steps.
        seq = items[:5]
        steps = [txt for _, txt in seq]
        goal = steps[0][:240]
        goal_vec = emb.embed(goal, model_name=embedding_model)

        # Dedup: skip if a very similar plan already exists.
        skip = False
        thresh = config.get("plan_dedup_threshold", 0.90)
        try:
            neighbors = db.vector_search("Plan", "plan_emb_idx", goal_vec, 8)
            for n in neighbors:
                score = float(n.get("score", 0.0) or 0.0)
                if score > thresh:
                    _logger.info("Plan dedup: similarity=%.3f, threshold=%.2f, action=reject", score, thresh)
                    skip = True
                    break
        except Exception:
            pass
        if skip:
            continue

        try:
            plan_id = str(uuid.uuid4())
            await _gateway(db).run(
                "sweep.create_retrospective_plan",
                plan_id=plan_id,
                goal=goal,
                embedding=goal_vec,
                embedding_model=embedding_model,
                embedding_dim=len(goal_vec),
                step_count=len(steps),
                created_at=now,
                completed_at=now,
            )

            await _gateway(db).run(
                "sweep.link_plan_session",
                pid=plan_id,
                sid=session_id,
            )

            step_ids: list[str] = []
            for idx, (_, text_raw) in enumerate(seq, start=1):
                step_id = str(uuid.uuid4())
                step_ids.append(step_id)
                step_vec = emb.embed(text_raw, model_name=embedding_model)
                await _gateway(db).run(
                    "sweep.create_plan_step",
                    step_id=step_id,
                    step_number=idx,
                    description=text_raw,
                    embedding=step_vec,
                    embedding_model=embedding_model,
                    embedding_dim=len(step_vec),
                    created_at=now,
                    completed_at=now,
                )
                await _gateway(db).run(
                    "sweep.link_step_of_plan",
                    sid=step_id,
                    pid=plan_id,
                )

            for a, b in zip(step_ids, step_ids[1:]):
                await _gateway(db).run(
                    "sweep.link_next_step",
                    a=a,
                    b=b,
                )

            inferred += 1
        except Exception:
            errors += 1

    return inferred, errors


async def _detect_knowledge_gaps(db, config: dict) -> tuple[int, int]:
    """
    Detect knowledge gaps across domains and archetypes.

    Heuristics implemented:
      - Domain with < 2 Lessons but > 5 Messages mentioning it => missing_lessons
      - Archetype (Plan.strategy) with solved_count > 0 but lesson_count == 0 => no_lessons_for_archetype
      - Domain where avg Lesson confidence < 0.5 => low_quality

    Creates or updates `KnowledgeGap` nodes and links them via IDENTIFIED_GAP_IN.
    Returns (n_detected, n_errors).
    """
    detected = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    # 1) Aggregate lesson counts and average confidence by domain
    lesson_map: dict[str, int] = {}
    avg_conf_map: dict[str, float] = {}
    try:
        rows = _gateway(db).run_sync("sweep.count_lessons_by_domain")
        for row in rows:
            dom = (row.get("l.domain") if isinstance(row, dict) else row[0]) or ""
            lcount = (row.get("lesson_count") if isinstance(row, dict) else row[1]) or 0
            avg_c = (row.get("avg_conf") if isinstance(row, dict) else row[2]) or 0.0
            lesson_map[dom] = int(lcount)
            avg_conf_map[dom] = float(avg_c)
    except Exception:
        return 0, 1

    # 2) Count messages that reference Concepts by gist_class
    msg_map: dict[str, int] = {}
    try:
        rows_m = _gateway(db).run_sync("sweep.count_messages_by_domain")
        for row in rows_m:
            gist = (row.get("c.gist_class") if isinstance(row, dict) else row[0]) or ""
            mcount = (row.get("msg_count") if isinstance(row, dict) else row[1]) or 0
            msg_map[gist] = int(mcount)
    except Exception:
        # Non-fatal: continue with empty msg_map
        msg_map = {}

    # 3) Completed plan strategies (archetype proxy)
    plan_map: dict[str, int] = {}
    try:
        rows_p = _gateway(db).run_sync("sweep.count_solved_plans")
        for row in rows_p:
            strat = (row.get("p.strategy") if isinstance(row, dict) else row[0]) or ""
            scount = (row.get("solved_count") if isinstance(row, dict) else row[1]) or 0
            plan_map[strat] = int(scount)
    except Exception:
        plan_map = {}

    # Candidate domains to evaluate
    candidates = set(list(lesson_map.keys()) + list(msg_map.keys()) + list(plan_map.keys()))

    for dom in candidates:
        lesson_count = lesson_map.get(dom, 0)
        msg_count = msg_map.get(dom, 0)
        plan_count = plan_map.get(dom, 0)
        avg_conf = avg_conf_map.get(dom, 0.0)

        gap_type = None
        if lesson_count < 2 and msg_count > 5:
            gap_type = "missing_lessons"
        elif plan_count > 0 and lesson_count == 0:
            gap_type = "no_lessons_for_archetype"
        elif lesson_count > 0 and avg_conf < 0.5:
            gap_type = "low_quality"

        # If no gap detected, consider resolving existing unresolved gap
        if not gap_type:
            try:
                rr = _gateway(db).run_sync("sweep.find_unresolved_gap", d=dom)
                if rr:
                    gid = rr[0].get("g.gap_id") if isinstance(rr[0], dict) else rr[0][0]
                    # Resolve if criteria now satisfied
                    if lesson_count >= 2 or (lesson_count > 0 and avg_conf >= 0.5):
                        try:
                            await _gateway(db).run("sweep.resolve_gap", gid=gid, now=now)
                            detected += 1
                        except Exception:
                            errors += 1
                continue
            except Exception:
                errors += 1
                continue

        # Compute severity: message_count / max(1, lesson_count) scaled
        try:
            if lesson_count == 0:
                severity = min(1.0, float(msg_count) / 10.0)
            else:
                severity = min(1.0, (float(msg_count) / float(max(1, lesson_count))) / 10.0)
            # Boost severity for archetype-without-lessons
            if gap_type == "no_lessons_for_archetype" and severity < 0.5:
                severity = 0.6

            desc = f"Detected knowledge gap ({gap_type}) for domain '{dom}': {msg_count} messages, {lesson_count} lessons"

            # Create or update KnowledgeGap node
            ex = _gateway(db).run_sync("sweep.find_unresolved_gap", d=dom)
            if ex:
                gid = ex[0].get("g.gap_id") if isinstance(ex[0], dict) else ex[0][0]
                await _gateway(db).run(
                    "sweep.update_gap_severity",
                    gid=gid, gap_type=gap_type, desc=desc, severity=severity,
                    msg_count=msg_count, lesson_count=lesson_count,
                )
            else:
                gid = str(uuid.uuid4())
                await _gateway(db).run(
                    "sweep.create_knowledge_gap",
                    gid=gid, domain=dom, gap_type=gap_type, desc=desc, severity=severity,
                    msg_count=msg_count, lesson_count=lesson_count, now=now,
                )

            # Try to link to a Concept (gist_class) or a MainQuest
            try:
                cr = _gateway(db).run_sync("sweep.find_concept_by_domain", domain=dom)
                if cr:
                    cid = cr[0].get("c.concept_id") if isinstance(cr[0], dict) else cr[0][0]
                    await _gateway(db).run("sweep.link_gap_concept", gid=gid, cid=cid)
                else:
                    qr = _gateway(db).run_sync("sweep.find_quest_by_domain", domain=dom)
                    if qr:
                        qid = qr[0].get("q.quest_id") if isinstance(qr[0], dict) else qr[0][0]
                        await _gateway(db).run("sweep.link_gap_quest", gid=gid, qid=qid)
            except Exception:
                pass

            detected += 1
        except Exception:
            errors += 1

    return detected, errors


# ---------------------------------------------------------------------------
# Step 1: Decay + Archive
# ---------------------------------------------------------------------------

async def _decay_and_archive(
    db,
    decay_rates: dict,
    interval_days: float,
    archive_threshold: float,
) -> tuple[int, int, int]:
    """
    Apply one sweep interval of pathway_strength decay to every active node
    in each artifact table. Archive nodes that fall below archive_threshold.

    Decay formula (Ebbinghaus Forgetting Curve, incremental per sweep run):
        new_strength = current * decay_rate ^ interval_days

    Returns (decayed_count, archived_count, error_count).
    """
    decayed = archived = errors = 0

    for table, pk_col, config_key, _ in SWEEP_TABLES:
        decay_rate = float(decay_rates.get(config_key, 0.99))
        decay_factor = decay_rate ** interval_days

        try:
            # Atomic decay: multiply in-place to avoid TOCTOU race (SW1 fix).
            await _gateway(db).run(f"sweep.decay_pathway_{table.lower()}", factor=decay_factor)

            # B282: one read serves both the decayed count and the archive candidate list
            rows = _gateway(db).run_sync(f"sweep.get_active_pathway_{table.lower()}")

            to_archive = []
            for row in rows:
                if isinstance(row, dict):
                    vals = list(row.values())
                    nid, pstrength = vals[0], vals[1]
                else:
                    nid, pstrength = row[0], row[1]
                decayed += 1
                if pstrength is not None and pstrength < archive_threshold:
                    to_archive.append(nid)

            if to_archive:
                ok, bad = await _batch_write(
                    db,
                    f"sweep.unwind_archive_{table.lower()}",
                    to_archive,
                )
                archived += ok
                errors += 1 if bad else 0

        except Exception:
            errors += 1

    return decayed, archived, errors


async def _index_hygiene(db, config: dict) -> dict:
    """Compute per-table archived ratios for HNSW-indexed sweep tables.

    Rebuild is intentionally disabled in this downgraded B285 path. The Step 0
    probe confirmed drop/create table support, but also confirmed indexed embedding
    updates are disallowed; effective archived-vector removal requires row
    movement that is deferred to a dedicated architecture decision.
    """
    threshold = float(config.get("sweep", {}).get("index_rebuild_archived_ratio", 0.5))
    enabled = bool(config.get("sweep", {}).get("index_rebuild_enabled", True))
    report: dict[str, dict] = {}

    for table, _, _, _index_name in SWEEP_TABLES:
        counts = {True: 0, False: 0}
        total = 0
        try:
            res_rows = _gateway(db).run_sync(f"sweep.index_hygiene_{table.lower()}")
            for row in res_rows:
                if isinstance(row, dict):
                    archived = row.get("archived")
                    count = row.get("c")
                else:
                    archived, count = row[0], row[1]
                c = int(count or 0)
                total += c
                counts[bool(archived)] = counts.get(bool(archived), 0) + c
        except Exception:
            _logger.debug("[IndexHygiene] failed ratio query for %s", table, exc_info=True)
            report[table] = {
                "archived_ratio": 0.0,
                "total": 0,
                "threshold": threshold,
                "rebuild_enabled": enabled,
                "rebuilt": False,
            }
            continue

        archived_count = counts.get(True, 0)
        ratio = (archived_count / total) if total > 0 else 0.0
        report[table] = {
            "archived_ratio": ratio,
            "total": total,
            "threshold": threshold,
            "rebuild_enabled": enabled,
            "rebuilt": False,
        }

        if enabled and ratio >= threshold:
            # Rebuild is intentionally disabled (see module docstring above) -
            # but staleness must not accumulate silently. Log it so it's
            # visible to an operator even though no action is taken.
            _logger.warning(
                "[IndexHygiene] %s archived_ratio=%.2f >= threshold=%.2f — "
                "rebuild is disabled by design (Path B archive-move not yet "
                "implemented, see backlog/B285.md); index staleness for this "
                "table is accumulating",
                table, ratio, threshold,
            )

    return report


# ---------------------------------------------------------------------------
# B283: Supernode monitoring + session edge pruning
# ---------------------------------------------------------------------------

# (rel_table, side) — measure the endpoint that concentrates edges.
_DEGREE_REPORT_RELS = [
    ("CO_OCCURS_WITH", "both"),
    ("ESTABLISHED_IN", "to"),    # Session side
    ("LOADED",         "from"),  # Session side
    ("WARM_NODE",      "from"),
    ("BELONGS_TO",     "to"),    # MainQuest side
    ("WORKING_ON",     "to"),
]

# Session-scoped cache rel tables eligible for TTL pruning. These are
# rebuilt on session activity — deleting them never loses durable memory.
_SESSION_CACHE_RELS = ("LOADED", "WARM_NODE")


def _node_identity(node: dict) -> tuple[str, str]:
    """Best-effort (table, pk_value) from a Kuzu node property dict."""
    table = str(node.get("_label", "") or "")
    for key, value in node.items():
        if key.endswith("_id") and value:
            return table, str(value)
    return table, str(node.get("name", "") or "")


async def _report_degree_hotspots(db, config: dict) -> list[dict]:
    """Top-K highest-degree nodes per monitored rel table.

    Degree hotspots are the first-class supernode risk signal: a node whose
    edge count keeps climbing will eventually dominate traversals.
    Read-only; results land in sweep stats and the activity log.
    """
    sweep_cfg = config.get("sweep", {})
    top_k = int(sweep_cfg.get("degree_report_top_k", 10))
    alert_threshold = int(sweep_cfg.get("degree_alert_threshold", 5000))
    hotspots: list[dict] = []

    for rel, side in _DEGREE_REPORT_RELS:
        directions = []
        if side in ("from", "both"):
            directions.append(("out", f"sweep.degree_out_{rel.lower()}"))
        if side in ("to", "both"):
            directions.append(("in", f"sweep.degree_in_{rel.lower()}"))
        for direction, qname in directions:
            try:
                rows = _gateway(db).run_sync(qname, limit=top_k)
                for row in rows:
                    if isinstance(row, dict):
                        vals = list(row.values())
                        node_val, degree_val = vals[0], vals[1]
                    else:
                        node_val, degree_val = row[0], row[1]
                    table, node_id = _node_identity(node_val or {})
                    degree = int(degree_val or 0)
                    hotspots.append({
                        "node_id": node_id, "table": table,
                        "rel_table": rel, "degree": degree,
                        "direction": direction,
                    })
                    if degree >= alert_threshold:
                        _logger.warning(
                            "[Supernode] %s:%s has degree %d on %s (threshold %d)",
                            table, node_id, degree, rel, alert_threshold,
                        )
            except Exception:
                _logger.debug("[Supernode] degree query failed for %s", rel, exc_info=True)

    return hotspots


async def _prune_session_edges(db, config: dict) -> tuple[int, int]:
    """Delete LOADED/WARM_NODE cache edges for long-inactive sessions.

    These rel tables are read-through caches over the session's working set;
    they are rebuilt on the next message in that session. Without pruning,
    every session ever created keeps its edges forever.

    Returns (sessions_pruned, error_count).
    """
    sweep_cfg = config.get("sweep", {})
    if not bool(sweep_cfg.get("prune_session_edges", True)):
        return 0, 0
    ttl_days = float(sweep_cfg.get("session_edge_ttl_days", 30))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()

    try:
        rows = _gateway(db).run_sync("sweep.find_stale_sessions", cutoff=cutoff)
        stale = []
        for row in rows:
            sid = (row.get("s.session_id") if isinstance(row, dict) else row[0])
            if sid:
                stale.append(sid)
    except Exception:
        _logger.exception("[Supernode] stale session query failed")
        return 0, 1

    if not stale:
        return 0, 0

    errors = 0
    for rel in _SESSION_CACHE_RELS:
        _, bad = await _batch_write(
            db,
            f"sweep.unwind_delete_session_{rel.lower()}",
            stale,
        )
        errors += 1 if bad else 0

    _logger.info("[Supernode] pruned cache edges for %d stale sessions (ttl=%sd)",
                 len(stale), ttl_days)
    return len(stale), errors


# ---------------------------------------------------------------------------
# Step 1.5: B74 — Valence-aware decay
# ---------------------------------------------------------------------------

async def _apply_valence_decay(db) -> tuple[int, int]:
    """
    Adjust Concept pathway_strength based on accumulated OUTCOME_SIGNAL valence.
    Positive valence -> slower decay; Negative valence -> faster decay.
    """
    adjusted = errors = 0
    try:
        # 1. Query all Concepts with signals
        rows = _gateway(db).run_sync("sweep.get_outcome_signals")
        
        updates = []
        for row in rows:
            if isinstance(row, dict):
                cid = row.get("c.concept_id")
                avg_v = row.get("avg_v")
            else:
                cid, avg_v = row[0], row[1]
            if cid and avg_v is not None:
                # valence_factor in [0.7, 1.3] for valence in [-1, 1]
                factor = 1.0 + (float(avg_v) * 0.3)
                updates.append((cid, factor))
                
        # 2. Apply atomic updates
        for cid, factor in updates:
            try:
                await _gateway(db).run("sweep.strengthen_concept_pathway", cid=cid, factor=factor)
                adjusted += 1
            except Exception:
                errors += 1
                
    except Exception:
        errors += 1
        
    return adjusted, errors


# ---------------------------------------------------------------------------
# Step 2: Resurrection
# ---------------------------------------------------------------------------

_DEFAULT_RESURRECTION_CANDIDATES_PER_SWEEP = 200


def _resurrect_candidates_sync(
    db, table: str, pk_col: str, index_name: str,
    resurrection_threshold: float, candidate_limit: int,
) -> tuple[list, int]:
    """B373: the synchronous, per-table resurrection scan -- one HNSW
    `vector_search` call per archived+embedded node, previously run
    directly on the asyncio event loop thread with no cap and no thread
    offload. Confirmed via a live stack trace (sample(1) during a real
    incident, cross-checked independently by two sessions) that this was
    genuinely blocking the daemon's entire event loop -- a table with
    tens of thousands of archived rows (this project's own Message table
    has ~18k) means tens of thousands of synchronous Kuzu calls in one
    unbroken Python loop, which grows without bound as more nodes get
    archived over the graph's lifetime. `candidate_limit` bounds the
    worst case per sweep per table; this whole function additionally runs
    off the event loop thread via `asyncio.to_thread` in the caller below,
    so even the bounded amount of work here can't block anything else.
    Not a smart "most-worth-checking-first" ordering -- just Kuzu's
    natural scan order, capped. A future improvement, not attempted here
    under time pressure: round-robin/random sampling so the whole archive
    gets covered across many sweeps instead of always re-checking the
    same first N rows.
    """
    try:
        rows = _gateway(db).run_sync(f"sweep.resurrect_active_embeddings_{table.lower()}", limit=int(candidate_limit))

        archived_nodes = []
        for row in rows:
            if isinstance(row, dict):
                vals = list(row.values())
                nid, emb_val = vals[0], vals[1]
            else:
                nid, emb_val = row[0], row[1]
            if nid and emb_val:
                archived_nodes.append((nid, emb_val))

    except Exception:
        return [], 1

    to_resurrect = []
    errors = 0
    for node_id, embedding in archived_nodes:
        try:
            # SW2 fix: fetch more results since we'll filter out archived
            # neighbors. HNSW doesn't support prefiltering in 0.11.3, so
            # we over-fetch and postfilter to active nodes only.
            neighbors = db.vector_search(table, index_name, embedding, 20)
            for neighbor in neighbors:
                node  = neighbor["node"]
                score = neighbor["score"]

                # Skip self-match and archived neighbors.
                # SW2: explicitly check archived=false to ensure we only
                # compare against active (confirmed) nodes per spec.
                if node.get(pk_col) == node_id:
                    continue
                if node.get("archived", True):
                    continue

                if score >= resurrection_threshold:
                    to_resurrect.append(node_id)
                    break  # one match is enough

        except Exception:
            errors += 1

    return to_resurrect, errors


async def _resurrect_archived(
    db,
    resurrection_threshold: float,
    candidate_limit: int = _DEFAULT_RESURRECTION_CANDIDATES_PER_SWEEP,
) -> tuple[int, int]:
    """
    For each archived node (up to `candidate_limit` per table per sweep),
    search for similar active nodes in the same table using the HNSW vector
    index. If any neighbor scores above resurrection_threshold, un-archive
    the node and reset its strength.

    Strength reset to resurrection_threshold (not 1.0 — node was dormant and
    must earn full strength back through access per the Hebbian model).

    B279: resurrection_threshold is a true cosine similarity threshold.
    B373: the actual scan runs off the event loop thread; see
    _resurrect_candidates_sync's docstring for why.

    Returns (resurrected_count, error_count).
    """
    resurrected = errors = 0

    for table, pk_col, _, index_name in SWEEP_TABLES:
        to_resurrect, table_errors = await asyncio.to_thread(
            _resurrect_candidates_sync, db, table, pk_col, index_name,
            resurrection_threshold, candidate_limit,
        )
        errors += table_errors

        # B282: batch the resurrection updates (strength is a constant reset,
        # so a plain id list suffices).
        if to_resurrect:
            try:
                await _gateway(db).run(
                    f"sweep.resurrect_node_{table.lower()}",
                    ids=to_resurrect,
                    strength=float(resurrection_threshold),
                )
                resurrected += len(to_resurrect)
            except Exception:
                errors += len(to_resurrect)

    return resurrected, errors


# ---------------------------------------------------------------------------
# Step 3: Hebbian Trigger 2 — CO_OCCURS_WITH auto-promotion
# ---------------------------------------------------------------------------

_PROMOTION_PROMPT = """\
Two concepts frequently co-occur in the same AI assistant conversation context.
Based on the concept text alone, determine their most likely semantic relationship.

Concept A: {text_a}
Concept B: {text_b}

Choose exactly one relationship type from this list, or null if none clearly applies:
REQUIRES, ENABLES, REPLACES, CONTRADICTS, PART_OF, CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO

Rules:
- Only choose a type if you are confident (>= 0.70)
- "A REQUIRES B" means A depends on B to function
- "A ENABLES B" means A makes B possible
- "A REPLACES B" means A supersedes B
- "A CONTRADICTS B" means A and B are in conflict
- "A PART_OF B" means A is a component of B
- "A CHOSEN_OVER B" means A was selected instead of B
- "A IMPLEMENTS B" means A is a concrete realization of B
- "A EXTENDS B" means A builds on B
- "A ALTERNATIVE_TO B" means A and B are options for the same need

Respond with JSON only, no explanation:
{{"relation_type": "REQUIRES", "confidence": 0.82}}

If no relationship clearly applies:
{{"relation_type": null, "confidence": 0.0}}"""


async def _hebbian_promote(
    db,
    llm_client,
    co_occurrence_threshold: int,
) -> tuple[int, int]:
    """
    Find CO_OCCURS_WITH edges at or above co_occurrence_threshold and ask
    the LLM to name the semantic relationship. Writes the named edge with
    inferred_by="LLM". Uses upsert — idempotent if edge already exists.

    Returns (promoted_count, error_count).
    """
    promoted = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    # Fetch high-count co-occurrence pairs that don't already have a named edge.
    # SW3 fix: exclude pairs where any named semantic relationship already exists
    # to avoid re-prompting the LLM for already-promoted pairs.
    try:
        rows = _gateway(db).run_sync("sweep.get_co_occurring_concepts", threshold=co_occurrence_threshold)
        pairs = []
        for row in rows:
            if isinstance(row, dict):
                a_id = row.get("a.concept_id")
                a_text = row.get("a.text_raw") or ""
                b_id = row.get("b.concept_id")
                b_text = row.get("b.text_raw") or ""
                count_v = row.get("r.count")
            else:
                a_id = row[0]
                a_text = row[1] or ""
                b_id = row[2]
                b_text = row[3] or ""
                count_v = row[4]
            pairs.append({
                "a_id":   a_id,
                "a_text": a_text,
                "b_id":   b_id,
                "b_text": b_text,
                "count":  count_v,
            })
    except Exception:
        return 0, 1

    for pair in pairs:
        if not pair["a_text"] or not pair["b_text"]:
            continue

        try:
            prompt = _PROMOTION_PROMPT.format(
                text_a=pair["a_text"],
                text_b=pair["b_text"],
            )
            # B371: the achat-or-else-plain-chat() branching used to be
            # duplicated inline here, with the else branch calling
            # llm_client.chat() synchronously with no await and no thread
            # offload -- a real event-loop-blocking bug for any LLM client
            # lacking achat (dead in this deployment's real Ollama-backed
            # client, which always has achat, but a genuine latent bug).
            # _call_llm() already implements this branching correctly and
            # is used elsewhere in this file -- reuse it instead of a third
            # copy of the same logic.
            raw = await _call_llm(llm_client, prompt)

            parsed     = json.loads(raw.strip())
            rel_type   = parsed.get("relation_type")
            confidence = float(parsed.get("confidence", 0.0))

            if rel_type not in _NAMED_REL_TYPES:
                continue
            if confidence < 0.60:
                continue

            # Write named relationship — upsert is idempotent
            await _gateway(db).run(
                f"sweep.merge_concept_rel_{rel_type.lower()}",
                a_id=pair["a_id"],
                b_id=pair["b_id"],
                conf=confidence,
                now=now,
            )
            promoted += 1

        except (json.JSONDecodeError, KeyError, ValueError):
            # LLM returned malformed JSON — skip silently, will retry next sweep
            pass
        except Exception:
            errors += 1

    return promoted, errors


# ---------------------------------------------------------------------------
# Step 4 (sweep): Centroid recomputation from System 2 examples (M4)
# ---------------------------------------------------------------------------

async def _recompute_centroids(db) -> tuple[int, int]:
    """
    For each GistClass that has at least one GistExample, mean-pool all
    example embeddings and update GistClass.centroid.

    This makes the System 1 fast-path self-improving — centroids shift toward
    real usage patterns as System 2 accumulates labeled examples over time.

    Returns (updated_count, error_count).
    """
    updated = errors = 0

    # Fetch distinct gist classes that have examples
    try:
        rows = _gateway(db).run_sync("sweep.get_distinct_gist_classes")
        classes_with_examples = []
        for row in rows:
            c = (row.get("e.gist_class") if isinstance(row, dict) else row[0])
            if c:
                classes_with_examples.append(c)
    except Exception:
        return 0, 1

    for class_name in classes_with_examples:
        try:
            rows_e = _gateway(db).run_sync("sweep.get_gist_examples_by_class", cls=class_name)
            embeddings = []
            for row in rows_e:
                e_val = (row.get("e.embedding") if isinstance(row, dict) else row[0])
                if e_val:
                    embeddings.append(e_val)

            if not embeddings:
                continue

            # Mean-pool: sum then divide element-wise
            dim = len(embeddings[0])
            centroid = [0.0] * dim
            for emb in embeddings:
                for i, v in enumerate(emb):
                    centroid[i] += v
            n = len(embeddings)
            centroid = [v / n for v in centroid]

            # Normalize to unit vector (cosine similarity requires unit vectors)
            norm = sum(v * v for v in centroid) ** 0.5
            if norm > 0:
                centroid = [v / norm for v in centroid]

            await _gateway(db).run("sweep.update_gist_class_centroid", name=class_name, centroid=centroid)
            updated += 1

        except Exception:
            errors += 1

    return updated, errors


# ---------------------------------------------------------------------------
# Step 3.5: Dream consolidation / synthesis
# ---------------------------------------------------------------------------


async def _dream_consolidation(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    Cluster Lesson nodes by domain + embedding similarity and synthesize
    meta-lessons using the LLM. Returns (synthesized_count, error_count).

    Config (campy.toml):
      [sweep.dreaming]
      min_cluster_size = 3
      similarity_threshold = 0.75
      max_syntheses_per_sweep = 5
      decay_boost_multiplier = 1.3
    """
    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    dreaming_cfg = config.get("sweep", {}).get("dreaming", {})
    min_cluster = int(dreaming_cfg.get("min_cluster_size", 3))
    sim_thresh = float(dreaming_cfg.get("similarity_threshold", 0.75))
    max_per_sweep = int(dreaming_cfg.get("max_syntheses_per_sweep", 5))
    decay_boost = float(dreaming_cfg.get("decay_boost_multiplier", 1.3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # 1) Discover candidate domains
    try:
        rows_d = _gateway(db).run_sync("sweep.get_dream_lesson_domains")
    except Exception:
        return 0, 1

    domains = []
    for row in rows_d:
        dom = (row.get("l.domain") if isinstance(row, dict) else row[0]) or ""
        if dom:
            domains.append(dom)

    for domain in domains:
        try:
            rows_c = _gateway(db).run_sync("sweep.get_lessons_for_synthesis", domain=domain)
        except Exception:
            errors += 1
            continue

        candidates = []
        for row in rows_c:
            if isinstance(row, dict):
                lid = row.get("l.lesson_id")
                embedding = row.get("l.embedding")
                text = row.get("l.text_raw") or ""
                pathway = float(row.get("l.pathway_strength") or 0.0)
                conf = float(row.get("l.confidence") or 0.0)
            else:
                lid = row[0]
                embedding = row[1]
                text = row[2] or ""
                pathway = float(row[3] or 0.0)
                conf = float(row[4] or 0.0)
            if lid and embedding:
                candidates.append({"id": lid, "emb": embedding, "text": text, "pathway": pathway, "confidence": conf})

        if len(candidates) < min_cluster:
            continue

        # Normalize embeddings for cosine similarity
        for c in candidates:
            vec = c["emb"]
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                c["emb_norm"] = [v / norm for v in vec]
            else:
                c["emb_norm"] = vec

        unassigned = set(range(len(candidates)))
        clusters = []
        # Greedy clustering: seed with an unassigned item, group neighbors above threshold
        while unassigned and len(clusters) < max_per_sweep:
            i = next(iter(unassigned))
            seed = candidates[i]
            cluster_idx = [i]
            others = list(unassigned - {i})
            for j in others:
                a = seed["emb_norm"]
                b = candidates[j]["emb_norm"]
                denom = (sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5)
                sim = 0.0
                if denom > 0:
                    sim = sum(x * y for x, y in zip(a, b)) / denom
                if sim >= sim_thresh:
                    cluster_idx.append(j)
            for k in cluster_idx:
                unassigned.discard(k)
            if len(cluster_idx) >= min_cluster:
                clusters.append([candidates[k] for k in cluster_idx])

        for cluster in clusters:
            if synthesized >= max_per_sweep:
                break
            try:
                excerpts = "\n\n".join(f"- {c['text']}" for c in cluster)
                prompt = (
                    f"Synthesize a concise meta-lesson for domain '{domain}'.\n\n"
                    f"Excerpts:\n{excerpts}\n\n"
                    "Return a short, stand-alone lesson text (title + 1-2-sentence summary + 1 actionable recommendation)."
                )
                # B371: the else branch used to `await llm_client.chat(...)`
                # -- chat() returns a plain str synchronously, so awaiting
                # it would raise TypeError for any LLM client lacking achat.
                # Reuse _call_llm() (already used elsewhere in this file)
                # instead of a third copy of the achat-or-else branching.
                raw = await _call_llm(llm_client, prompt)
                synth_text = (raw or "").strip()
                if not synth_text:
                    continue

                meta_emb = emb.embed(synth_text, model_name=embedding_model)
                meta_id = str(uuid.uuid4())
                max_path = max(c["pathway"] for c in cluster)
                avg_conf = sum(c["confidence"] for c in cluster) / len(cluster)
                meta_strength = min(1.0, max_path * 1.2)
                meta_conf = min(0.99, avg_conf + 0.05)

                # Create synthesized Lesson node
                await _gateway(db).run(
                    "sweep.create_synthesized_lesson",
                    lid=meta_id,
                    text_raw=synth_text,
                    embedding=meta_emb,
                    embedding_model=embedding_model,
                    embedding_dim=len(meta_emb),
                    domain=domain,
                    confidence=meta_conf,
                    pathway_strength=meta_strength,
                    now=now,
                )

                # Link meta-lesson -> constituents and accelerate constituent decay
                for c in cluster:
                    await _gateway(db).run(
                        "sweep.link_generalizes_lesson",
                        mid=meta_id,
                        cid=c["id"],
                        now=now,
                        cluster_size=len(cluster),
                    )
                    await _gateway(db).run(
                        "sweep.touch_subsumed_lesson",
                        cid=c["id"],
                        now=now,
                        cluster_size=len(cluster),
                        decay_boost=decay_boost,
                    )

                synthesized += 1
            except Exception:
                errors += 1

    # After lesson synthesis, attempt procedure synthesis (B194)
    try:
        p_count, p_err = await _synthesize_procedures(db, config, llm_client)
        synthesized += p_count
        errors += p_err
    except Exception:
        errors += 1

    # Basal Ganglia: frustration cluster detection (no LLM needed)
    try:
        fc_count, fc_err = await _detect_frustration_clusters(db, config)
        synthesized += fc_count
        errors += fc_err
    except Exception:
        errors += 1

    # Basal Ganglia: update Procedure maturity stages
    try:
        maturity_result = await _update_procedure_maturity(db, config)
        _logger.info("[BasalGanglia] maturity update: %s", maturity_result)
    except Exception:
        errors += 1

    return synthesized, errors


async def _update_procedure_maturity(db, config: dict) -> dict:
    """
    Basal Ganglia — Maturity Lifecycle.

    Update maturity_stage for all active Procedures based on application stats.
    Also detect degradation and archive deeply degraded Procedures.

    Returns summary dict.
    """
    result = {"updated": 0, "degraded": 0, "archived": 0, "errors": 0}

    # 1) Promote: nascent -> developing -> mature
    try:
        await _gateway(db).run("sweep.promote_procedure_maturity")
        result["updated"] += 1
    except Exception:
        _logger.exception("[BasalGanglia] Procedure maturity promotion query failed")
        result["errors"] += 1

    # 2) Degrade: application_count >= 3 AND success_rate < 0.30
    try:
        await _gateway(db).run("sweep.degrade_procedure_maturity")
        result["degraded"] += 1
    except Exception:
        _logger.exception("[BasalGanglia] Procedure maturity degrade query failed")
        result["errors"] += 1

    # 3) Archive: already degraded AND still failing
    try:
        await _gateway(db).run("sweep.archive_degraded_procedure")
        result["archived"] += 1
    except Exception:
        _logger.exception("[BasalGanglia] Procedure archive query failed")
        result["errors"] += 1

    return result


async def _call_llm(llm_client: Optional[object], prompt: str) -> str:
    """Call the LLM client in a sync/async safe way and return raw text."""
    if llm_client is None:
        return ""
    try:
        if hasattr(llm_client, "achat"):
            res = llm_client.achat([{"role": "user", "content": prompt}])
        else:
            res = llm_client.chat([{"role": "user", "content": prompt}])
        if asyncio.iscoroutine(res):
            return await res
        return res
    except Exception:
        return ""


# Basal Ganglia extraction: frustration cluster detection
from campy.brain.basal_ganglia.frustration_clusters import detect_frustration_clusters as _detect_frustration_clusters


# Basal Ganglia extraction: procedure synthesis
from campy.brain.basal_ganglia.procedure_synthesis import synthesize_procedures as _synthesize_procedures


async def _audit_consistency(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    B196: Internal Consistency Audit

    - For each domain, select top-N Lessons by pathway_strength.
    - Pairwise compare embeddings; if similarity > threshold, ask LLM whether
      they contradict, supersede, or are both valid in different contexts.
    - Create DisambiguationEvent for contradictions/nuanced cases or
      DEPRECATED_BY + archive when one supersedes the other.
    - Flag stale Lessons (older than 30 days with no outgoing linkage).
    - Flag orphan Lessons (no inbound provenance edges).

    Returns: (audits_performed, errors)
    """
    audited = 0
    errors = 0
    now = datetime.now(timezone.utc).isoformat()

    cons_cfg = (config.get("sweep", {}) or {}).get("consistency", {})
    top_k = int(cons_cfg.get("top_lessons", 20))
    sim_thresh = float(cons_cfg.get("sim_threshold", 0.70))
    max_llm = int(cons_cfg.get("max_llm_calls", 10))
    min_path = float(cons_cfg.get("min_pathway_strength", 0.3))
    stale_days = int(cons_cfg.get("stale_days", 30))

    # 1) Get all domains with lessons
    domains = []
    try:
        rows_d = _gateway(db).run_sync("sweep.get_all_lesson_domains")
        for row in rows_d:
            d = (row.get("l.domain") if isinstance(row, dict) else row[0])
            if d:
                domains.append(d)
    except Exception:
        return 0, 1

    candidate_pairs: list[tuple[dict, dict, float]] = []

    for domain in domains:
        try:
            res_rows = _gateway(db).run_sync("sweep.get_lessons_in_domain_embeddings", domain=domain, min_path=min_path, limit=top_k)
        except Exception:
            errors += 1
            continue

        lessons = []
        for row in res_rows:
            if isinstance(row, dict):
                lid = row.get("l.lesson_id")
                emb_vec = row.get("l.embedding")
                text = row.get("l.text_raw") or ""
                conf = float(row.get("l.confidence") or 0.0)
                pathway = float(row.get("l.pathway_strength") or 0.0)
                last_aud = row.get("l.last_audited_at")
            else:
                lid = row[0]
                emb_vec = row[1]
                text = row[2] or ""
                conf = float(row[3] or 0.0)
                pathway = float(row[4] or 0.0)
                last_aud = row[6] if len(row) > 6 else None
            if lid and emb_vec:
                lessons.append({"id": lid, "emb": emb_vec, "text": text, "conf": conf, "pathway": pathway, "last_audited_at": last_aud})

        if len(lessons) < 2:
            continue

        # Normalize embeddings for cosine similarity
        for l in lessons:
            vec = l["emb"]
            try:
                norm = sum(float(v) * float(v) for v in vec) ** 0.5
                if norm > 0:
                    l["emb_norm"] = [float(v) / norm for v in vec]
                else:
                    l["emb_norm"] = [float(v) for v in vec]
            except Exception:
                l["emb_norm"] = [float(v) for v in vec]

        # Pairwise compare
        for i in range(len(lessons)):
            for j in range(i + 1, len(lessons)):
                a = lessons[i]
                b = lessons[j]
                # Skip if both recently audited
                try:
                    skip = False
                    if a.get("last_audited_at") and b.get("last_audited_at"):
                        # If both have any last_audited_at, skip (keeps audit budget bounded)
                        skip = True
                    if skip:
                        continue
                except Exception:
                    pass

                va = a.get("emb_norm")
                vb = b.get("emb_norm")
                denom = (sum(x * x for x in va) ** 0.5) * (sum(x * x for x in vb) ** 0.5)
                sim = 0.0
                if denom > 0:
                    sim = sum(x * y for x, y in zip(va, vb)) / denom

                if sim >= sim_thresh:
                    candidate_pairs.append((a, b, sim))

    # Sort by similarity desc
    candidate_pairs.sort(key=lambda t: t[2], reverse=True)

    llm_calls = 0
    processed_lessons = set()

    for a, b, sim in candidate_pairs:
        if llm_calls >= max_llm or llm_client is None:
            break
        try:
            prompt = (
                f"You are auditing two extracted lessons for domain '{(a.get('text') or '')[:40]}'.\n"
                "Decide whether the two lessons: 1) directly contradict each other, 2) one supersedes the other (specify which as 'a' or 'b'), 3) are both valid but for different contexts, or 4) are consistent.\n"
                "Return a JSON object with keys: action ('contradict'|'supersedes'|'both_valid'|'no_issue'), winner (optional 'a'|'b'), explanation (string), confidence (0.0-1.0)."
            )
            raw = await _call_llm(llm_client, prompt)
            if not raw:
                llm_calls += 1
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                obj = {}

            action = obj.get("action", "")
            winner = obj.get("winner")

            # Handle actions
            if action == "contradict":
                # Create DisambiguationEvent for human review
                try:
                    eid = str(uuid.uuid4())
                    await _gateway(db).run(
                        "sweep.create_disambiguation_event",
                        eid=eid, a=a["id"], b=b["id"], sim=float(sim), now=now,
                    )
                    audited += 1
                except Exception:
                    errors += 1

            elif action == "supersedes" and winner in ("a", "b"):
                # Archive the loser and draw DEPRECATED_BY loser -> winner
                try:
                    loser = b["id"] if winner == "a" else a["id"]
                    win = a["id"] if winner == "a" else b["id"]
                    await _gateway(db).run("sweep.archive_lesson", lid=loser)
                    await _gateway(db).run("sweep.link_lesson_deprecated_by", old=loser, new=win)
                    audited += 1
                except Exception:
                    errors += 1

            elif action == "both_valid":
                # Create DisambiguationEvent for human review (nuanced)
                try:
                    eid = str(uuid.uuid4())
                    await _gateway(db).run(
                        "sweep.create_disambiguation_event",
                        eid=eid, a=a["id"], b=b["id"], sim=float(sim), now=now,
                    )
                    audited += 1
                except Exception:
                    errors += 1

            llm_calls += 1
            processed_lessons.add(a["id"])
            processed_lessons.add(b["id"])
        except Exception:
            errors += 1

    # Update last_audited_at for processed lessons
    try:
        for lid in processed_lessons:
            try:
                await _gateway(db).run("sweep.touch_audited_lesson", lid=lid, now=now)
            except Exception:
                pass
    except Exception:
        pass

    # Stale detection: older than stale_days with no outgoing APPLIES_TO|RELATED_TO|GENERALIZES_LESSON
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        rows_sr = _gateway(db).run_sync("sweep.get_stale_lessons", cutoff=cutoff)
        stale_count = 0
        for row in rows_sr:
            lid = (row.get("l.lesson_id") if isinstance(row, dict) else row[0])
            try:
                await _gateway(db).run("sweep.flag_stale_lesson", lid=lid, now=now)
                stale_count += 1
            except Exception:
                errors += 1
        audited += stale_count
    except Exception:
        errors += 1

    # Orphan detection: no inbound CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED
    try:
        rows_orr = _gateway(db).run_sync("sweep.get_orphan_lessons")
        orphan_count = 0
        for row in rows_orr:
            lid = (row.get("l.lesson_id") if isinstance(row, dict) else row[0])
            try:
                await _gateway(db).run("sweep.flag_orphan_lesson", lid=lid, now=now)
                orphan_count += 1
            except Exception:
                errors += 1
        audited += orphan_count
    except Exception:
        errors += 1

    return audited, errors
