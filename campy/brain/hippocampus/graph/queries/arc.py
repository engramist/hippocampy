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
    ),
    NamedQuery(
        name="arc.get_entity_centroid",
        cypher="MATCH (e:GridEntity {entity_id: $eid}) RETURN e.centroid_row, e.centroid_col",
        params=("eid",),
        mutating=False,
        description="Fetch centroid coordinates for an existing GridEntity.",
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
    ),
    NamedQuery(
        name="arc.get_max_snapshot_step",
        cypher="MATCH (s:GridSnapshot {task_id: $tid}) RETURN max(s.step)",
        params=("tid",),
        mutating=False,
        description="Get maximum snapshot step for a task.",
    ),
    NamedQuery(
        name="arc.get_action_facts_summary",
        cypher="MATCH (af:ActionFact {task_id: $tid}) RETURN af.action_id, af.value_status, af.confidence",
        params=("tid",),
        mutating=False,
        description="Fetch ActionFact summary for a task.",
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
    ),
    NamedQuery(
        name="arc.get_distinct_action_ids",
        cypher="MATCH (af:ActionFact {task_id: $tid}) RETURN DISTINCT af.action_id",
        params=("tid",),
        mutating=False,
        description="Fetch distinct action IDs for a task.",
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
    ),
    NamedQuery(
        name="arc.get_hypothesis_confidence",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence",
        params=("hid",),
        mutating=False,
        description="Fetch confidence of a hypothesis.",
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
    ),
    NamedQuery(
        name="arc.get_hypothesis_confidence_and_status",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid RETURN h.confidence, h.status",
        params=("hid",),
        mutating=False,
        description="Fetch hypothesis confidence and status.",
    ),
    NamedQuery(
        name="arc.demote_hypothesis",
        cypher="MATCH (h:Hypothesis) WHERE h.id = $hid SET h.status = 'demoted'",
        params=("hid",),
        mutating=True,
        description="Demote a falsified hypothesis.",
    ),
    NamedQuery(
        name="arc.get_victory_condition_confidence",
        cypher="MATCH (vc:VictoryCondition {condition_id: $gid}) RETURN vc.confidence",
        params=("gid",),
        mutating=False,
        description="Fetch victory condition confidence.",
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
    ),
    NamedQuery(
        name="arc.falsify_rule",
        cypher="MATCH (r:Rule {rule_id: $rid}) SET r.falsified = true",
        params=("rid",),
        mutating=True,
        description="Mark a Rule as falsified.",
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
    ),
)
