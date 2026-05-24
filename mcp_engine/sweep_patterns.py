"""
mcp_engine/sweep_patterns.py — Offline Pattern Discovery (Phase 4)

Anticipatory Engine offline mode: sweep-based retrospective pattern discovery.
Runs during the background sweep cycle to find temporal, sequence, and frequency
patterns in historical graph data that no single message would reveal.

Pattern types:
  - Temporal: recurring errors at consistent time intervals
  - Sequence: action chains that consistently precede failures
  - Frequency: error types with increasing occurrence rates

Discovered patterns become Lesson/Procedure nodes with trigger metadata,
feeding back into the online mode (step4b_associative.py) and the trigger
manifest (trigger_manifest.py).

Named IP Claims:
  - Prospective Memory: retrospective pattern discovery from graph history
  - Associative Priming: auto-binding triggers from discovered patterns

Called by: mcp_engine/sweep.py run_sweep() as Step 7.5
"""

from __future__ import annotations

import asyncio as _asyncio
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

from mcp_engine.graph import embeddings as emb
from mcp_engine.loop.step4b_associative import _build_trigger_pattern

_logger = logging.getLogger(__name__)

# Minimum instances required before a pattern is considered
MIN_TEMPORAL_INSTANCES = 3
MIN_SEQUENCE_INSTANCES = 3
MIN_FREQUENCY_SESSIONS = 4

# Coefficient of variation threshold for temporal clustering
# CV < 0.3 means the intervals are consistent enough to be a pattern
MAX_TEMPORAL_CV = 0.30

# Maximum candidates per pattern type per sweep to bound LLM cost
MAX_CANDIDATES_PER_TYPE = 5

# Maximum total candidates sent to LLM per sweep cycle
MAX_TOTAL_CANDIDATES = 10


async def discover_patterns(
    db: "KuzuClient",
    config: dict,
    llm_client: Optional[object],
) -> dict:
    """
    Discover patterns in historical graph data and write trigger metadata.

    Coordinator function called by run_sweep(). Runs three discovery
    functions, deduplicates candidates, validates via LLM, and writes
    trigger metadata to matched nodes.

    Returns:
        {
            "candidates_found": int,
            "candidates_validated": int,
            "triggers_written": int,
            "errors": int,
            "by_type": {"temporal": int, "sequence": int, "frequency": int},
        }
    """
    pat_cfg = config.get("sweep", {}).get("patterns", {})

    if not pat_cfg.get("enabled", True):
        return {
            "candidates_found": 0, "candidates_validated": 0,
            "triggers_written": 0, "errors": 0,
            "by_type": {"temporal": 0, "sequence": 0, "frequency": 0},
        }

    summary = {
        "candidates_found": 0, "candidates_validated": 0,
        "triggers_written": 0, "errors": 0,
        "by_type": {"temporal": 0, "sequence": 0, "frequency": 0},
    }

    all_candidates: list[dict] = []

    if pat_cfg.get("temporal_enabled", True):
        try:
            temporal = await _discover_temporal_patterns(db, pat_cfg)
            all_candidates.extend(temporal)
            summary["by_type"]["temporal"] = len(temporal)
        except Exception as e:
            _logger.warning("[SweepPatterns] temporal discovery failed: %s", e)
            summary["errors"] += 1

    if pat_cfg.get("sequence_enabled", True):
        try:
            sequence = await _discover_sequence_patterns(db, pat_cfg)
            all_candidates.extend(sequence)
            summary["by_type"]["sequence"] = len(sequence)
        except Exception as e:
            _logger.warning("[SweepPatterns] sequence discovery failed: %s", e)
            summary["errors"] += 1

    if pat_cfg.get("frequency_enabled", True):
        try:
            frequency = await _discover_frequency_patterns(db, pat_cfg)
            all_candidates.extend(frequency)
            summary["by_type"]["frequency"] = len(frequency)
        except Exception as e:
            _logger.warning("[SweepPatterns] frequency discovery failed: %s", e)
            summary["errors"] += 1

    summary["candidates_found"] = len(all_candidates)

    if not all_candidates:
        return summary

    all_candidates = await _deduplicate_candidates(db, all_candidates)

    max_total = int(pat_cfg.get("max_total_candidates", MAX_TOTAL_CANDIDATES))
    all_candidates = all_candidates[:max_total]

    validated, errors = await _validate_candidates(all_candidates, llm_client)
    summary["candidates_validated"] = len(validated)
    summary["errors"] += errors

    written, write_errors = await _write_trigger_metadata(db, config, validated)
    summary["triggers_written"] = written
    summary["errors"] += write_errors

    _logger.info(
        "[SweepPatterns] found=%d validated=%d written=%d errors=%d",
        summary["candidates_found"], summary["candidates_validated"],
        summary["triggers_written"], summary["errors"],
    )

    return summary


async def _discover_temporal_patterns(db, pat_cfg: dict) -> list[dict]:
    """Find recurring patterns where similar errors/events occur at consistent time intervals."""
    min_instances = int(pat_cfg.get("min_temporal_instances", MIN_TEMPORAL_INSTANCES))
    max_cv = float(pat_cfg.get("max_temporal_cv", MAX_TEMPORAL_CV))
    max_candidates = int(pat_cfg.get("max_candidates_per_type", MAX_CANDIDATES_PER_TYPE))

    candidates: list[dict] = []

    try:
        result = db.execute(
            "MATCH (m:Message)-[:CONTAINS_LESSON]->(l:Lesson) "
            "WHERE l.archived = false "
            "  AND l.trigger_pattern IS NULL "
            "  AND m.created_at IS NOT NULL "
            "RETURN l.lesson_id, l.text_raw, m.created_at "
            "ORDER BY l.lesson_id, m.created_at ASC"
        )
    except Exception:
        return []

    lesson_timestamps: dict[str, list] = defaultdict(list)
    lesson_text: dict[str, str] = {}
    while result.has_next():
        row = result.get_next()
        lid, text, ts = row[0], row[1] or "", row[2]
        if lid and ts is not None:
            lesson_timestamps[lid].append(ts)
            if lid not in lesson_text:
                lesson_text[lid] = text

    for lid, timestamps in lesson_timestamps.items():
        if len(timestamps) < min_instances:
            continue

        deltas: list[float] = []
        for i in range(1, len(timestamps)):
            try:
                t1, t2 = timestamps[i - 1], timestamps[i]
                if hasattr(t1, 'timestamp') and hasattr(t2, 'timestamp'):
                    delta = t2.timestamp() - t1.timestamp()
                else:
                    delta = float(t2) - float(t1)
                if delta > 0:
                    deltas.append(delta)
            except (TypeError, ValueError):
                continue

        if len(deltas) < min_instances - 1:
            continue

        mean_delta = sum(deltas) / len(deltas)
        if mean_delta <= 0:
            continue
        variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
        std_dev = variance ** 0.5
        cv = std_dev / mean_delta

        if cv > max_cv:
            continue

        text = lesson_text.get(lid, "")
        trigger_pattern = _build_trigger_pattern(text)

        hours = mean_delta / 3600
        interval_str = f"~{hours:.1f} hours" if hours >= 1 else f"~{mean_delta:.0f} seconds"

        candidates.append({
            "type": "temporal",
            "node_type": "Lesson",
            "node_id": lid,
            "node_text": text[:200],
            "evidence": (
                f"This error/event recurs every {interval_str} "
                f"(CV={cv:.2f}, n={len(timestamps)} occurrences). "
                f"Deltas: {[f'{d/3600:.1f}h' for d in deltas[:5]]}"
            ),
            "mean_interval_seconds": mean_delta,
            "cv": cv,
            "instance_count": len(timestamps),
            "proposed_trigger_pattern": trigger_pattern,
            "proposed_hook_type": "PostToolUse",
            "proposed_tool": "Bash",
        })

        if len(candidates) >= max_candidates:
            break

    return candidates


async def _discover_sequence_patterns(db, pat_cfg: dict) -> list[dict]:
    """Find action chains where the same sequence precedes failures >N times."""
    min_instances = int(pat_cfg.get("min_sequence_instances", MIN_SEQUENCE_INSTANCES))
    max_candidates = int(pat_cfg.get("max_candidates_per_type", MAX_CANDIDATES_PER_TYPE))

    candidates: list[dict] = []

    try:
        result = db.execute(
            "MATCH (ps1:PlanStep)-[:NEXT_STEP]->(ps2:PlanStep)-[:NEXT_STEP]->(ps_fail:PlanStep) "
            "WHERE ps_fail.valence IS NOT NULL AND ps_fail.valence < 0 "
            "  AND ps_fail.status = 'failed' "
            "RETURN ps1.description, ps2.description, ps_fail.description, "
            "       ps_fail.step_id, ps_fail.valence "
            "ORDER BY ps_fail.valence ASC"
        )
    except Exception:
        return []

    chains: list[dict] = []
    while result.has_next():
        row = result.get_next()
        step1_desc = (row[0] or "").strip()
        step2_desc = (row[1] or "").strip()
        fail_desc = (row[2] or "").strip()
        fail_id, valence = row[3], float(row[4] or 0)

        if not step1_desc or not step2_desc or not fail_desc:
            continue

        chain_text = f"{step1_desc} -> {step2_desc} -> {fail_desc}"
        chains.append({
            "chain_text": chain_text,
            "steps": [step1_desc, step2_desc, fail_desc],
            "fail_id": fail_id,
            "valence": valence,
        })

    if len(chains) < min_instances:
        return []

    embedding_model = pat_cfg.get(
        "embedding_model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    try:
        chain_texts = [c["chain_text"] for c in chains]
        chain_embeddings = emb.embed_batch(chain_texts, model_name=embedding_model)
    except Exception:
        return []

    for i, vec in enumerate(chain_embeddings):
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            chain_embeddings[i] = [v / norm for v in vec]

    sim_threshold = float(pat_cfg.get("sequence_similarity_threshold", 0.80))
    used = set()
    clusters: list[list[int]] = []

    for i in range(len(chains)):
        if i in used:
            continue
        cluster = [i]
        used.add(i)
        for j in range(i + 1, len(chains)):
            if j in used:
                continue
            sim = sum(a * b for a, b in zip(chain_embeddings[i], chain_embeddings[j]))
            if sim >= sim_threshold:
                cluster.append(j)
                used.add(j)
        if len(cluster) >= min_instances:
            clusters.append(cluster)

    for cluster_indices in clusters:
        if len(candidates) >= max_candidates:
            break
        cluster_chains = [chains[i] for i in cluster_indices]
        representative = cluster_chains[0]
        all_step_text = " ".join(representative["steps"])
        trigger_pattern = _build_trigger_pattern(all_step_text)

        candidates.append({
            "type": "sequence",
            "node_type": "Procedure",
            "node_id": None,
            "node_text": representative["chain_text"],
            "evidence": (
                f"Action chain '{representative['chain_text'][:100]}' "
                f"preceded failure {len(cluster_indices)} times "
                f"(avg valence={sum(c['valence'] for c in cluster_chains)/len(cluster_chains):.2f})"
            ),
            "instance_count": len(cluster_indices),
            "steps": representative["steps"],
            "proposed_trigger_pattern": trigger_pattern,
            "proposed_hook_type": "PreToolUse",
            "proposed_tool": "",
        })

    return candidates


async def _discover_frequency_patterns(db, pat_cfg: dict) -> list[dict]:
    """Find error types whose occurrence rate is increasing over recent sessions."""
    min_sessions = int(pat_cfg.get("min_frequency_sessions", MIN_FREQUENCY_SESSIONS))
    max_candidates = int(pat_cfg.get("max_candidates_per_type", MAX_CANDIDATES_PER_TYPE))

    candidates: list[dict] = []

    try:
        result = db.execute(
            "MATCH (m:Message)-[:CONTAINS_LESSON]->(l:Lesson), "
            "      (m)-[:SENT_IN]->(s:Session) "
            "WHERE l.archived = false "
            "  AND l.trigger_pattern IS NULL "
            "  AND s.started_at IS NOT NULL "
            "RETURN l.lesson_id, l.text_raw, s.session_id, s.started_at, count(m) AS msg_count "
            "ORDER BY l.lesson_id, s.started_at ASC"
        )
    except Exception:
        return []

    lesson_sessions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    lesson_text: dict[str, str] = {}
    lesson_session_order: dict[str, int] = defaultdict(int)

    while result.has_next():
        row = result.get_next()
        lid, text, sid, started_at, count = row[0], row[1] or "", row[2], row[3], int(row[4] or 0)

        if not lid or count == 0:
            continue

        order = lesson_session_order[lid]
        lesson_session_order[lid] += 1
        lesson_sessions[lid].append((order, count))
        if lid not in lesson_text:
            lesson_text[lid] = text

    for lid, session_counts in lesson_sessions.items():
        if len(session_counts) < min_sessions:
            continue

        n = len(session_counts)
        xs = [sc[0] for sc in session_counts]
        ys = [sc[1] for sc in session_counts]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)

        if denominator == 0:
            continue

        slope = numerator / denominator

        if slope <= 0:
            continue

        recent_count = ys[-1]
        if recent_count <= mean_y:
            continue

        text = lesson_text.get(lid, "")
        trigger_pattern = _build_trigger_pattern(text)

        candidates.append({
            "type": "frequency",
            "node_type": "Lesson",
            "node_id": lid,
            "node_text": text[:200],
            "evidence": (
                f"Occurrence rate increasing over {n} sessions "
                f"(slope={slope:.2f}, recent_count={recent_count}, "
                f"mean={mean_y:.1f}, counts={ys[-5:]})"
            ),
            "instance_count": sum(ys),
            "slope": slope,
            "proposed_trigger_pattern": trigger_pattern,
            "proposed_hook_type": "PostToolUse",
            "proposed_tool": "Bash",
        })

        if len(candidates) >= max_candidates:
            break

    candidates.sort(key=lambda c: c.get("slope", 0), reverse=True)
    return candidates[:max_candidates]


async def _deduplicate_candidates(db, candidates: list[dict]) -> list[dict]:
    """Remove candidates whose trigger pattern already exists in the graph."""
    existing_patterns: set[str] = set()

    try:
        r = db.execute(
            "MATCH (l:Lesson) WHERE l.archived = false "
            "AND l.trigger_pattern IS NOT NULL AND l.trigger_pattern <> '' "
            "RETURN l.trigger_pattern"
        )
        while r.has_next():
            row = r.get_next()
            if row[0]:
                existing_patterns.add(row[0].strip())
    except Exception:
        pass

    try:
        r = db.execute(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND p.trigger_pattern IS NOT NULL AND p.trigger_pattern <> '' "
            "RETURN p.trigger_pattern"
        )
        while r.has_next():
            row = r.get_next()
            if row[0]:
                existing_patterns.add(row[0].strip())
    except Exception:
        pass

    deduplicated = []
    for c in candidates:
        proposed = c.get("proposed_trigger_pattern", "").strip()
        if proposed and proposed not in existing_patterns:
            deduplicated.append(c)
        else:
            _logger.debug("[SweepPatterns] dedup: skipping existing pattern %r", proposed)

    return deduplicated


_VALIDATION_PROMPT = """\
You are validating automatically-discovered patterns from a memory system's graph database.
Each candidate represents a potential recurring pattern that should trigger a context injection
when the agent encounters a similar situation.

For each candidate, decide whether it represents a genuine, actionable pattern or is noise.

Candidates:
{candidates_json}

For each candidate, return a JSON object with:
- "index": the candidate's index (0-based)
- "valid": true if this is a genuine pattern worth triggering on, false if noise
- "confidence": 0.0-1.0 your confidence in this assessment
- "reason": one-sentence explanation

Return a JSON array of objects, one per candidate. Example:
[{{"index": 0, "valid": true, "confidence": 0.85, "reason": "Clear temporal pattern in SSO expiration"}}]

Rules:
- A temporal pattern is valid if the interval is plausible for the described event type
- A sequence pattern is valid if the action chain has a clear causal relationship to the failure
- A frequency pattern is valid if increasing occurrence suggests a systemic issue, not random variation
- Reject patterns that are too generic (would match too many unrelated inputs)
- Reject patterns where the evidence count is borderline (barely above minimum)
"""


async def _validate_candidates(
    candidates: list[dict], llm_client: Optional[object],
) -> tuple[list[dict], int]:
    """Validate candidate patterns via LLM. Single batched call. Degrades if LLM is None."""
    if not candidates:
        return [], 0

    if llm_client is None:
        for c in candidates:
            c["validated"] = True
            c["validation_confidence"] = 0.5
            c["confidence_low"] = True
        _logger.info("[SweepPatterns] no LLM, accepting %d candidates as confidence_low", len(candidates))
        return candidates, 0

    candidate_descriptions = [
        {"index": i, "type": c["type"], "text": c.get("node_text", "")[:150],
         "evidence": c.get("evidence", ""), "proposed_trigger": c.get("proposed_trigger_pattern", "")}
        for i, c in enumerate(candidates)
    ]

    prompt = _VALIDATION_PROMPT.format(candidates_json=json.dumps(candidate_descriptions, indent=2))

    try:
        raw = await _call_llm(llm_client, prompt)
        if not raw:
            for c in candidates:
                c["validated"] = True
                c["validation_confidence"] = 0.5
                c["confidence_low"] = True
            return candidates, 0

        try:
            validations = json.loads(raw.strip())
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                validations = json.loads(match.group())
            else:
                for c in candidates:
                    c["validated"] = True
                    c["validation_confidence"] = 0.5
                    c["confidence_low"] = True
                return candidates, 0

        validation_map = {}
        if isinstance(validations, list):
            for v in validations:
                idx = v.get("index")
                if idx is not None:
                    validation_map[idx] = v

        validated = []
        for i, c in enumerate(candidates):
            v = validation_map.get(i, {})
            is_valid = v.get("valid", True)
            confidence = float(v.get("confidence", 0.5))
            if is_valid and confidence >= 0.5:
                c["validated"] = True
                c["validation_confidence"] = confidence
                c["confidence_low"] = confidence < 0.7
                validated.append(c)

        return validated, 0

    except Exception as e:
        _logger.warning("[SweepPatterns] LLM validation failed: %s", e)
        for c in candidates:
            c["validated"] = True
            c["validation_confidence"] = 0.5
            c["confidence_low"] = True
        return candidates, 1


async def _write_trigger_metadata(
    db, config: dict, candidates: list[dict],
) -> tuple[int, int]:
    """Write trigger metadata to graph nodes for validated candidates."""
    written = errors = 0
    now = datetime.now(timezone.utc).isoformat()
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    for candidate in candidates:
        try:
            node_type = candidate.get("node_type", "Lesson")
            node_id = candidate.get("node_id")
            pattern = candidate.get("proposed_trigger_pattern", "")
            hook_type = candidate.get("proposed_hook_type", "PostToolUse")
            tool = candidate.get("proposed_tool", "")
            confidence_low = candidate.get("confidence_low", False)

            if not pattern:
                continue

            if node_type == "Lesson" and node_id:
                await db.execute_write(
                    "MATCH (l:Lesson {lesson_id: $lid}) "
                    "SET l.trigger_pattern = $pattern, "
                    "    l.trigger_hook_type = $hook_type, "
                    "    l.trigger_tool = $tool, "
                    "    l.trigger_project_scope = $scope",
                    {"lid": node_id, "pattern": pattern,
                     "hook_type": hook_type, "tool": tool, "scope": ""},
                )
                _logger.info(
                    "[SweepPatterns] wrote trigger to Lesson %s: pattern=%r type=%s",
                    node_id[:8], pattern, candidate["type"],
                )
                written += 1

            elif node_type == "Procedure" and node_id is None:
                proc_id = str(uuid.uuid4())
                steps = candidate.get("steps", [])
                node_text = candidate.get("node_text", "")

                name = f"Avoid: {node_text[:60]}"
                description = (
                    f"Auto-discovered failure sequence: {node_text}. "
                    f"Evidence: {candidate.get('evidence', '')}"
                )
                steps_json = json.dumps([
                    {"step": i + 1, "action": s, "warning": "This sequence has led to failures"}
                    for i, s in enumerate(steps)
                ])

                try:
                    proc_emb = emb.embed(description, model_name=embedding_model)
                except Exception:
                    proc_emb = [0.0] * 384

                await db.execute_write(
                    """
                    CREATE (pr:Procedure {
                        procedure_id: $pid, name: $name,
                        domain: 'auto-discovered', archetype: 'failure-sequence',
                        description: $description, steps_json: $steps_json,
                        embedding: $embedding, embedding_model: $embedding_model,
                        embedding_dim: $embedding_dim,
                        success_count: 0, application_count: 0, success_rate: 0.0,
                        confidence: $confidence, pathway_strength: $pathway_strength,
                        archived: false, created_at: timestamp($now),
                        trigger_pattern: $trigger_pattern,
                        trigger_hook_type: $trigger_hook_type,
                        trigger_tool: $trigger_tool,
                        trigger_project_scope: $trigger_scope
                    })
                    """,
                    {
                        "pid": proc_id, "name": name,
                        "description": description, "steps_json": steps_json,
                        "embedding": proc_emb, "embedding_model": embedding_model,
                        "embedding_dim": len(proc_emb),
                        "confidence": candidate.get("validation_confidence", 0.5),
                        "pathway_strength": 0.6 if not confidence_low else 0.4,
                        "now": now, "trigger_pattern": pattern,
                        "trigger_hook_type": hook_type, "trigger_tool": tool,
                        "trigger_scope": "",
                    },
                )
                _logger.info("[SweepPatterns] created Procedure %s for sequence: %r", proc_id[:8], pattern)
                written += 1

            elif node_type == "Procedure" and node_id:
                await db.execute_write(
                    "MATCH (p:Procedure {procedure_id: $pid}) "
                    "SET p.trigger_pattern = $pattern, "
                    "    p.trigger_hook_type = $hook_type, "
                    "    p.trigger_tool = $tool, "
                    "    p.trigger_project_scope = $scope",
                    {"pid": node_id, "pattern": pattern,
                     "hook_type": hook_type, "tool": tool, "scope": ""},
                )
                written += 1

        except Exception as e:
            _logger.warning("[SweepPatterns] failed to write trigger for %s %s: %s",
                           candidate.get("node_type"), candidate.get("node_id", "new")[:8], e)
            errors += 1

    return written, errors


async def _call_llm(llm_client: Optional[object], prompt: str) -> str:
    """Call the LLM client in a sync/async safe way and return raw text."""
    if llm_client is None:
        return ""
    try:
        if hasattr(llm_client, "achat"):
            res = llm_client.achat([{"role": "user", "content": prompt}])
        else:
            res = llm_client.chat([{"role": "user", "content": prompt}])
        if _asyncio.iscoroutine(res):
            return await res
        return res
    except Exception:
        return ""
