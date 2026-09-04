from __future__ import annotations
"""Procedure synthesis — Basal Ganglia automation learning.

Synthesize Procedure nodes from clusters of similar successful Plans.
Uses LLM-assisted clustering.
"""
import json
from campy.brain.hippocampus.graph.gateway import get_gateway

def _row_val(row, idx: int, key: str):
    if isinstance(row, dict):
        return row.get(key)
    if isinstance(row, (list, tuple)) and idx < len(row):
        return row[idx]
    return getattr(row, key, None)
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

_logger = logging.getLogger(__name__)


async def synthesize_procedures(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    Synthesize Procedure nodes from clusters of similar successful Plans.

    Heuristic: group completed Plans by identical `strategy` string and synthesize
    a Procedure when at least `min_cluster_size` plans share the same strategy.
    This is a pragmatic first-pass implementation of B194 suitable for unit tests.
    """
    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    proc_cfg = config.get("sweep", {}).get("procedural", {})
    min_cluster = int(proc_cfg.get("min_cluster_size", 2))
    min_valence = float(proc_cfg.get("min_valence", 0.5))
    max_per_sweep = int(proc_cfg.get("max_syntheses_per_sweep", 3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    try:
        gw = get_gateway(db)
        rows = gw.run_sync("basal_ganglia.synthesis_get_distinct_strategies", min_valence=min_valence)
    except Exception:
        return 0, 1

    strategies = []
    for row in rows:
        s = _row_val(row, 0, "p.strategy") or _row_val(row, 0, "strategy") or ""
        if s:
            strategies.append(s)

    for strategy in strategies:
        if synthesized >= max_per_sweep:
            break

        try:
            p_rows = gw.run_sync(
                "basal_ganglia.synthesis_get_plans_for_strategy",
                strategy=strategy,
                min_valence=min_valence,
            )
        except Exception:
            errors += 1
            continue

        plans = []
        for row in p_rows:
            pid = _row_val(row, 0, "p.plan_id") or _row_val(row, 0, "plan_id")
            goal = _row_val(row, 1, "p.goal") or _row_val(row, 1, "goal") or ""
            emb_vec = _row_val(row, 2, "p.embedding") or _row_val(row, 2, "embedding")
            pathway = float(_row_val(row, 3, "p.pathway_strength") or _row_val(row, 3, "pathway_strength") or 0.0)
            conf = float(_row_val(row, 4, "p.confidence") or _row_val(row, 4, "confidence") or 0.0)
            plans.append({"plan_id": pid, "goal": goal, "emb": emb_vec, "pathway": pathway, "confidence": conf})

        if len(plans) < min_cluster:
            continue

        # Basal Ganglia: skip if an automation Procedure already exists for this strategy
        try:
            dup_rows = gw.run_sync(
                "basal_ganglia.synthesis_check_existing_procedure",
                strategy=strategy,
            )
            if dup_rows and (_row_val(dup_rows[0], 0, "count(p) > 0") or False):
                continue
        except Exception:
            pass

        # Build prompt and call LLM
        excerpts = "\n\n".join(f"- Goal: {p['goal']}" for p in plans)
        prompt = (
            f"Synthesize a reusable, parameterized Procedure template from these successful Plans "
            f"(strategy='{strategy}').\n\nPlans:\n{excerpts}\n\n"
            "Return a JSON object with keys: name (string), description (string), steps (array of {step, precondition, action, expected_outcome}). "
            "Keep steps concise (3-8 steps)."
        )

        raw = await _call_llm(llm_client, prompt)
        if not raw:
            # no LLM output — skip
            continue

        try:
            proc_obj = json.loads(raw)
        except Exception:
            # Fallback: create a minimal procedure from the strategy string
            proc_obj = {
                "name": strategy,
                "description": f"Procedure synthesized from plans using strategy '{strategy}'",
                "steps": [{"step": strategy, "precondition": "", "action": strategy, "expected_outcome": ""}],
            }

        # Prepare Procedure node params
        proc_text = proc_obj.get("description") or proc_obj.get("name") or strategy
        try:
            from campy.brain.hippocampus.graph.embeddings import embed
            proc_emb = embed(proc_text, model_name=embedding_model)
        except Exception:
            proc_emb = [0.0] * 384

        proc_id = str(uuid.uuid4())
        steps_json = json.dumps(proc_obj.get("steps", []))
        success_count = len(plans)
        avg_conf = sum(p.get("confidence", 0.0) for p in plans) / len(plans)
        max_path = max(p.get("pathway", 0.0) for p in plans)
        pathway_strength = min(1.0, max_path * 1.1)

        try:
            await gw.run(
                "basal_ganglia.synthesis_create_procedure",
                pid=proc_id,
                name=proc_obj.get("name", strategy),
                domain=proc_obj.get("domain", "planning"),
                archetype="automation",
                description=proc_obj.get("description", ""),
                steps_json=steps_json,
                embedding=proc_emb,
                embedding_model=embedding_model,
                embedding_dim=len(proc_emb),
                success_count=success_count,
                confidence=avg_conf,
                pathway_strength=pathway_strength,
                now=now,
            )

            # Link Procedure -> Plan (DISTILLED_FROM)
            for p in plans:
                try:
                    await gw.run(
                        "basal_ganglia.synthesis_link_distilled_from",
                        pid=proc_id,
                        plan_id=p["plan_id"],
                        now=now,
                    )
                except Exception:
                    pass

            # Upsert archetype Concept and link
            try:
                concept_id = f"procedure_archetype:{uuid.uuid5(uuid.NAMESPACE_URL, strategy)}"
                await gw.run(
                    "basal_ganglia.synthesis_merge_archetype_concept",
                    cid=concept_id,
                    text=strategy,
                    now=now,
                )
                await gw.run(
                    "basal_ganglia.synthesis_link_applies_to_archetype",
                    pid=proc_id,
                    cid=concept_id,
                )
            except Exception:
                pass

            synthesized += 1
        except Exception:
            errors += 1

    return synthesized, errors


async def _call_llm(llm_client: Optional[object], prompt: str) -> str:
    """Helper to call LLM client."""
    if not llm_client:
        return ""
    try:
        res = llm_client.chat([{"role": "user", "content": prompt}])
        if __import__("asyncio").iscoroutine(res):
            return await res
        return res
    except Exception:
        return ""
