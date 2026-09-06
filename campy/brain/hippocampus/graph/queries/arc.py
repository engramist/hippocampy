"""
campy/brain/hippocampus/graph/queries/arc.py — B314 named-query slice.

Holds queries migrated out of `arc_queries.py`'s inline Cypher, one card at
a time (B363's `VictoryCondition` merge, B369's `InvestigationThread`
read/create/link queries) — not a full migration of that file, just what
each card actually touched. New code in `arc_queries.py` is written as a
NamedQuery from the start rather than inline, to stay under the Cypher
ratchet (scripts/check_cypher_ratchet.py). See B314's card for the full
rationale.

Naming convention: `arc.<verb>_<subject>`.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

ARC_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="arc.merge_victory_condition_confidence",
        cypher="""
            MERGE (vc:VictoryCondition {condition_id: $gid})
            SET vc.task_id = $tid, vc.confidence = $conf,
                vc.created_at = coalesce(vc.created_at, current_timestamp()),
                vc.last_updated = current_timestamp()
            """,
        params=("gid", "tid", "conf"),
        mutating=True,
        description=(
            "B363: create-or-update a VictoryCondition's confidence, keyed on "
            "condition_id. Previously a bare MATCH silently no-op'd against a "
            "condition_id with no existing node."
        ),
        sparql="""
            DELETE {
                ?vc campy:task_id ?old_task_id .
                ?vc campy:confidence ?old_confidence .
                ?vc campy:created_at ?old_created_at .
                ?vc campy:last_updated ?old_last_updated .
            }
            INSERT {
                ?vc a campy:VictoryCondition ;
                    campy:condition_id ?gid ;
                    campy:task_id ?tid ;
                    campy:confidence ?conf ;
                    campy:created_at ?created_at_val ;
                    campy:last_updated ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "VictoryCondition/", ENCODE_FOR_URI(?gid))) AS ?vc)
                BIND(NOW() AS ?now)
                OPTIONAL { ?vc campy:task_id ?old_task_id }
                OPTIONAL { ?vc campy:confidence ?old_confidence }
                OPTIONAL { ?vc campy:created_at ?old_created_at }
                OPTIONAL { ?vc campy:last_updated ?old_last_updated }
                BIND(COALESCE(?old_created_at, ?now) AS ?created_at_val)
            }
            """,
    ),
    # B369 — arc_start_or_resume_thread (investigation-thread durability for
    # ARC_AGI's trajectory Annatar). Written as NamedQuery from the start
    # (new code, not a migration) to stay under the Cypher ratchet.
    NamedQuery(
        name="arc.fetch_investigation_thread_state",
        cypher="MATCH (t:InvestigationThread {thread_id: $tid}) RETURN t.state",
        params=("tid",),
        mutating=False,
        description="B369: O(1) primary-key lookup for arc_start_or_resume_thread's resume check.",
        sparql="""
            SELECT ?tid ?state WHERE {
                ?t a campy:InvestigationThread ;
                   campy:thread_id ?tid ;
                   campy:state ?state .
            }
            """,
    ),
    NamedQuery(
        name="arc.reopen_investigation_thread",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid})
            SET t.state = 'exploring', t.state_updated_at = current_timestamp()
            """,
        params=("tid",),
        mutating=True,
        description="B369: reset a terminal (satisfied/exhausted) thread to a fresh 'exploring' start.",
        sparql="""
            DELETE {
                ?t campy:state ?old_state .
                ?t campy:state_updated_at ?old_state_updated_at .
            }
            INSERT {
                ?t campy:state "exploring" ;
                   campy:state_updated_at ?now .
            }
            WHERE {
                ?t a campy:InvestigationThread ;
                   campy:thread_id ?tid .
                BIND(NOW() AS ?now)
                OPTIONAL { ?t campy:state ?old_state }
                OPTIONAL { ?t campy:state_updated_at ?old_state_updated_at }
            }
            """,
    ),
    NamedQuery(
        name="arc.create_investigation_thread",
        cypher="""
            MERGE (t:InvestigationThread {thread_id: $tid})
            SET t.task_id = $task, t.anchor_ref = $aref, t.anchor_type = $atype,
                t.state = 'exploring', t.state_updated_at = current_timestamp(),
                t.created_at = current_timestamp()
            """,
        params=("tid", "task", "aref", "atype"),
        mutating=True,
        description="B369: create a brand-new InvestigationThread in state 'exploring'.",
        sparql="""
            DELETE {
                ?t campy:task_id ?old_task .
                ?t campy:anchor_ref ?old_aref .
                ?t campy:anchor_type ?old_atype .
                ?t campy:state ?old_state .
                ?t campy:state_updated_at ?old_supdated .
            }
            INSERT {
                ?t a campy:InvestigationThread ;
                   campy:thread_id ?tid ;
                   campy:task_id ?task ;
                   campy:anchor_ref ?aref ;
                   campy:anchor_type ?atype ;
                   campy:state "exploring" ;
                   campy:state_updated_at ?now ;
                   campy:created_at ?created_at_val .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "InvestigationThread/", ENCODE_FOR_URI(?tid))) AS ?t)
                BIND(NOW() AS ?now)
                OPTIONAL { ?t campy:task_id ?old_task }
                OPTIONAL { ?t campy:anchor_ref ?old_aref }
                OPTIONAL { ?t campy:anchor_type ?old_atype }
                OPTIONAL { ?t campy:state ?old_state }
                OPTIONAL { ?t campy:state_updated_at ?old_supdated }
                OPTIONAL { ?t campy:created_at ?existing_created_at }
                BIND(COALESCE(?existing_created_at, ?now) AS ?created_at_val)
            }
            """,
    ),
    NamedQuery(
        name="arc.link_thread_to_entity_anchor",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid}),
                  (ge:GridEntity {task_id: $task, region_index: $eref})
            WITH t, ge LIMIT 1
            MERGE (t)-[:ANCHORED_ON_ENTITY]->(ge)
            """,
        params=("tid", "task", "eref"),
        mutating=True,
        description=(
            "B369: best-effort ANCHORED_ON_ENTITY edge -- no-ops if the GridEntity "
            "doesn't exist yet."
        ),
        sparql="""
            INSERT {
                ?t campy:ANCHORED_ON_ENTITY ?ge .
            }
            WHERE {
                ?t a campy:InvestigationThread ;
                   campy:thread_id ?tid .
                ?ge a campy:GridEntity ;
                    campy:task_id ?task ;
                    campy:region_index ?eref .
            }
            """,
    ),
    NamedQuery(
        name="arc.link_thread_to_goal_anchor",
        cypher="""
            MATCH (t:InvestigationThread {thread_id: $tid}), (h:Hypothesis {id: $hid})
            WITH t, h LIMIT 1
            MERGE (t)-[:ANCHORED_ON_GOAL]->(h)
            """,
        params=("tid", "hid"),
        mutating=True,
        description=(
            "B369: best-effort ANCHORED_ON_GOAL edge -- no-ops if the Hypothesis "
            "doesn't exist yet."
        ),
        sparql="""
            INSERT {
                ?t campy:ANCHORED_ON_GOAL ?h .
            }
            WHERE {
                ?t a campy:InvestigationThread ;
                   campy:thread_id ?tid .
                ?h a campy:Hypothesis ;
                   campy:id ?hid .
            }
            """,
    ),
    # B372 — arc_perceive_state's new disappeared_entities handling (ARC_AGI's
    # A221 Finding 2). Written as NamedQuery from the start to stay under the
    # Cypher ratchet.
    NamedQuery(
        name="arc.record_entity_disappearance",
        cypher="""
            MERGE (d:EntityDisappearance {disappearance_id: $did})
            SET d.task_id = $task, d.entity_id = $eid, d.region_index = $ridx,
                d.color_id = $cid, d.step = $step, d.centroid_row = $cr,
                d.centroid_col = $cc, d.pixel_count = $pc,
                d.created_at = current_timestamp()
            """,
        params=("did", "task", "eid", "ridx", "cid", "step", "cr", "cc", "pc"),
        mutating=True,
        description=(
            "B372: one row per observed disappearance (task_id, entity, step) -- "
            "deliberately event-style, never merged/updated per-entity, so a later "
            "reappearance doesn't overwrite an earlier disappearance's history."
        ),
        sparql="""
            INSERT {
                ?d a campy:EntityDisappearance ;
                   campy:disappearance_id ?did ;
                   campy:task_id ?task ;
                   campy:entity_id ?eid ;
                   campy:region_index ?ridx ;
                   campy:color_id ?cid ;
                   campy:step ?step ;
                   campy:centroid_row ?cr ;
                   campy:centroid_col ?cc ;
                   campy:pixel_count ?pc ;
                   campy:created_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "EntityDisappearance/", ENCODE_FOR_URI(?did))) AS ?d)
                BIND(NOW() AS ?now)
            }
            """,
    ),
    NamedQuery(
        name="arc.link_entity_disappearance",
        cypher="""
            MATCH (e:GridEntity {entity_id: $eid}), (d:EntityDisappearance {disappearance_id: $did})
            WITH e, d LIMIT 1
            MERGE (e)-[:DISAPPEARED]->(d)
            """,
        params=("eid", "did"),
        mutating=True,
        description=(
            "B372: best-effort DISAPPEARED edge -- in practice the GridEntity should "
            "always already exist (disappearance implies a prior frame observed it), "
            "but no-ops rather than errors if it somehow doesn't, matching this file's "
            "existing best-effort-edge convention."
        ),
        sparql="""
            INSERT {
                ?e campy:DISAPPEARED ?d .
            }
            WHERE {
                ?e a campy:GridEntity ; campy:entity_id ?eid .
                ?d a campy:EntityDisappearance ; campy:disappearance_id ?did .
            }
            """,
    ),
    # arc_queries.py migrated queries
    NamedQuery(
        name="arc.merge_snapshot",
        cypher="""
            MERGE (s:GridSnapshot {snapshot_id: $sid})
            SET s.task_id = $tid, s.step = $step, s.grid_hash = $hash,
                s.n_entities = $n, s.created_at = current_timestamp()
            """,
        params=("sid", "tid", "step", "hash", "n"),
        mutating=True,
        description="Record or update a GridSnapshot node.",
        sparql="""
            DELETE {
                ?s campy:task_id ?old_task_id .
                ?s campy:step ?old_step .
                ?s campy:grid_hash ?old_grid_hash .
                ?s campy:n_entities ?old_n_entities .
                ?s campy:created_at ?old_created_at .
            }
            INSERT {
                ?s a campy:GridSnapshot ;
                   campy:snapshot_id ?sid ;
                   campy:task_id ?tid ;
                   campy:step ?step ;
                   campy:grid_hash ?hash ;
                   campy:n_entities ?n ;
                   campy:created_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "GridSnapshot/", ENCODE_FOR_URI(?sid))) AS ?s)
                BIND(NOW() AS ?now)
                OPTIONAL { ?s campy:task_id ?old_task_id }
                OPTIONAL { ?s campy:step ?old_step }
                OPTIONAL { ?s campy:grid_hash ?old_grid_hash }
                OPTIONAL { ?s campy:n_entities ?old_n_entities }
                OPTIONAL { ?s campy:created_at ?old_created_at }
            }
            """,
    ),
    NamedQuery(
        name="arc.get_entity_centroid",
        cypher="MATCH (e:GridEntity {entity_id: $eid}) RETURN e.centroid_row, e.centroid_col",
        params=("eid",),
        mutating=False,
        description="Fetch centroid coordinates for an existing GridEntity.",
        sparql="""
            SELECT ?centroid_row ?centroid_col WHERE {
                ?e a campy:GridEntity ;
                   campy:entity_id ?eid ;
                   campy:centroid_row ?centroid_row ;
                   campy:centroid_col ?centroid_col .
            }
            """,
    ),
    NamedQuery(
        name="arc.merge_entity",
        cypher="""
            MERGE (e:GridEntity {entity_id: $eid})
            SET e.task_id = $tid, e.color_id = $cid, e.region_index = $ridx,
                e.centroid_row = $cr, e.centroid_col = $cc,
                e.pixel_count = $pc, e.inferred_role = $role,
                e.last_updated_step = $step
            """,
        params=("eid", "tid", "cid", "ridx", "cr", "cc", "pc", "role", "step"),
        mutating=True,
        description="Record or update a GridEntity node.",
        sparql="""
            DELETE {
                ?e campy:task_id ?old_task_id .
                ?e campy:color_id ?old_color_id .
                ?e campy:region_index ?old_region_index .
                ?e campy:centroid_row ?old_centroid_row .
                ?e campy:centroid_col ?old_centroid_col .
                ?e campy:pixel_count ?old_pixel_count .
                ?e campy:inferred_role ?old_inferred_role .
                ?e campy:last_updated_step ?old_last_updated_step .
            }
            INSERT {
                ?e a campy:GridEntity ;
                   campy:entity_id ?eid ;
                   campy:task_id ?tid ;
                   campy:color_id ?cid ;
                   campy:region_index ?ridx ;
                   campy:centroid_row ?cr ;
                   campy:centroid_col ?cc ;
                   campy:pixel_count ?pc ;
                   campy:inferred_role ?role ;
                   campy:last_updated_step ?step .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "GridEntity/", ENCODE_FOR_URI(?eid))) AS ?e)
                OPTIONAL { ?e campy:task_id ?old_task_id }
                OPTIONAL { ?e campy:color_id ?old_color_id }
                OPTIONAL { ?e campy:region_index ?old_region_index }
                OPTIONAL { ?e campy:centroid_row ?old_centroid_row }
                OPTIONAL { ?e campy:centroid_col ?old_centroid_col }
                OPTIONAL { ?e campy:pixel_count ?old_pixel_count }
                OPTIONAL { ?e campy:inferred_role ?old_inferred_role }
                OPTIONAL { ?e campy:last_updated_step ?old_last_updated_step }
            }
            """,
    ),
    NamedQuery(
        name="arc.merge_action_effect_action",
        cypher="""
            MERGE (ae:ActionEffect {effect_id: $eid})
            SET ae.task_id = $tid, ae.action_id = $aid, ae.step = $step,
                ae.n_cells_changed = $ncc, ae.apparent_effect = $eff
            """,
        params=("eid", "tid", "aid", "step", "ncc", "eff"),
        mutating=True,
        description="Record an ActionEffect with action and effect details.",
        sparql="""
            DELETE {
                ?ae campy:task_id ?old_task_id .
                ?ae campy:action_id ?old_action_id .
                ?ae campy:step ?old_step .
                ?ae campy:n_cells_changed ?old_ncc .
                ?ae campy:apparent_effect ?old_eff .
            }
            INSERT {
                ?ae a campy:ActionEffect ;
                    campy:effect_id ?eid ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:step ?step ;
                    campy:n_cells_changed ?ncc ;
                    campy:apparent_effect ?eff .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ActionEffect/", ENCODE_FOR_URI(?eid))) AS ?ae)
                OPTIONAL { ?ae campy:task_id ?old_task_id }
                OPTIONAL { ?ae campy:action_id ?old_action_id }
                OPTIONAL { ?ae campy:step ?old_step }
                OPTIONAL { ?ae campy:n_cells_changed ?old_ncc }
                OPTIONAL { ?ae campy:apparent_effect ?old_eff }
            }
            """,
    ),
    NamedQuery(
        name="arc.merge_action_effect_moved",
        cypher="""
            MERGE (ae:ActionEffect {effect_id: $eid})
            SET ae.task_id = $tid, ae.step = $step
            """,
        params=("eid", "tid", "step"),
        mutating=True,
        description="Anchor ActionEffect for entity movement without action_taken.",
        sparql="""
            DELETE {
                ?ae campy:task_id ?old_task_id .
                ?ae campy:step ?old_step .
            }
            INSERT {
                ?ae a campy:ActionEffect ;
                    campy:effect_id ?eid ;
                    campy:task_id ?tid ;
                    campy:step ?step .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ActionEffect/", ENCODE_FOR_URI(?eid))) AS ?ae)
                OPTIONAL { ?ae campy:task_id ?old_task_id }
                OPTIONAL { ?ae campy:step ?old_step }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_entity_moved_by",
        cypher="""
            MATCH (e:GridEntity {entity_id: $eid}), (ae:ActionEffect {effect_id: $aeid})
            MERGE (e)-[m:MOVED_BY]->(ae)
            SET m.delta_row = $dr, m.delta_col = $dc
            """,
        params=("eid", "aeid", "dr", "dc"),
        mutating=True,
        description="Link GridEntity to ActionEffect with delta row and col.",
    ),
    NamedQuery(
        name="arc.count_active_hypotheses",
        cypher="MATCH (h:Hypothesis {task_id: $tid}) WHERE h.status = 'active' RETURN count(h)",
        params=("tid",),
        mutating=False,
        description="Count active hypotheses for a task.",
        sparql="""
            SELECT (COUNT(?h) AS ?count) WHERE {
                ?h a campy:Hypothesis ;
                   campy:task_id ?tid ;
                   campy:status "active" .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_max_snapshot_step",
        cypher="MATCH (s:GridSnapshot {task_id: $tid}) RETURN max(s.step)",
        params=("tid",),
        mutating=False,
        description="Get maximum snapshot step for a task.",
        sparql="""
            SELECT (MAX(?step) AS ?max_step) WHERE {
                ?s a campy:GridSnapshot ;
                   campy:task_id ?tid ;
                   campy:step ?step .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_action_facts_summary",
        cypher="MATCH (af:ActionFact {task_id: $tid}) RETURN af.action_id, af.value_status, af.confidence",
        params=("tid",),
        mutating=False,
        description="Fetch ActionFact summary for a task.",
        sparql="""
            SELECT ?action_id ?value_status ?confidence WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?action_id .
                OPTIONAL { ?af campy:value_status ?value_status }
                OPTIONAL { ?af campy:confidence ?confidence }
            }
            """,
    ),
    NamedQuery(
        name="arc.get_action_fact_detail",
        cypher="""
            MATCH (af:ActionFact {task_id: $tid, action_id: $aid})
            RETURN af.fact_id, af.value_status, af.confidence, af.evidence_summary,
                   af.sample_count, af.last_tested_step, af.recommended_next
            """,
        params=("tid", "aid"),
        mutating=False,
        description="Fetch detailed ActionFact fields.",
        sparql="""
            SELECT ?fact_id ?value_status ?confidence ?evidence_summary ?sample_count ?last_tested_step ?recommended_next WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:fact_id ?fact_id .
                OPTIONAL { ?af campy:value_status ?value_status }
                OPTIONAL { ?af campy:confidence ?confidence }
                OPTIONAL { ?af campy:evidence_summary ?evidence_summary }
                OPTIONAL { ?af campy:sample_count ?sample_count }
                OPTIONAL { ?af campy:last_tested_step ?last_tested_step }
                OPTIONAL { ?af campy:recommended_next ?recommended_next }
            }
            """,
    ),
    NamedQuery(
        name="arc.get_distinct_action_ids",
        cypher="MATCH (af:ActionFact {task_id: $tid}) RETURN DISTINCT af.action_id",
        params=("tid",),
        mutating=False,
        description="Fetch distinct action IDs for a task.",
        sparql="""
            SELECT DISTINCT ?action_id WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?action_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.query_causal_chain_with_goal",
        cypher="""
            MATCH (af:ActionFact {task_id: $tid, action_id: $aid})-[:DERIVED_FROM_FACT]->(ae:ActionEffect)
            <-[:MOVED_BY]-(ge:GridEntity)-[:REQUIRES_ENTITY]-(vc:VictoryCondition {task_id: $tid, condition_id: $gid})
            RETURN count(af) as path_count, min(vc.confidence) as min_conf
            """,
        params=("tid", "aid", "gid"),
        mutating=False,
        description="Find causal paths connecting action fact to a goal condition.",
        sparql="""
            SELECT (COUNT(?af) AS ?path_count) (MIN(?conf) AS ?min_conf) WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:DERIVED_FROM_FACT ?ae .
                ?ge campy:MOVED_BY ?ae .
                ?ge (campy:REQUIRES_ENTITY|^campy:REQUIRES_ENTITY) ?vc .
                ?vc a campy:VictoryCondition ;
                    campy:task_id ?tid ;
                    campy:condition_id ?gid ;
                    campy:confidence ?conf .
            }
            """,
    ),
    NamedQuery(
        name="arc.query_causal_chain",
        cypher="""
            MATCH (af:ActionFact {task_id: $tid, action_id: $aid})-[:DERIVED_FROM_FACT]->(ae:ActionEffect)
            <-[:MOVED_BY]-(ge:GridEntity)-[:REQUIRES_ENTITY]-(vc:VictoryCondition {task_id: $tid})
            RETURN count(af) as path_count, min(vc.confidence) as min_conf
            """,
        params=("tid", "aid"),
        mutating=False,
        description="Find causal paths connecting action fact to any victory condition.",
        sparql="""
            SELECT (COUNT(?af) AS ?path_count) (MIN(?conf) AS ?min_conf) WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:DERIVED_FROM_FACT ?ae .
                ?ge campy:MOVED_BY ?ae .
                ?ge (campy:REQUIRES_ENTITY|^campy:REQUIRES_ENTITY) ?vc .
                ?vc a campy:VictoryCondition ;
                    campy:task_id ?tid ;
                    campy:confidence ?conf .
            }
            """,
    ),
    NamedQuery(
        name="arc.record_action_effect_simple",
        cypher="""
            MERGE (ae:ActionEffect {effect_id: $eid})
            SET ae.task_id = $tid, ae.action_id = $aid, ae.step = $step,
                ae.n_cells_changed = $ncc, ae.apparent_effect = $eff, ae.created_at = current_timestamp()
            """,
        params=("eid", "tid", "aid", "step", "ncc", "eff"),
        mutating=True,
        description="Record an ActionEffect with cell changes and apparent effect.",
        sparql="""
            DELETE {
                ?ae campy:task_id ?old_task_id .
                ?ae campy:action_id ?old_action_id .
                ?ae campy:step ?old_step .
                ?ae campy:n_cells_changed ?old_ncc .
                ?ae campy:apparent_effect ?old_eff .
                ?ae campy:created_at ?old_created_at .
            }
            INSERT {
                ?ae a campy:ActionEffect ;
                    campy:effect_id ?eid ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:step ?step ;
                    campy:n_cells_changed ?ncc ;
                    campy:apparent_effect ?eff ;
                    campy:created_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ActionEffect/", ENCODE_FOR_URI(?eid))) AS ?ae)
                BIND(NOW() AS ?now)
                OPTIONAL { ?ae campy:task_id ?old_task_id }
                OPTIONAL { ?ae campy:action_id ?old_action_id }
                OPTIONAL { ?ae campy:step ?old_step }
                OPTIONAL { ?ae campy:n_cells_changed ?old_ncc }
                OPTIONAL { ?ae campy:apparent_effect ?old_eff }
                OPTIONAL { ?ae campy:created_at ?old_created_at }
            }
            """,
    ),
    NamedQuery(
        name="arc.increment_action_fact_observation",
        cypher="""
            MERGE (af:ActionFact {fact_id: $fid})
            SET af.task_id = $tid, af.action_id = $aid,
                af.observation_count = coalesce(af.observation_count, 0) + 1,
                af.last_updated = current_timestamp()
            """,
        params=("fid", "tid", "aid"),
        mutating=True,
        description="Record or increment observation count on an ActionFact.",
        sparql="""
            DELETE {
                ?af campy:task_id ?old_task_id .
                ?af campy:action_id ?old_action_id .
                ?af campy:observation_count ?old_observation_count .
                ?af campy:last_updated ?old_last_updated .
            }
            INSERT {
                ?af a campy:ActionFact ;
                    campy:fact_id ?fid ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid ;
                    campy:observation_count ?new_observation_count ;
                    campy:last_updated ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ActionFact/", ENCODE_FOR_URI(?fid))) AS ?af)
                BIND(NOW() AS ?now)
                OPTIONAL { ?af campy:task_id ?old_task_id }
                OPTIONAL { ?af campy:action_id ?old_action_id }
                OPTIONAL { ?af campy:observation_count ?old_observation_count }
                OPTIONAL { ?af campy:last_updated ?old_last_updated }
                BIND(STRDT(STR(COALESCE(?old_observation_count, 0) + 1), xsd:int) AS ?new_observation_count)
            }
            """,
    ),
    NamedQuery(
        name="arc.get_entity_movement",
        cypher="""
            MATCH (ge:GridEntity {task_id: $tid})-[m:MOVED_BY]->(ae:ActionEffect {step: $step})
            RETURN ge.entity_id, m.delta_row, m.delta_col
            """,
        params=("tid", "step"),
        mutating=False,
        description="Fetch entity movement at a step.",
        sparql="""
            SELECT ?entity_id ?delta_row ?delta_col WHERE {
                ?ge a campy:GridEntity ;
                    campy:task_id ?tid ;
                    campy:entity_id ?entity_id ;
                    campy:MOVED_BY ?ae .
                ?ae a campy:ActionEffect ;
                    campy:step ?step .
                << ?ge campy:MOVED_BY ?ae >> campy:delta_row ?delta_row ;
                                              campy:delta_col ?delta_col .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_entity_hypotheses",
        cypher="""
            MATCH (ge:GridEntity {task_id: $tid, region_index: $eref})-[:ENTITY_HYPOTHESIS]->(h:Hypothesis)
            WHERE h.status IS NULL OR h.status <> 'demoted'
            RETURN h.id, h.description, h.confidence, h.status
            """,
        params=("tid", "eref"),
        mutating=False,
        description="Fetch hypotheses linked to an entity.",
        sparql="""
            SELECT ?id ?description ?confidence ?status WHERE {
                ?ge a campy:GridEntity ;
                    campy:task_id ?tid ;
                    campy:region_index ?eref ;
                    campy:ENTITY_HYPOTHESIS ?h .
                ?h a campy:Hypothesis ;
                   campy:id ?id ;
                   campy:description ?description ;
                   campy:confidence ?confidence .
                OPTIONAL { ?h campy:status ?status }
                FILTER(!BOUND(?status) || ?status != "demoted")
            }
            """,
    ),
    NamedQuery(
        name="arc.get_entity_mechanics",
        cypher="""
            MATCH (m:ArcMechanic) WHERE m.source_task_ids CONTAINS $tid
            RETURN m.name, m.confidence
            ORDER BY m.confidence DESC
            """,
        params=("tid",),
        mutating=False,
        description="Fetch mechanics observed in a task.",
        sparql="""
            SELECT ?name ?confidence WHERE {
                ?m a campy:ArcMechanic ;
                   campy:source_task_ids ?source_task_ids ;
                   campy:name ?name ;
                   campy:confidence ?confidence .
                FILTER(CONTAINS(?source_task_ids, ?tid))
            }
            ORDER BY DESC(?confidence)
            """,
    ),
    NamedQuery(
        name="arc.get_entity_rules",
        cypher="""
            MATCH (ge:GridEntity {task_id: $tid, region_index: $eref})-[:ENTITY_RULE]->(r:Rule)
            WHERE r.falsified = false
            RETURN r.rule_id, r.action_family, r.from_color, r.to_color, r.confidence
            """,
        params=("tid", "eref"),
        mutating=False,
        description="Fetch live rules linked to an entity.",
        sparql="""
            SELECT ?rule_id ?action_family ?from_color ?to_color ?confidence WHERE {
                ?ge a campy:GridEntity ;
                    campy:task_id ?tid ;
                    campy:region_index ?eref ;
                    campy:ENTITY_RULE ?r .
                ?r a campy:Rule ;
                   campy:rule_id ?rule_id ;
                   campy:action_family ?action_family ;
                   campy:from_color ?from_color ;
                   campy:to_color ?to_color ;
                   campy:confidence ?confidence ;
                   campy:falsified false .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_goal_evidence",
        cypher="""
            MATCH (vc:VictoryCondition {task_id: $tid})
            OPTIONAL MATCH (vc)<-[s:INFERRED_FROM]-(h:Hypothesis)
            RETURN vc.condition_id, vc.condition_type, vc.confidence,
                   count(CASE WHEN h.status = 'active' THEN 1 END) as supports,
                   count(CASE WHEN h.status = 'demoted' THEN 1 END) as contradicts
            """,
        params=("tid",),
        mutating=False,
        description="Fetch goal evidence with support and contradiction counts.",
        sparql="""
            SELECT ?condition_id ?condition_type ?confidence
                   (SUM(IF(BOUND(?h) && BOUND(?status) && ?status = "active", 1, 0)) AS ?supports)
                   (SUM(IF(BOUND(?h) && BOUND(?status) && ?status = "demoted", 1, 0)) AS ?contradicts)
            WHERE {
                ?vc a campy:VictoryCondition ;
                    campy:task_id ?tid ;
                    campy:condition_id ?condition_id ;
                    campy:condition_type ?condition_type ;
                    campy:confidence ?confidence .
                OPTIONAL {
                    ?h a campy:Hypothesis ;
                       campy:INFERRED_FROM ?vc .
                    OPTIONAL { ?h campy:status ?status }
                }
            }
            GROUP BY ?condition_id ?condition_type ?confidence
            """,
    ),
    NamedQuery(
        name="arc.link_entity_hypothesis",
        cypher="""
            MATCH (ge:GridEntity {task_id: $tid, region_index: $eref}), (h:Hypothesis {id: $hid})
            WITH ge, h LIMIT 1
            MERGE (ge)-[eh:ENTITY_HYPOTHESIS]->(h)
            SET eh.weight = $weight, eh.step = $step
            """,
        params=("tid", "eref", "hid", "weight", "step"),
        mutating=True,
        description="Link entity to hypothesis via ENTITY_HYPOTHESIS.",
    ),
    NamedQuery(
        name="arc.boost_hypothesis_confidence",
        cypher="""
            MATCH (h:Hypothesis) WHERE h.id = $hid
            SET h.evidence_count = coalesce(h.evidence_count, 0) + 1,
                h.confidence = CASE WHEN coalesce(h.confidence, 0.5) + $boost > 1.0 THEN 1.0
                                    ELSE coalesce(h.confidence, 0.5) + $boost END
            """,
        params=("hid", "boost"),
        mutating=True,
        description="Boost hypothesis confidence on confirmation.",
        sparql="""
            DELETE {
                ?h campy:evidence_count ?old_evidence_count .
                ?h campy:confidence ?old_confidence .
            }
            INSERT {
                ?h campy:evidence_count ?new_evidence_count .
                ?h campy:confidence ?new_confidence .
            }
            WHERE {
                ?h a campy:Hypothesis ; campy:id ?hid .
                OPTIONAL { ?h campy:evidence_count ?old_evidence_count }
                OPTIONAL { ?h campy:confidence ?old_confidence }
                BIND(STRDT(STR(COALESCE(?old_evidence_count, 0) + 1), xsd:int) AS ?new_evidence_count)
                BIND((COALESCE(?old_confidence, "0.5"^^xsd:float) + ?boost) AS ?raw_confidence)
                BIND(STRDT(STR(IF(?raw_confidence > "1.0"^^xsd:float, "1.0"^^xsd:float, ?raw_confidence)), xsd:float) AS ?new_confidence)
            }
            """,
    ),
    NamedQuery(
        name="arc.get_hypothesis_confidence",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence",
        params=("hid",),
        mutating=False,
        description="Fetch confidence of a hypothesis.",
        sparql="""
            SELECT ?confidence WHERE {
                ?h a campy:Hypothesis ; campy:id ?hid .
                OPTIONAL { ?h campy:confidence ?confidence }
            }
            """,
    ),
    NamedQuery(
        name="arc.penalize_hypothesis_confidence",
        cypher="""
            MATCH (h:Hypothesis) WHERE h.id = $hid
            SET h.evidence_count = coalesce(h.evidence_count, 0) + 1,
                h.confidence = CASE WHEN coalesce(h.confidence, 0.5) - $penalty < 0.0 THEN 0.0
                                    ELSE coalesce(h.confidence, 0.5) - $penalty END
            """,
        params=("hid", "penalty"),
        mutating=True,
        description="Penalize hypothesis confidence on contradiction.",
        sparql="""
            DELETE {
                ?h campy:evidence_count ?old_evidence_count .
                ?h campy:confidence ?old_confidence .
            }
            INSERT {
                ?h campy:evidence_count ?new_evidence_count .
                ?h campy:confidence ?new_confidence .
            }
            WHERE {
                ?h a campy:Hypothesis ; campy:id ?hid .
                OPTIONAL { ?h campy:evidence_count ?old_evidence_count }
                OPTIONAL { ?h campy:confidence ?old_confidence }
                BIND(STRDT(STR(COALESCE(?old_evidence_count, 0) + 1), xsd:int) AS ?new_evidence_count)
                BIND((COALESCE(?old_confidence, "0.5"^^xsd:float) - ?penalty) AS ?raw_confidence)
                BIND(STRDT(STR(IF(?raw_confidence < "0.0"^^xsd:float, "0.0"^^xsd:float, ?raw_confidence)), xsd:float) AS ?new_confidence)
            }
            """,
    ),
    NamedQuery(
        name="arc.get_hypothesis_confidence_and_status",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence, h.status",
        params=("hid",),
        mutating=False,
        description="Fetch hypothesis confidence and status.",
        sparql="""
            SELECT ?confidence ?status WHERE {
                ?h a campy:Hypothesis ; campy:id ?hid .
                OPTIONAL { ?h campy:confidence ?confidence }
                OPTIONAL { ?h campy:status ?status }
            }
            """,
    ),
    NamedQuery(
        name="arc.demote_hypothesis",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid SET h.status = 'demoted'",
        params=("hid",),
        mutating=True,
        description="Demote a falsified hypothesis.",
        sparql="""
            DELETE { ?h campy:status ?old_status . }
            INSERT { ?h campy:status "demoted" . }
            WHERE {
                ?h a campy:Hypothesis ; campy:id ?hid .
                OPTIONAL { ?h campy:status ?old_status }
            }
            """,
    ),
    NamedQuery(
        name="arc.get_victory_condition_confidence",
        cypher="MATCH (vc:VictoryCondition {condition_id: $gid}) RETURN vc.confidence",
        params=("gid",),
        mutating=False,
        description="Fetch victory condition confidence.",
        sparql="""
            SELECT ?confidence WHERE {
                ?vc a campy:VictoryCondition ; campy:condition_id ?gid ; campy:confidence ?confidence .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_mechanic_priors",
        cypher="""
            MATCH (m:ArcMechanic)-[:ARC_MECHANIC_HAS_ACTION_PATTERN]->(ap:ArcActionPattern)
            WHERE m.confidence > 0.3
            RETURN m.mechanic_id, m.name, m.confidence, ap.signature, ap.action_set
            ORDER BY m.confidence DESC LIMIT 5
            """,
        params=(),
        mutating=False,
        description="Fetch top mechanic priors.",
        sparql="""
            SELECT ?mechanic_id ?name ?confidence ?signature ?action_set WHERE {
                ?m a campy:ArcMechanic ;
                   campy:mechanic_id ?mechanic_id ;
                   campy:name ?name ;
                   campy:confidence ?confidence ;
                   campy:ARC_MECHANIC_HAS_ACTION_PATTERN ?ap .
                ?ap a campy:ArcActionPattern ;
                    campy:signature ?signature ;
                    campy:action_set ?action_set .
                FILTER(?confidence > "0.3"^^xsd:double)
            }
            ORDER BY DESC(?confidence)
            LIMIT 5
            """,
    ),
        NamedQuery(
        name="arc.get_action_evidence",
        cypher="""
            MATCH (af:ActionFact {task_id: $tid, action_id: $aid})
            RETURN af.fact_type, af.confidence, af.value_status, af.evidence_count,
                   af.observation_count, COALESCE(af.falsified_count, 0)
            """,
        params=("tid", "aid"),
        mutating=False,
        description="Fetch action fact evidence metrics.",
        sparql="""
            SELECT ?fact_type ?confidence ?value_status ?evidence_count ?observation_count ?falsified_count WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid .
                OPTIONAL { ?af campy:fact_type ?fact_type }
                OPTIONAL { ?af campy:confidence ?confidence }
                OPTIONAL { ?af campy:value_status ?value_status }
                OPTIONAL { ?af campy:evidence_count ?evidence_count }
                OPTIONAL { ?af campy:observation_count ?observation_count }
                OPTIONAL { ?af campy:falsified_count ?raw_falsified_count }
                BIND(STRDT(STR(COALESCE(?raw_falsified_count, 0)), xsd:int) AS ?falsified_count)
            }
            """,
    ),
NamedQuery(
        name="arc.get_action_gate_fact",
        cypher="""
            MATCH (af:ActionFact {task_id: $tid, action_id: $aid})
            RETURN af.confidence, af.value_status, COALESCE(af.falsified_count, 0),
                   af.observation_count
            """,
        params=("tid", "aid"),
        mutating=False,
        description="Fetch action fact gate metrics.",
        sparql="""
            SELECT ?confidence ?value_status ?falsified_count ?observation_count WHERE {
                ?af a campy:ActionFact ;
                    campy:task_id ?tid ;
                    campy:action_id ?aid .
                OPTIONAL { ?af campy:confidence ?confidence }
                OPTIONAL { ?af campy:value_status ?value_status }
                OPTIONAL { ?af campy:falsified_count ?raw_falsified_count }
                OPTIONAL { ?af campy:observation_count ?observation_count }
                BIND(STRDT(STR(COALESCE(?raw_falsified_count, 0)), xsd:int) AS ?falsified_count)
            }
            """,
    ),
    NamedQuery(
        name="arc.penalize_action_fact_rpe",
        cypher="""
            MATCH (af:ActionFact {fact_id: $fid})
            SET af.confidence = CASE WHEN af.confidence > 0.1 THEN af.confidence - 0.1 ELSE 0.0 END,
                af.falsified_count = COALESCE(af.falsified_count, 0) + 1,
                af.value_status = CASE WHEN af.value_status = 'valuable' THEN 'uncertain' ELSE af.value_status END
            """,
        params=("fid",),
        mutating=True,
        description="Penalize action fact confidence and increment falsified count.",
        sparql="""
            DELETE {
                ?af campy:confidence ?old_confidence .
                ?af campy:falsified_count ?old_falsified_count .
                ?af campy:value_status ?old_value_status .
            }
            INSERT {
                ?af campy:confidence ?new_confidence .
                ?af campy:falsified_count ?new_falsified_count .
                ?af campy:value_status ?new_value_status .
            }
            WHERE {
                ?af a campy:ActionFact ; campy:fact_id ?fid .
                OPTIONAL { ?af campy:confidence ?old_confidence }
                OPTIONAL { ?af campy:falsified_count ?old_falsified_count }
                OPTIONAL { ?af campy:value_status ?old_value_status }
                BIND(IF(BOUND(?old_confidence) && ?old_confidence > "0.1"^^xsd:double,
                        STRDT(STR(?old_confidence - "0.1"^^xsd:double), xsd:double),
                        "0.0"^^xsd:double) AS ?new_confidence)
                BIND(STRDT(STR(COALESCE(?old_falsified_count, 0) + 1), xsd:int) AS ?new_falsified_count)
                BIND(IF(BOUND(?old_value_status) && ?old_value_status = "valuable", "uncertain", ?old_value_status) AS ?new_value_status)
            }
            """,
    ),
    NamedQuery(
        name="arc.boost_action_fact_rpe",
        cypher="""
            MATCH (af:ActionFact {fact_id: $fid})
            SET af.confidence = CASE WHEN af.confidence < 0.9 THEN af.confidence + 0.1 ELSE 1.0 END
            """,
        params=("fid",),
        mutating=True,
        description="Boost action fact confidence on positive RPE.",
        sparql="""
            DELETE { ?af campy:confidence ?old_confidence . }
            INSERT { ?af campy:confidence ?new_confidence . }
            WHERE {
                ?af a campy:ActionFact ; campy:fact_id ?fid .
                OPTIONAL { ?af campy:confidence ?old_confidence }
                BIND(IF(BOUND(?old_confidence) && ?old_confidence < "0.9"^^xsd:double,
                        STRDT(STR(?old_confidence + "0.1"^^xsd:double), xsd:double),
                        "1.0"^^xsd:double) AS ?new_confidence)
            }
            """,
    ),
    NamedQuery(
        name="arc.merge_transition",
        cypher="""
            MERGE (t:Transition {transition_id: $tid})
            SET t.task_id = $task_id, t.step = $step, t.action_id = $aid,
                t.entity_ref = $eref, t.changed_count = $cc,
                t.color_transitions = $ct, t.created_at = current_timestamp()
            """,
        params=("tid", "task_id", "step", "aid", "eref", "cc", "ct"),
        mutating=True,
        description="Record or update a Transition node.",
        sparql="""
            INSERT {
                ?t a campy:Transition ;
                   campy:transition_id ?tid ;
                   campy:task_id ?task_id ;
                   campy:step ?step ;
                   campy:action_id ?aid ;
                   campy:entity_ref ?eref ;
                   campy:changed_count ?cc ;
                   campy:color_transitions ?ct ;
                   campy:created_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "Transition/", ENCODE_FOR_URI(?tid))) AS ?t)
                BIND(NOW() AS ?now)
            }
            """,
    ),
    NamedQuery(
        name="arc.link_transition_to_entity",
        cypher="""
            MATCH (t:Transition {transition_id: $tid}),
                  (ge:GridEntity {task_id: $task_id, region_index: $eref})
            WITH t, ge LIMIT 1
            MERGE (t)-[:TRANSITION_OF]->(ge)
            """,
        params=("tid", "task_id", "eref"),
        mutating=True,
        description="Link Transition to GridEntity.",
        sparql="""
            INSERT {
                ?t campy:TRANSITION_OF ?ge .
            }
            WHERE {
                ?t a campy:Transition ; campy:transition_id ?tid .
                ?ge a campy:GridEntity ; campy:task_id ?task_id ; campy:region_index ?eref .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_entity_history",
        cypher="""
            MATCH (t:Transition {task_id: $tid, entity_ref: $eref})
            RETURN t.action_id, t.step, t.color_transitions, t.changed_count
            ORDER BY t.step
            """,
        params=("tid", "eref"),
        mutating=False,
        description="Fetch transition history for an entity.",
        sparql="""
            SELECT ?action_id ?step ?color_transitions ?changed_count WHERE {
                ?t a campy:Transition ;
                   campy:task_id ?tid ;
                   campy:entity_ref ?eref ;
                   campy:action_id ?action_id ;
                   campy:step ?step ;
                   campy:color_transitions ?color_transitions ;
                   campy:changed_count ?changed_count .
            }
            ORDER BY ?step
            """,
    ),
    NamedQuery(
        name="arc.link_entity_rule",
        cypher="""
            MATCH (ge:GridEntity {task_id: $tid, region_index: $eref}), (r:Rule {rule_id: $rid})
            WITH ge, r LIMIT 1
            MERGE (ge)-[er:ENTITY_RULE]->(r)
            SET er.weight = $weight, er.step = $step
            """,
        params=("tid", "eref", "rid", "weight", "step"),
        mutating=True,
        description="Link GridEntity to Rule via ENTITY_RULE.",
    ),
    NamedQuery(
        name="arc.find_live_rule",
        cypher="""
            MATCH (r:Rule {task_id: $tid, action_family: $af, from_color: $fc})
            WHERE r.falsified = false
            RETURN r.rule_id, r.to_color, r.confidence
            """,
        params=("tid", "af", "fc"),
        mutating=False,
        description="Find live rule matching action family and from_color.",
        sparql="""
            SELECT ?rule_id ?to_color ?confidence WHERE {
                ?r a campy:Rule ;
                   campy:task_id ?tid ;
                   campy:action_family ?af ;
                   campy:from_color ?fc ;
                   campy:falsified false ;
                   campy:rule_id ?rule_id ;
                   campy:to_color ?to_color ;
                   campy:confidence ?confidence .
            }
            """,
    ),
    NamedQuery(
        name="arc.create_rule",
        cypher="""
            MERGE (r:Rule {rule_id: $rid})
            SET r.task_id = $tid, r.action_family = $af, r.from_color = $fc,
                r.to_color = $tc, r.fingerprint = $fp, r.confidence = 0.5,
                r.falsified = false, r.created_step = $step
            """,
        params=("rid", "tid", "af", "fc", "tc", "fp", "step"),
        mutating=True,
        description="Create a new Rule candidate.",
        sparql="""
            INSERT {
                ?r a campy:Rule ;
                   campy:rule_id ?rid ;
                   campy:task_id ?tid ;
                   campy:action_family ?af ;
                   campy:from_color ?fc ;
                   campy:to_color ?tc ;
                   campy:fingerprint ?fp ;
                   campy:confidence "0.5"^^xsd:double ;
                   campy:falsified false ;
                   campy:created_step ?step .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "Rule/", ENCODE_FOR_URI(?rid))) AS ?r)
            }
            """,
    ),
    NamedQuery(
        name="arc.confirm_rule",
        cypher="""
            MATCH (r:Rule {rule_id: $rid})
            SET r.confidence = $conf, r.fingerprint = coalesce(r.fingerprint, $fp)
            """,
        params=("rid", "conf", "fp"),
        mutating=True,
        description="Confirm a Rule and update confidence.",
        sparql="""
            DELETE {
                ?r campy:confidence ?old_confidence .
                ?r campy:fingerprint ?old_fingerprint .
            }
            INSERT {
                ?r campy:confidence ?conf ;
                   campy:fingerprint ?fingerprint_val .
            }
            WHERE {
                ?r a campy:Rule ; campy:rule_id ?rid .
                OPTIONAL { ?r campy:confidence ?old_confidence }
                OPTIONAL { ?r campy:fingerprint ?old_fingerprint }
                BIND(COALESCE(?old_fingerprint, ?fp) AS ?fingerprint_val)
            }
            """,
    ),
    NamedQuery(
        name="arc.falsify_rule",
        cypher="MATCH (r:Rule {rule_id: $rid}) SET r.falsified = true",
        params=("rid",),
        mutating=True,
        description="Mark a Rule as falsified.",
        sparql="""
            DELETE { ?r campy:falsified ?old_falsified . }
            INSERT { ?r campy:falsified true . }
            WHERE {
                ?r a campy:Rule ; campy:rule_id ?rid .
                OPTIONAL { ?r campy:falsified ?old_falsified }
            }
            """,
    ),
    NamedQuery(
        name="arc.get_rules_for_action",
        cypher="""
            MATCH (r:Rule {task_id: $tid, action_family: $af})
            WHERE r.falsified = false
            RETURN r.rule_id, r.from_color, r.to_color, r.confidence, r.falsified
            """,
        params=("tid", "af"),
        mutating=False,
        description="Fetch live rules for an action family.",
        sparql="""
            SELECT ?rule_id ?from_color ?to_color ?confidence ?falsified WHERE {
                ?r a campy:Rule ;
                   campy:task_id ?tid ;
                   campy:action_family ?af ;
                   campy:falsified false ;
                   campy:rule_id ?rule_id ;
                   campy:from_color ?from_color ;
                   campy:to_color ?to_color ;
                   campy:confidence ?confidence .
                BIND(false AS ?falsified)
            }
            """,
    ),
    NamedQuery(
        name="arc.get_transferred_rules",
        cypher="""
            MATCH (r:Rule {fingerprint: $fp})
            WHERE r.task_id <> $tid AND r.falsified = false
            RETURN r.rule_id, r.confidence, r.task_id
            """,
        params=("fp", "tid"),
        mutating=False,
        description="Fetch transferred rules from other tasks matching fingerprint.",
        sparql="""
            SELECT ?rule_id ?confidence ?task_id WHERE {
                ?r a campy:Rule ;
                   campy:fingerprint ?fp ;
                   campy:falsified false ;
                   campy:rule_id ?rule_id ;
                   campy:confidence ?confidence ;
                   campy:task_id ?task_id .
                FILTER(?task_id != ?tid)
            }
            """,
    ),
    # arc_artifacts.py queries
    NamedQuery(
        name="arc.upsert_artifact",
        cypher="""
            MERGE (a:ArcArtifact {artifact_id: $artifact_id})
            SET a.artifact_kind = $artifact_kind,
                a.path = $path,
                a.content_hash = $content_hash,
                a.record_count = $record_count,
                a.captured_at = $captured_at,
                a.ingested_at = timestamp($now),
                a.domain = $domain,
                a.summary = $summary
            """,
        params=("artifact_id", "artifact_kind", "path", "content_hash", "record_count", "captured_at", "now", "domain", "summary"),
        mutating=True,
        description="Upsert ArcArtifact node.",
        sparql="""
            DELETE {
                ?a campy:artifact_kind ?o1 . ?a campy:path ?o2 . ?a campy:content_hash ?o3 .
                ?a campy:record_count ?o4 . ?a campy:captured_at ?o5 . ?a campy:ingested_at ?o6 .
                ?a campy:domain ?o7 . ?a campy:summary ?o8 .
            }
            INSERT {
                ?a a campy:ArcArtifact ;
                   campy:artifact_id ?artifact_id ;
                   campy:artifact_kind ?artifact_kind ;
                   campy:path ?path ;
                   campy:content_hash ?content_hash ;
                   campy:record_count ?record_count ;
                   campy:captured_at ?captured_at ;
                   campy:ingested_at ?now ;
                   campy:domain ?domain ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcArtifact/", ENCODE_FOR_URI(?artifact_id))) AS ?a)
                BIND(NOW() AS ?now)
                OPTIONAL { ?a campy:artifact_kind ?o1 }
                OPTIONAL { ?a campy:path ?o2 }
                OPTIONAL { ?a campy:content_hash ?o3 }
                OPTIONAL { ?a campy:record_count ?o4 }
                OPTIONAL { ?a campy:captured_at ?o5 }
                OPTIONAL { ?a campy:ingested_at ?o6 }
                OPTIONAL { ?a campy:domain ?o7 }
                OPTIONAL { ?a campy:summary ?o8 }
            }
            """,
    ),
    NamedQuery(
        name="arc.upsert_run",
        cypher="""
            MERGE (r:ArcRun {run_id: $run_id})
            SET r.artifact_hash = $artifact_hash,
                r.source_root = $source_root,
                r.source_files = $source_files,
                r.started_at = $started_at,
                r.completed_at = $completed_at,
                r.status = $status,
                r.variant = $variant,
                r.task_count = $task_count,
                r.solved_count = $solved_count,
                r.failed_count = $failed_count,
                r.step_count = $step_count,
                r.domain = $domain,
                r.summary = $summary,
                r.created_at = timestamp($now),
                r.updated_at = timestamp($now)
            """,
        params=("run_id", "artifact_hash", "source_root", "source_files", "started_at", "completed_at", "status", "variant", "task_count", "solved_count", "failed_count", "step_count", "domain", "summary", "now"),
        mutating=True,
        description="Upsert ArcRun node.",
        sparql="""
            DELETE {
                ?r campy:artifact_hash ?o1 . ?r campy:source_root ?o2 . ?r campy:source_files ?o3 .
                ?r campy:started_at ?o4 . ?r campy:completed_at ?o5 . ?r campy:status ?o6 .
                ?r campy:variant ?o7 . ?r campy:task_count ?o8 . ?r campy:solved_count ?o9 .
                ?r campy:failed_count ?o10 . ?r campy:step_count ?o11 . ?r campy:domain ?o12 .
                ?r campy:summary ?o13 . ?r campy:created_at ?o14 . ?r campy:updated_at ?o15 .
            }
            INSERT {
                ?r a campy:ArcRun ;
                   campy:run_id ?run_id ;
                   campy:artifact_hash ?artifact_hash ;
                   campy:source_root ?source_root ;
                   campy:source_files ?source_files ;
                   campy:started_at ?started_at ;
                   campy:completed_at ?completed_at ;
                   campy:status ?status ;
                   campy:variant ?variant ;
                   campy:task_count ?task_count ;
                   campy:solved_count ?solved_count ;
                   campy:failed_count ?failed_count ;
                   campy:step_count ?step_count ;
                   campy:domain ?domain ;
                   campy:summary ?summary ;
                   campy:created_at ?now ;
                   campy:updated_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcRun/", ENCODE_FOR_URI(?run_id))) AS ?r)
                BIND(NOW() AS ?now)
                OPTIONAL { ?r campy:artifact_hash ?o1 }
                OPTIONAL { ?r campy:source_root ?o2 }
                OPTIONAL { ?r campy:source_files ?o3 }
                OPTIONAL { ?r campy:started_at ?o4 }
                OPTIONAL { ?r campy:completed_at ?o5 }
                OPTIONAL { ?r campy:status ?o6 }
                OPTIONAL { ?r campy:variant ?o7 }
                OPTIONAL { ?r campy:task_count ?o8 }
                OPTIONAL { ?r campy:solved_count ?o9 }
                OPTIONAL { ?r campy:failed_count ?o10 }
                OPTIONAL { ?r campy:step_count ?o11 }
                OPTIONAL { ?r campy:domain ?o12 }
                OPTIONAL { ?r campy:summary ?o13 }
                OPTIONAL { ?r campy:created_at ?o14 }
                OPTIONAL { ?r campy:updated_at ?o15 }
            }
            """,
    ),
    NamedQuery(
        name="arc.upsert_task",
        cypher="""
            MERGE (t:ArcTaskResult {task_result_id: $task_result_id})
            SET t.run_id = $run_id,
                t.task_id = $task_id,
                t.puzzle_id = $puzzle_id,
                t.status = $status,
                t.correct = $correct,
                t.steps = $steps,
                t.tokens_input = $tokens_input,
                t.tokens_output = $tokens_output,
                t.failure_class = $failure_class,
                t.trajectory_score = $trajectory_score,
                t.domain = $domain,
                t.summary = $summary,
                t.created_at = timestamp($now),
                t.updated_at = timestamp($now)
            """,
        params=("task_result_id", "run_id", "task_id", "puzzle_id", "status", "correct", "steps", "tokens_input", "tokens_output", "failure_class", "trajectory_score", "domain", "summary", "now"),
        mutating=True,
        description="Upsert ArcTaskResult node.",
        sparql="""
            DELETE {
                ?t campy:run_id ?o1 . ?t campy:task_id ?o2 . ?t campy:puzzle_id ?o3 . ?t campy:status ?o4 .
                ?t campy:correct ?o5 . ?t campy:steps ?o6 . ?t campy:tokens_input ?o7 . ?t campy:tokens_output ?o8 .
                ?t campy:failure_class ?o9 . ?t campy:trajectory_score ?o10 . ?t campy:domain ?o11 .
                ?t campy:summary ?o12 . ?t campy:created_at ?o13 . ?t campy:updated_at ?o14 .
            }
            INSERT {
                ?t a campy:ArcTaskResult ;
                   campy:task_result_id ?task_result_id ;
                   campy:run_id ?run_id ;
                   campy:task_id ?task_id ;
                   campy:puzzle_id ?puzzle_id ;
                   campy:status ?status ;
                   campy:correct ?correct ;
                   campy:steps ?steps ;
                   campy:tokens_input ?tokens_input ;
                   campy:tokens_output ?tokens_output ;
                   campy:failure_class ?failure_class ;
                   campy:trajectory_score ?trajectory_score ;
                   campy:domain ?domain ;
                   campy:summary ?summary ;
                   campy:created_at ?now ;
                   campy:updated_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcTaskResult/", ENCODE_FOR_URI(?task_result_id))) AS ?t)
                BIND(NOW() AS ?now)
                OPTIONAL { ?t campy:run_id ?o1 }
                OPTIONAL { ?t campy:task_id ?o2 }
                OPTIONAL { ?t campy:puzzle_id ?o3 }
                OPTIONAL { ?t campy:status ?o4 }
                OPTIONAL { ?t campy:correct ?o5 }
                OPTIONAL { ?t campy:steps ?o6 }
                OPTIONAL { ?t campy:tokens_input ?o7 }
                OPTIONAL { ?t campy:tokens_output ?o8 }
                OPTIONAL { ?t campy:failure_class ?o9 }
                OPTIONAL { ?t campy:trajectory_score ?o10 }
                OPTIONAL { ?t campy:domain ?o11 }
                OPTIONAL { ?t campy:summary ?o12 }
                OPTIONAL { ?t campy:created_at ?o13 }
                OPTIONAL { ?t campy:updated_at ?o14 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_run_task",
        cypher="""
            MATCH (r:ArcRun {run_id: $run_id})
            MATCH (t:ArcTaskResult {task_result_id: $task_result_id})
            MERGE (r)-[:ARC_RUN_HAS_TASK]->(t)
            """,
        params=("run_id", "task_result_id"),
        mutating=True,
        description="Link ArcRun to ArcTaskResult.",
        sparql="""
            INSERT { ?r campy:ARC_RUN_HAS_TASK ?t . }
            WHERE {
                ?r a campy:ArcRun ; campy:run_id ?run_id .
                ?t a campy:ArcTaskResult ; campy:task_result_id ?task_result_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.upsert_event",
        cypher="""
            MERGE (e:ArcEvent {event_id: $event_id})
            SET e.run_id = $run_id,
                e.task_id = $task_id,
                e.event_type = $event_type,
                e.timestamp = $timestamp,
                e.step_index = $step_index,
                e.actor = $actor,
                e.tool_name = $tool_name,
                e.action_name = $action_name,
                e.outcome = $outcome,
                e.domain = $domain,
                e.summary = $summary
            """,
        params=("event_id", "run_id", "task_id", "event_type", "timestamp", "step_index", "actor", "tool_name", "action_name", "outcome", "domain", "summary"),
        mutating=True,
        description="Upsert ArcEvent node.",
        sparql="""
            DELETE {
                ?e campy:run_id ?o1 . ?e campy:task_id ?o2 . ?e campy:event_type ?o3 . ?e campy:timestamp ?o4 .
                ?e campy:step_index ?o5 . ?e campy:actor ?o6 . ?e campy:tool_name ?o7 . ?e campy:action_name ?o8 .
                ?e campy:outcome ?o9 . ?e campy:domain ?o10 . ?e campy:summary ?o11 .
            }
            INSERT {
                ?e a campy:ArcEvent ;
                   campy:event_id ?event_id ;
                   campy:run_id ?run_id ;
                   campy:task_id ?task_id ;
                   campy:event_type ?event_type ;
                   campy:timestamp ?timestamp ;
                   campy:step_index ?step_index ;
                   campy:actor ?actor ;
                   campy:tool_name ?tool_name ;
                   campy:action_name ?action_name ;
                   campy:outcome ?outcome ;
                   campy:domain ?domain ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcEvent/", ENCODE_FOR_URI(?event_id))) AS ?e)
                OPTIONAL { ?e campy:run_id ?o1 }
                OPTIONAL { ?e campy:task_id ?o2 }
                OPTIONAL { ?e campy:event_type ?o3 }
                OPTIONAL { ?e campy:timestamp ?o4 }
                OPTIONAL { ?e campy:step_index ?o5 }
                OPTIONAL { ?e campy:actor ?o6 }
                OPTIONAL { ?e campy:tool_name ?o7 }
                OPTIONAL { ?e campy:action_name ?o8 }
                OPTIONAL { ?e campy:outcome ?o9 }
                OPTIONAL { ?e campy:domain ?o10 }
                OPTIONAL { ?e campy:summary ?o11 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_task_event",
        cypher="""
            MATCH (t:ArcTaskResult {task_id: $task_id})
            MATCH (e:ArcEvent {event_id: $event_id})
            MERGE (t)-[:ARC_TASK_HAS_EVENT]->(e)
            """,
        params=("task_id", "event_id"),
        mutating=True,
        description="Link ArcTaskResult to ArcEvent.",
        sparql="""
            INSERT { ?t campy:ARC_TASK_HAS_EVENT ?e . }
            WHERE {
                ?t a campy:ArcTaskResult ; campy:task_id ?task_id .
                ?e a campy:ArcEvent ; campy:event_id ?event_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.link_run_artifact",
        cypher="""
            MATCH (r:ArcRun {run_id: $run_id})
            MATCH (a:ArcArtifact {artifact_id: $artifact_id})
            MERGE (r)-[:ARC_RUN_HAS_ARTIFACT]->(a)
            """,
        params=("run_id", "artifact_id"),
        mutating=True,
        description="Link ArcRun to ArcArtifact.",
        sparql="""
            INSERT { ?r campy:ARC_RUN_HAS_ARTIFACT ?a . }
            WHERE {
                ?r a campy:ArcRun ; campy:run_id ?run_id .
                ?a a campy:ArcArtifact ; campy:artifact_id ?artifact_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.link_event_artifact",
        cypher="""
            MATCH (e:ArcEvent {event_id: $event_id})
            MATCH (a:ArcArtifact {artifact_id: $artifact_id})
            MERGE (e)-[:ARC_EVENT_FROM_ARTIFACT]->(a)
            """,
        params=("event_id", "artifact_id"),
        mutating=True,
        description="Link ArcEvent to ArcArtifact.",
        sparql="""
            INSERT { ?e campy:ARC_EVENT_FROM_ARTIFACT ?a . }
            WHERE {
                ?e a campy:ArcEvent ; campy:event_id ?event_id .
                ?a a campy:ArcArtifact ; campy:artifact_id ?artifact_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.upsert_wm_step",
        cypher="""
            MERGE (s:ArcWorldModelStep {world_model_step_id: $world_model_step_id})
            SET s.run_id = $run_id,
                s.task_id = $task_id,
                s.step_index = $step_index,
                s.node_count = $node_count,
                s.edge_count = $edge_count,
                s.compiled_claim_count = $compiled_claim_count,
                s.action_effect_class = $action_effect_class,
                s.reasoning_mode = $reasoning_mode,
                s.planner_candidate_count = $planner_candidate_count,
                s.single_action_stall_detected = $single_action_stall_detected,
                s.summary = $summary,
                s.created_at = $created_at
            """,
        params=("world_model_step_id", "run_id", "task_id", "step_index", "node_count", "edge_count", "compiled_claim_count", "action_effect_class", "reasoning_mode", "planner_candidate_count", "single_action_stall_detected", "summary", "created_at"),
        mutating=True,
        description="Upsert ArcWorldModelStep node.",
        sparql="""
            DELETE {
                ?s campy:run_id ?o1 . ?s campy:task_id ?o2 . ?s campy:step_index ?o3 . ?s campy:node_count ?o4 .
                ?s campy:edge_count ?o5 . ?s campy:compiled_claim_count ?o6 . ?s campy:action_effect_class ?o7 .
                ?s campy:reasoning_mode ?o8 . ?s campy:planner_candidate_count ?o9 .
                ?s campy:single_action_stall_detected ?o10 . ?s campy:summary ?o11 . ?s campy:created_at ?o12 .
            }
            INSERT {
                ?s a campy:ArcWorldModelStep ;
                   campy:world_model_step_id ?world_model_step_id ;
                   campy:run_id ?run_id ;
                   campy:task_id ?task_id ;
                   campy:step_index ?step_index ;
                   campy:node_count ?node_count ;
                   campy:edge_count ?edge_count ;
                   campy:compiled_claim_count ?compiled_claim_count ;
                   campy:action_effect_class ?action_effect_class ;
                   campy:reasoning_mode ?reasoning_mode ;
                   campy:planner_candidate_count ?planner_candidate_count ;
                   campy:single_action_stall_detected ?single_action_stall_detected ;
                   campy:summary ?summary ;
                   campy:created_at ?created_at .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcWorldModelStep/", ENCODE_FOR_URI(?world_model_step_id))) AS ?s)
                OPTIONAL { ?s campy:run_id ?o1 }
                OPTIONAL { ?s campy:task_id ?o2 }
                OPTIONAL { ?s campy:step_index ?o3 }
                OPTIONAL { ?s campy:node_count ?o4 }
                OPTIONAL { ?s campy:edge_count ?o5 }
                OPTIONAL { ?s campy:compiled_claim_count ?o6 }
                OPTIONAL { ?s campy:action_effect_class ?o7 }
                OPTIONAL { ?s campy:reasoning_mode ?o8 }
                OPTIONAL { ?s campy:planner_candidate_count ?o9 }
                OPTIONAL { ?s campy:single_action_stall_detected ?o10 }
                OPTIONAL { ?s campy:summary ?o11 }
                OPTIONAL { ?s campy:created_at ?o12 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_run_wm_step",
        cypher="""
            MATCH (r:ArcRun {run_id: $run_id})
            MATCH (s:ArcWorldModelStep {world_model_step_id: $world_model_step_id})
            MERGE (r)-[:ARC_RUN_HAS_WORLD_MODEL_STEP]->(s)
            """,
        params=("run_id", "world_model_step_id"),
        mutating=True,
        description="Link ArcRun to ArcWorldModelStep.",
        sparql="""
            INSERT { ?r campy:ARC_RUN_HAS_WORLD_MODEL_STEP ?s . }
            WHERE {
                ?r a campy:ArcRun ; campy:run_id ?run_id .
                ?s a campy:ArcWorldModelStep ; campy:world_model_step_id ?world_model_step_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.upsert_wm_summary",
        cypher="""
            MERGE (s:ArcWorldModelSummary {world_model_summary_id: $world_model_summary_id})
            SET s.run_id = $run_id,
                s.task_id = $task_id,
                s.graph_bounded = $graph_bounded,
                s.compiler_active = $compiler_active,
                s.falsification_active = $falsification_active,
                s.reasoning_gated = $reasoning_gated,
                s.planner_grounded = $planner_grounded,
                s.memory_transfer_active = $memory_transfer_active,
                s.single_action_stall_detected = $single_action_stall_detected,
                s.full_reasoning_cycles_avoided = $full_reasoning_cycles_avoided,
                s.summary = $summary,
                s.created_at = $created_at
            """,
        params=("world_model_summary_id", "run_id", "task_id", "graph_bounded", "compiler_active", "falsification_active", "reasoning_gated", "planner_grounded", "memory_transfer_active", "single_action_stall_detected", "full_reasoning_cycles_avoided", "summary", "created_at"),
        mutating=True,
        description="Upsert ArcWorldModelSummary node.",
        sparql="""
            DELETE {
                ?s campy:run_id ?o1 . ?s campy:task_id ?o2 . ?s campy:graph_bounded ?o3 . ?s campy:compiler_active ?o4 .
                ?s campy:falsification_active ?o5 . ?s campy:reasoning_gated ?o6 . ?s campy:planner_grounded ?o7 .
                ?s campy:memory_transfer_active ?o8 . ?s campy:single_action_stall_detected ?o9 .
                ?s campy:full_reasoning_cycles_avoided ?o10 . ?s campy:summary ?o11 . ?s campy:created_at ?o12 .
            }
            INSERT {
                ?s a campy:ArcWorldModelSummary ;
                   campy:world_model_summary_id ?world_model_summary_id ;
                   campy:run_id ?run_id ;
                   campy:task_id ?task_id ;
                   campy:graph_bounded ?graph_bounded ;
                   campy:compiler_active ?compiler_active ;
                   campy:falsification_active ?falsification_active ;
                   campy:reasoning_gated ?reasoning_gated ;
                   campy:planner_grounded ?planner_grounded ;
                   campy:memory_transfer_active ?memory_transfer_active ;
                   campy:single_action_stall_detected ?single_action_stall_detected ;
                   campy:full_reasoning_cycles_avoided ?full_reasoning_cycles_avoided ;
                   campy:summary ?summary ;
                   campy:created_at ?created_at .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcWorldModelSummary/", ENCODE_FOR_URI(?world_model_summary_id))) AS ?s)
                OPTIONAL { ?s campy:run_id ?o1 }
                OPTIONAL { ?s campy:task_id ?o2 }
                OPTIONAL { ?s campy:graph_bounded ?o3 }
                OPTIONAL { ?s campy:compiler_active ?o4 }
                OPTIONAL { ?s campy:falsification_active ?o5 }
                OPTIONAL { ?s campy:reasoning_gated ?o6 }
                OPTIONAL { ?s campy:planner_grounded ?o7 }
                OPTIONAL { ?s campy:memory_transfer_active ?o8 }
                OPTIONAL { ?s campy:single_action_stall_detected ?o9 }
                OPTIONAL { ?s campy:full_reasoning_cycles_avoided ?o10 }
                OPTIONAL { ?s campy:summary ?o11 }
                OPTIONAL { ?s campy:created_at ?o12 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_run_wm_summary",
        cypher="""
            MATCH (r:ArcRun {run_id: $run_id})
            MATCH (s:ArcWorldModelSummary {world_model_summary_id: $world_model_summary_id})
            MERGE (r)-[:ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(s)
            """,
        params=("run_id", "world_model_summary_id"),
        mutating=True,
        description="Link ArcRun to ArcWorldModelSummary.",
        sparql="""
            INSERT { ?r campy:ARC_RUN_HAS_WORLD_MODEL_SUMMARY ?s . }
            WHERE {
                ?r a campy:ArcRun ; campy:run_id ?run_id .
                ?s a campy:ArcWorldModelSummary ; campy:world_model_summary_id ?world_model_summary_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.link_wm_step_artifact",
        cypher="""
            MATCH (s:ArcWorldModelStep {world_model_step_id: $step_id})
            MATCH (a:ArcArtifact {artifact_id: $artifact_id})
            MERGE (s)-[:ARC_WORLD_MODEL_FROM_ARTIFACT]->(a)
            """,
        params=("step_id", "artifact_id"),
        mutating=True,
        description="Link ArcWorldModelStep to ArcArtifact.",
        sparql="""
            INSERT { ?s campy:ARC_WORLD_MODEL_FROM_ARTIFACT ?a . }
            WHERE {
                ?s a campy:ArcWorldModelStep ; campy:world_model_step_id ?step_id .
                ?a a campy:ArcArtifact ; campy:artifact_id ?artifact_id .
            }
            """,
    ),
    NamedQuery(
        name="arc.link_wm_summary_artifact",
        cypher="""
            MATCH (s:ArcWorldModelSummary {world_model_summary_id: $step_id})
            MATCH (a:ArcArtifact {artifact_id: $artifact_id})
            MERGE (s)-[:ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT]->(a)
            """,
        params=("step_id", "artifact_id"),
        mutating=True,
        description="Link ArcWorldModelSummary to ArcArtifact.",
        sparql="""
            INSERT { ?s campy:ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT ?a . }
            WHERE {
                ?s a campy:ArcWorldModelSummary ; campy:world_model_summary_id ?step_id .
                ?a a campy:ArcArtifact ; campy:artifact_id ?artifact_id .
            }
            """,
    ),
    # arc_mechanics.py queries
    NamedQuery(
        name="arc.merge_mechanic",
        cypher="""
            MERGE (m:ArcMechanic {mechanic_id: $mechanic_id})
            ON CREATE SET m.created_at = $now,
                          m.evidence_count = 0,
                          m.contradiction_count = 0
            SET m.name = $name,
                m.signature = $signature,
                m.confidence = $confidence,
                m.terminal_relevance = $terminal_relevance,
                m.coordinate_relevance = $coordinate_relevance,
                m.source_task_ids = CASE 
                    WHEN m.source_task_ids IS NULL OR m.source_task_ids = '' THEN $task_id
                    WHEN m.source_task_ids CONTAINS $task_id THEN m.source_task_ids
                    ELSE m.source_task_ids + ',' + $task_id
                END,
                m.evidence_count = m.evidence_count + 1,
                m.domain = $domain,
                m.summary = $summary,
                m.updated_at = $now
            """,
        params=(
            "mechanic_id", "now", "name", "signature", "confidence",
            "terminal_relevance", "coordinate_relevance", "task_id", "domain", "summary"
        ),
        mutating=True,
        description="Merge ArcMechanic node with evidence counting and task IDs.",
        sparql="""
            DELETE {
                ?m campy:name ?o1 . ?m campy:signature ?o2 . ?m campy:confidence ?o3 .
                ?m campy:terminal_relevance ?o4 . ?m campy:coordinate_relevance ?o5 .
                ?m campy:source_task_ids ?o6 . ?m campy:evidence_count ?o7 .
                ?m campy:domain ?o8 . ?m campy:summary ?o9 . ?m campy:updated_at ?o10 .
            }
            INSERT {
                ?m a campy:ArcMechanic ;
                   campy:mechanic_id ?mechanic_id ;
                   campy:created_at ?created_at_val ;
                   campy:contradiction_count ?contradiction_count_val ;
                   campy:name ?name ;
                   campy:signature ?signature ;
                   campy:confidence ?confidence ;
                   campy:terminal_relevance ?terminal_relevance ;
                   campy:coordinate_relevance ?coordinate_relevance ;
                   campy:source_task_ids ?new_source_task_ids ;
                   campy:evidence_count ?new_evidence_count ;
                   campy:domain ?domain ;
                   campy:summary ?summary ;
                   campy:updated_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcMechanic/", ENCODE_FOR_URI(?mechanic_id))) AS ?m)
                BIND(NOW() AS ?now)
                OPTIONAL { ?m campy:name ?o1 }
                OPTIONAL { ?m campy:signature ?o2 }
                OPTIONAL { ?m campy:confidence ?o3 }
                OPTIONAL { ?m campy:terminal_relevance ?o4 }
                OPTIONAL { ?m campy:coordinate_relevance ?o5 }
                OPTIONAL { ?m campy:source_task_ids ?o6 }
                OPTIONAL { ?m campy:evidence_count ?o7 }
                OPTIONAL { ?m campy:domain ?o8 }
                OPTIONAL { ?m campy:summary ?o9 }
                OPTIONAL { ?m campy:updated_at ?o10 }
                OPTIONAL { ?m campy:created_at ?existing_created_at }
                OPTIONAL { ?m campy:contradiction_count ?existing_contradiction_count }
                BIND(COALESCE(?existing_created_at, ?now) AS ?created_at_val)
                BIND(COALESCE(?existing_contradiction_count, STRDT("0", xsd:long)) AS ?contradiction_count_val)
                BIND(IF(!BOUND(?o6) || ?o6 = "", ?task_id,
                        IF(CONTAINS(?o6, ?task_id), ?o6, CONCAT(?o6, ",", ?task_id))) AS ?new_source_task_ids)
                BIND(STRDT(STR(COALESCE(?o7, STRDT("0", xsd:long)) + 1), xsd:long) AS ?new_evidence_count)
            }
            """,
    ),
    NamedQuery(
        name="arc.merge_action_pattern",
        cypher="""
            MERGE (p:ArcActionPattern {pattern_id: $pattern_id})
            SET p.signature = $signature,
                p.action_set = $action_set,
                p.action_count = $action_count,
                p.summary = $summary
            """,
        params=("pattern_id", "signature", "action_set", "action_count", "summary"),
        mutating=True,
        description="Merge ArcActionPattern node.",
        sparql="""
            DELETE {
                ?p campy:signature ?o1 . ?p campy:action_set ?o2 . ?p campy:action_count ?o3 . ?p campy:summary ?o4 .
            }
            INSERT {
                ?p a campy:ArcActionPattern ;
                   campy:pattern_id ?pattern_id ;
                   campy:signature ?signature ;
                   campy:action_set ?action_set ;
                   campy:action_count ?action_count ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcActionPattern/", ENCODE_FOR_URI(?pattern_id))) AS ?p)
                OPTIONAL { ?p campy:signature ?o1 }
                OPTIONAL { ?p campy:action_set ?o2 }
                OPTIONAL { ?p campy:action_count ?o3 }
                OPTIONAL { ?p campy:summary ?o4 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_mechanic_action_pattern",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mechanic_id})
            MATCH (p:ArcActionPattern {pattern_id: $pattern_id})
            MERGE (m)-[r:ARC_MECHANIC_HAS_ACTION_PATTERN]->(p)
            SET r.confidence = $confidence,
                r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
        params=("mechanic_id", "pattern_id", "confidence"),
        mutating=True,
        description="Link ArcMechanic to ArcActionPattern.",
    ),
    NamedQuery(
        name="arc.merge_effect_pattern",
        cypher="""
            MERGE (p:ArcEffectPattern {pattern_id: $pattern_id})
            SET p.signature = $signature,
                p.effect_class = $effect_class,
                p.terminal_trend = $terminal_trend,
                p.object_progress = $object_progress,
                p.summary = $summary
            """,
        params=("pattern_id", "signature", "effect_class", "terminal_trend", "object_progress", "summary"),
        mutating=True,
        description="Merge ArcEffectPattern node.",
        sparql="""
            DELETE {
                ?p campy:signature ?o1 . ?p campy:effect_class ?o2 . ?p campy:terminal_trend ?o3 .
                ?p campy:object_progress ?o4 . ?p campy:summary ?o5 .
            }
            INSERT {
                ?p a campy:ArcEffectPattern ;
                   campy:pattern_id ?pattern_id ;
                   campy:signature ?signature ;
                   campy:effect_class ?effect_class ;
                   campy:terminal_trend ?terminal_trend ;
                   campy:object_progress ?object_progress ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcEffectPattern/", ENCODE_FOR_URI(?pattern_id))) AS ?p)
                OPTIONAL { ?p campy:signature ?o1 }
                OPTIONAL { ?p campy:effect_class ?o2 }
                OPTIONAL { ?p campy:terminal_trend ?o3 }
                OPTIONAL { ?p campy:object_progress ?o4 }
                OPTIONAL { ?p campy:summary ?o5 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_mechanic_effect_pattern",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mechanic_id})
            MATCH (p:ArcEffectPattern {pattern_id: $pattern_id})
            MERGE (m)-[r:ARC_MECHANIC_CAUSES_EFFECT_PATTERN]->(p)
            SET r.confidence = $confidence,
                r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
        params=("mechanic_id", "pattern_id", "confidence"),
        mutating=True,
        description="Link ArcMechanic to ArcEffectPattern.",
    ),
    NamedQuery(
        name="arc.merge_precondition",
        cypher="""
            MERGE (p:ArcPrecondition {precondition_id: $pre_id})
            SET p.kind = $kind, p.signature = $signature, p.summary = $summary
            """,
        params=("pre_id", "kind", "signature", "summary"),
        mutating=True,
        description="Merge ArcPrecondition node.",
        sparql="""
            DELETE {
                ?p campy:kind ?o1 . ?p campy:signature ?o2 . ?p campy:summary ?o3 .
            }
            INSERT {
                ?p a campy:ArcPrecondition ;
                   campy:precondition_id ?pre_id ;
                   campy:kind ?kind ;
                   campy:signature ?signature ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcPrecondition/", ENCODE_FOR_URI(?pre_id))) AS ?p)
                OPTIONAL { ?p campy:kind ?o1 }
                OPTIONAL { ?p campy:signature ?o2 }
                OPTIONAL { ?p campy:summary ?o3 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_mechanic_precondition",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})
            MATCH (p:ArcPrecondition {precondition_id: $pre_id})
            MERGE (m)-[r:ARC_MECHANIC_REQUIRES]->(p)
            SET r.confidence = $confidence
            """,
        params=("mech_id", "pre_id", "confidence"),
        mutating=True,
        description="Link ArcMechanic to ArcPrecondition.",
    ),
    NamedQuery(
        name="arc.merge_failure_mode",
        cypher="""
            MERGE (f:ArcFailureMode {failure_mode_id: $fail_id})
            SET f.name = $name, f.signature = $signature, f.summary = $summary
            """,
        params=("fail_id", "name", "signature", "summary"),
        mutating=True,
        description="Merge ArcFailureMode node.",
        sparql="""
            DELETE {
                ?f campy:name ?o1 . ?f campy:signature ?o2 . ?f campy:summary ?o3 .
            }
            INSERT {
                ?f a campy:ArcFailureMode ;
                   campy:failure_mode_id ?fail_id ;
                   campy:name ?name ;
                   campy:signature ?signature ;
                   campy:summary ?summary .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcFailureMode/", ENCODE_FOR_URI(?fail_id))) AS ?f)
                OPTIONAL { ?f campy:name ?o1 }
                OPTIONAL { ?f campy:signature ?o2 }
                OPTIONAL { ?f campy:summary ?o3 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_mechanic_failure_mode",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})
            MATCH (f:ArcFailureMode {failure_mode_id: $fail_id})
            MERGE (m)-[r:ARC_MECHANIC_FAILS_AS]->(f)
            SET r.evidence_count = COALESCE(r.evidence_count, 0) + 1
            """,
        params=("mech_id", "fail_id"),
        mutating=True,
        description="Link ArcMechanic to ArcFailureMode.",
    ),
    NamedQuery(
        name="arc.merge_recovery_policy",
        cypher="""
            MERGE (p:ArcRecoveryPolicy {recovery_policy_id: $pol_id})
            SET p.name = $name, p.summary = $summary, p.confidence = $confidence
            """,
        params=("pol_id", "name", "summary", "confidence"),
        mutating=True,
        description="Merge ArcRecoveryPolicy node.",
        sparql="""
            DELETE {
                ?p campy:name ?o1 . ?p campy:summary ?o2 . ?p campy:confidence ?o3 .
            }
            INSERT {
                ?p a campy:ArcRecoveryPolicy ;
                   campy:recovery_policy_id ?pol_id ;
                   campy:name ?name ;
                   campy:summary ?summary ;
                   campy:confidence ?confidence .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "ArcRecoveryPolicy/", ENCODE_FOR_URI(?pol_id))) AS ?p)
                OPTIONAL { ?p campy:name ?o1 }
                OPTIONAL { ?p campy:summary ?o2 }
                OPTIONAL { ?p campy:confidence ?o3 }
            }
            """,
    ),
    NamedQuery(
        name="arc.link_failure_recovery_policy",
        cypher="""
            MATCH (f:ArcFailureMode {failure_mode_id: $fail_id})
            MATCH (p:ArcRecoveryPolicy {recovery_policy_id: $pol_id})
            MERGE (f)-[r:ARC_FAILURE_RECOVERED_BY]->(p)
            SET r.confidence = $confidence
            """,
        params=("fail_id", "pol_id", "confidence"),
        mutating=True,
        description="Link ArcFailureMode to ArcRecoveryPolicy.",
    ),
    NamedQuery(
        name="arc.recall_mechanics",
        cypher="""
            MATCH (m:ArcMechanic)
            WHERE m.confidence >= $min_confidence
            RETURN m.mechanic_id, m.name, m.confidence, m.signature, m.summary, m.source_task_ids, m.updated_at
            ORDER BY m.confidence DESC, m.updated_at DESC
            LIMIT $limit
            """,
        params=("min_confidence", "limit"),
        mutating=False,
        description="Recall ArcMechanics matching minimum confidence.",
        sparql="""
            SELECT ?mechanic_id ?name ?confidence ?signature ?summary ?source_task_ids ?updated_at WHERE {
                ?m a campy:ArcMechanic ;
                   campy:mechanic_id ?mechanic_id ;
                   campy:name ?name ;
                   campy:confidence ?confidence ;
                   campy:signature ?signature ;
                   campy:summary ?summary ;
                   campy:source_task_ids ?source_task_ids ;
                   campy:updated_at ?updated_at .
                FILTER(?confidence >= ?min_confidence)
            }
            ORDER BY DESC(?confidence) DESC(?updated_at)
            """,
    ),
    NamedQuery(
        name="arc.recall_mechanics_with_action_set",
        cypher="""
            MATCH (m:ArcMechanic)
            WHERE m.confidence >= $min_confidence AND m.signature = $action_set
            RETURN m.mechanic_id, m.name, m.confidence, m.signature, m.summary, m.source_task_ids, m.updated_at
            ORDER BY m.confidence DESC, m.updated_at DESC
            LIMIT $limit
            """,
        params=("min_confidence", "action_set", "limit"),
        mutating=False,
        description="Recall ArcMechanics matching minimum confidence and action_set.",
        sparql="""
            SELECT ?mechanic_id ?name ?confidence ?signature ?summary ?source_task_ids ?updated_at WHERE {
                ?m a campy:ArcMechanic ;
                   campy:mechanic_id ?mechanic_id ;
                   campy:name ?name ;
                   campy:confidence ?confidence ;
                   campy:signature ?signature ;
                   campy:summary ?summary ;
                   campy:source_task_ids ?source_task_ids ;
                   campy:updated_at ?updated_at .
                FILTER(?confidence >= ?min_confidence && ?signature = ?action_set)
            }
            ORDER BY DESC(?confidence) DESC(?updated_at)
            """,
    ),
    NamedQuery(
        name="arc.get_mechanic_action_patterns",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_HAS_ACTION_PATTERN]->(p:ArcActionPattern)
            RETURN p.signature, p.action_set, p.action_count, p.summary
            """,
        params=("mech_id",),
        mutating=False,
        description="Fetch action patterns for a mechanic.",
        sparql="""
            SELECT ?signature ?action_set ?action_count ?summary WHERE {
                ?m a campy:ArcMechanic ; campy:mechanic_id ?mech_id ; campy:ARC_MECHANIC_HAS_ACTION_PATTERN ?p .
                ?p a campy:ArcActionPattern ;
                   campy:signature ?signature ;
                   campy:action_set ?action_set ;
                   campy:action_count ?action_count ;
                   campy:summary ?summary .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_mechanic_effect_patterns",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_CAUSES_EFFECT_PATTERN]->(p:ArcEffectPattern)
            RETURN p.signature, p.effect_class, p.terminal_trend, p.object_progress, p.summary
            """,
        params=("mech_id",),
        mutating=False,
        description="Fetch effect patterns for a mechanic.",
        sparql="""
            SELECT ?signature ?effect_class ?terminal_trend ?object_progress ?summary WHERE {
                ?m a campy:ArcMechanic ; campy:mechanic_id ?mech_id ; campy:ARC_MECHANIC_CAUSES_EFFECT_PATTERN ?p .
                ?p a campy:ArcEffectPattern ;
                   campy:signature ?signature ;
                   campy:effect_class ?effect_class ;
                   campy:terminal_trend ?terminal_trend ;
                   campy:object_progress ?object_progress ;
                   campy:summary ?summary .
            }
            """,
    ),
    NamedQuery(
        name="arc.get_mechanic_failure_modes",
        cypher="""
            MATCH (m:ArcMechanic {mechanic_id: $mech_id})-[:ARC_MECHANIC_FAILS_AS]->(f:ArcFailureMode)
            OPTIONAL MATCH (f)-[:ARC_FAILURE_RECOVERED_BY]->(pol:ArcRecoveryPolicy)
            RETURN f.name, f.signature, f.summary, pol.name, pol.summary, pol.confidence
            """,
        params=("mech_id",),
        mutating=False,
        description="Fetch failure modes and recovery policies for a mechanic.",
        sparql="""
            SELECT ?name ?signature ?summary ?pol_name ?pol_summary ?pol_confidence WHERE {
                ?m a campy:ArcMechanic ; campy:mechanic_id ?mech_id ; campy:ARC_MECHANIC_FAILS_AS ?f .
                ?f a campy:ArcFailureMode ;
                   campy:name ?name ;
                   campy:signature ?signature ;
                   campy:summary ?summary .
                OPTIONAL {
                    ?f campy:ARC_FAILURE_RECOVERED_BY ?pol .
                    ?pol a campy:ArcRecoveryPolicy ;
                         campy:name ?pol_name ;
                         campy:summary ?pol_summary ;
                         campy:confidence ?pol_confidence .
                }
            }
            """,
    ),
)
