"""Procedure synthesis — Basal Ganglia automation learning.

Synthesize Procedure nodes from clusters of similar successful Plans.
Uses LLM-assisted clustering.
"""
import json
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
        q = (
            "MATCH (p:Plan) WHERE p.valence > $min_valence AND p.status = 'completed' "
            "AND p.strategy IS NOT NULL RETURN DISTINCT p.strategy"
        )
        r = db.execute(q, {"min_valence": min_valence})
    except Exception:
        return 0, 1

    strategies = []
    while r.has_next():
        row = r.get_next()
        s = row[0] or ""
        if s:
            strategies.append(s)

    for strategy in strategies:
        if synthesized >= max_per_sweep:
            break

        try:
            pr = db.execute(
                "MATCH (p:Plan) WHERE p.strategy = $strategy AND p.valence > $min_valence "
                "AND p.status = 'completed' RETURN p.plan_id, p.goal, p.embedding, p.pathway_strength, p.confidence LIMIT 20",
                {"strategy": strategy, "min_valence": min_valence},
            )
        except Exception:
            errors += 1
            continue

        plans = []
        while pr.has_next():
            row = pr.get_next()
            pid = row[0]
            goal = row[1] or ""
            emb_vec = row[2]
            pathway = float(row[3] or 0.0)
            conf = float(row[4] or 0.0)
            plans.append({"plan_id": pid, "goal": goal, "emb": emb_vec, "pathway": pathway, "confidence": conf})

        if len(plans) < min_cluster:
            continue

        # Basal Ganglia: skip if an automation Procedure already exists for this strategy
        try:
            dup_check = db.execute(
                "MATCH (p:Procedure) WHERE p.archetype = $strategy AND p.archived = false "
                "RETURN count(p) > 0",
                {"strategy": strategy},
            )
            if dup_check.has_next() and dup_check.get_next()[0]:
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
            await db.execute_write(
                """
                CREATE (pr:Procedure {
                    procedure_id: $pid,
                    name: $name,
                    domain: $domain,
                    archetype: $archetype,
                    description: $description,
                    steps_json: $steps_json,
                    embedding: $embedding,
                    embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    success_count: $success_count,
                    application_count: 0,
                    success_rate: 0.0,
                    confidence: $confidence,
                    pathway_strength: $pathway_strength,
                    archived: false,
                    created_at: timestamp($now)
                })
                """,
                {
                    "pid": proc_id,
                    "name": proc_obj.get("name", strategy),
                    "domain": proc_obj.get("domain", "planning"),
                    "archetype": "automation",
                    "description": proc_obj.get("description", ""),
                    "steps_json": steps_json,
                    "embedding": proc_emb,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(proc_emb),
                    "success_count": success_count,
                    "confidence": avg_conf,
                    "pathway_strength": pathway_strength,
                    "now": now,
                },
            )

            # Link Procedure -> Plan (DISTILLED_FROM)
            for p in plans:
                try:
                    await db.execute_write(
                        "MATCH (pr:Procedure {procedure_id: $pid}), (pl:Plan {plan_id: $plan_id}) "
                        "MERGE (pr)-[r:DISTILLED_FROM]->(pl) "
                        "ON CREATE SET r.synthesized_at = timestamp($now)",
                        {"pid": proc_id, "plan_id": p["plan_id"], "now": now},
                    )
                except Exception:
                    pass

            # Create or MERGE archetype Concept and link
            try:
                concept_id = f"procedure_archetype:{uuid.uuid5(uuid.NAMESPACE_URL, strategy)}"
                await db.execute_write(
                    "MERGE (c:Concept {concept_id: $cid}) "
                    "ON CREATE SET c.text_raw = $text, c.pathway_strength = 0.6, c.archived = false, c.created_at = timestamp($now)",
                    {"cid": concept_id, "text": strategy, "now": now},
                )
                await db.execute_write(
                    "MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) MERGE (pr)-[:APPLIES_TO_ARCHETYPE]->(c)",
                    {"pid": proc_id, "cid": concept_id},
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
