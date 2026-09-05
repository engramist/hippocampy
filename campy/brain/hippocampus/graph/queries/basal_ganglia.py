"""basal_ganglia.py — named queries for Basal Ganglia automation, frustration clusters, maturity, and reward prediction."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

BASAL_GANGLIA_QUERIES: tuple[NamedQuery, ...] = (
    # procedure_synthesis.py
    NamedQuery(
        name="basal_ganglia.synthesis_get_distinct_strategies",
        cypher="MATCH (p:Plan) WHERE p.valence > $min_valence AND p.status = 'completed' "
               "AND p.strategy IS NOT NULL RETURN DISTINCT p.strategy",
        params=("min_valence",),
        mutating=False,
        description="Get distinct strategies from completed plans with valence > min_valence",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_get_plans_for_strategy",
        cypher="MATCH (p:Plan) WHERE p.strategy = $strategy AND p.valence > $min_valence "
               "AND p.status = 'completed' RETURN p.plan_id, p.goal, p.embedding, p.pathway_strength, p.confidence LIMIT 20",
        params=("strategy", "min_valence"),
        mutating=False,
        description="Get completed plans for strategy",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_check_existing_procedure",
        cypher="MATCH (p:Procedure) WHERE p.archetype = $strategy AND p.archived = false "
               "RETURN count(p) > 0",
        params=("strategy",),
        mutating=False,
        description="Check if procedure exists for archetype strategy",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_create_procedure",
        cypher="CREATE (pr:Procedure {\n"
               "    procedure_id: $pid,\n"
               "    name: $name,\n"
               "    domain: $domain,\n"
               "    archetype: $archetype,\n"
               "    description: $description,\n"
               "    steps_json: $steps_json,\n"
               "    embedding: $embedding,\n"
               "    embedding_model: $embedding_model,\n"
               "    embedding_dim: $embedding_dim,\n"
               "    success_count: $success_count,\n"
               "    application_count: 0,\n"
               "    success_rate: 0.0,\n"
               "    confidence: $confidence,\n"
               "    pathway_strength: $pathway_strength,\n"
               "    archived: false,\n"
               "    created_at: timestamp($now)\n"
               "})",
        params=(
            "pid", "name", "domain", "archetype", "description",
            "steps_json", "embedding", "embedding_model", "embedding_dim",
            "success_count", "confidence", "pathway_strength", "now",
        ),
        mutating=True,
        description="Create synthesized Procedure node from plans",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_link_distilled_from",
        cypher="MATCH (pr:Procedure {procedure_id: $pid}), (pl:Plan {plan_id: $plan_id}) "
               "MERGE (pr)-[r:DISTILLED_FROM]->(pl) "
               "ON CREATE SET r.synthesized_at = timestamp($now)",
        params=("pid", "plan_id", "now"),
        mutating=True,
        description="Link Procedure DISTILLED_FROM Plan",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_merge_archetype_concept",
        cypher="MERGE (c:Concept {concept_id: $cid}) "
               "ON CREATE SET c.text_raw = $text, c.pathway_strength = 0.6, c.archived = false, c.created_at = timestamp($now)",
        params=("cid", "text", "now"),
        mutating=True,
        description="Merge archetype Concept node",
    ),
    NamedQuery(
        name="basal_ganglia.synthesis_link_applies_to_archetype",
        cypher="MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) "
               "MERGE (pr)-[:APPLIES_TO_ARCHETYPE]->(c)",
        params=("pid", "cid"),
        mutating=True,
        description="Link Procedure APPLIES_TO_ARCHETYPE Concept",
    ),

    # frustration_clusters.py
    NamedQuery(
        name="basal_ganglia.frustration_get_concept",
        cypher="MATCH (n:Concept) WHERE n.archived = false "
               "  AND n.salience_score >= $floor "
               "RETURN n.concept_id AS id, n.text_raw AS name, "
               "  coalesce(n.text_raw, '') AS description, n.embedding AS emb, "
               "  n.salience_score AS salience "
               "ORDER BY n.salience_score DESC LIMIT 50",
        params=("floor",),
        mutating=False,
        description="Get Concept nodes for frustration cluster detection",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_get_decision",
        cypher="MATCH (n:Decision) WHERE n.archived = false "
               "  AND n.salience_score >= $floor "
               "RETURN n.decision_id AS id, n.text_raw AS name, "
               "  coalesce(n.text_raw, '') AS description, n.embedding AS emb, "
               "  n.salience_score AS salience "
               "ORDER BY n.salience_score DESC LIMIT 50",
        params=("floor",),
        mutating=False,
        description="Get Decision nodes for frustration cluster detection",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_get_constraint",
        cypher="MATCH (n:Constraint) WHERE n.archived = false "
               "  AND n.salience_score >= $floor "
               "RETURN n.constraint_id AS id, n.text_raw AS name, "
               "  coalesce(n.text_raw, '') AS description, n.embedding AS emb, "
               "  n.salience_score AS salience "
               "ORDER BY n.salience_score DESC LIMIT 50",
        params=("floor",),
        mutating=False,
        description="Get Constraint nodes for frustration cluster detection",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_create_procedure",
        cypher="CREATE (pr:Procedure {\n"
               "    procedure_id: $pid, name: $name,\n"
               "    domain: $domain, archetype: $archetype,\n"
               "    description: $description, steps_json: $steps_json,\n"
               "    embedding: $embedding, embedding_model: $embedding_model,\n"
               "    embedding_dim: $embedding_dim,\n"
               "    success_count: 0, application_count: 0, success_rate: 0.0,\n"
               "    salience_score: $salience_score,\n"
               "    confidence: $confidence, pathway_strength: $pathway_strength,\n"
               "    maturity_stage: 'nascent',\n"
               "    archived: false, created_at: timestamp($now)\n"
               "})",
        params=(
            "pid", "name", "domain", "archetype", "description", "steps_json",
            "embedding", "embedding_model", "embedding_dim",
            "salience_score", "confidence", "pathway_strength", "now",
        ),
        mutating=True,
        description="Create avoidance Procedure node from frustration cluster",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_link_distilled_from_concept",
        cypher="MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) "
               "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
               "ON CREATE SET r.synthesized_at = timestamp($now)",
        params=("pid", "cid", "now"),
        mutating=True,
        description="Link Procedure DISTILLED_FROM Concept",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_link_distilled_from_decision",
        cypher="MATCH (pr:Procedure {procedure_id: $pid}), (c:Decision {decision_id: $cid}) "
               "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
               "ON CREATE SET r.synthesized_at = timestamp($now)",
        params=("pid", "cid", "now"),
        mutating=True,
        description="Link Procedure DISTILLED_FROM Decision",
    ),
    NamedQuery(
        name="basal_ganglia.frustration_link_distilled_from_constraint",
        cypher="MATCH (pr:Procedure {procedure_id: $pid}), (c:Constraint {constraint_id: $cid}) "
               "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
               "ON CREATE SET r.synthesized_at = timestamp($now)",
        params=("pid", "cid", "now"),
        mutating=True,
        description="Link Procedure DISTILLED_FROM Constraint",
    ),

    # procedure_maturity.py
    NamedQuery(
        name="basal_ganglia.maturity_get_procedures",
        cypher="MATCH (p:Procedure) WHERE p.archived = false "
               "RETURN p.procedure_id, p.application_count, p.success_rate, p.maturity_stage",
        params=(),
        mutating=False,
        description="Get active procedures for maturity update",
    ),
    NamedQuery(
        name="basal_ganglia.maturity_update_stage",
        cypher="MATCH (p:Procedure {procedure_id: $pid}) SET p.maturity_stage = $stage",
        params=("pid", "stage"),
        mutating=True,
        description="Update procedure maturity stage",
    ),

    # reward_predictor.py
    NamedQuery(
        name="basal_ganglia.record_prediction_error",
        cypher="MATCH (p:Plan {plan_id: $plan_id}) "
               "SET p.predicted_valence = $predicted, "
               "    p.actual_valence = $actual, "
               "    p.prediction_error = $error",
        params=("plan_id", "predicted", "actual", "error"),
        mutating=True,
        description="Record reward prediction error on Plan node",
    ),
)
