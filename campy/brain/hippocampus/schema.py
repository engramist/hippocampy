"""
mcp_engine/schema.py — Kùzu Schema Initialization

Run once at Brain Daemon startup (idempotent — uses IF NOT EXISTS throughout).
Creates all node/relationship tables, seeds ontology, bootstraps gist centroids.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph import embeddings as emb

# ---------------------------------------------------------------------------
# B312 — Provenance + explicit supersession
#
# Every fact-bearing node table (Tier 1 claimed/observed facts, Tier 2
# learned/inferred Arc* patterns) carries seven additional columns:
#
#   source, source_version, observed_at, evidence_ref        — provenance
#   superseded_by, superseded_at, supersession_reason         — supersession
#
# `supersession_reason` must be one of SUPERSESSION_REASONS below. See
# campy/brain/hippocampus/provenance.py for the write-side helpers
# (`provenance_fields()`, `mark_superseded()`) and docs/ARCHITECTURE.md for
# the full contract.
# ---------------------------------------------------------------------------

SUPERSESSION_REASONS = frozenset({
    "replaced",       # a newer fact says it better
    "contradicted",   # proven false
    "source_removed", # the upstream source no longer asserts it
    "merged",         # folded into another node (pairs with MergeEvent)
    "expired",        # time-bounded fact whose window closed
})

# Tables carrying provenance + supersession columns: Tier 1 fact-bearing
# tables required by B312, plus the Tier 2 Arc* learned/inferred-pattern
# tables (included per B312's judgement call — they are learned patterns,
# not structural/runtime bookkeeping, so provenance applies the same way).
PROVENANCE_TABLES = (
    "Concept", "Decision", "Constraint", "Requirement", "ActionItem",
    "GlobalConstraint", "GlobalPreference", "Lesson", "Procedure",
    "KnowledgeGap", "Plan", "PlanStep", "Hypothesis", "ActionFact",
    "ActionEffect", "VictoryCondition", "Rule", "Transition",
    "DocumentExtract", "WorkSummary", "WorkArtifact",
    "ArcMechanic", "ArcActionPattern", "ArcEffectPattern",
    "ArcPrecondition", "ArcFailureMode", "ArcRecoveryPolicy",
    "ArcWorldModelStep",
)

# ---------------------------------------------------------------------------
# B313 — Authority: projected vs earned memory
#
# Every PROVENANCE_TABLES table also carries an eighth column, `authority`,
# alongside the seven B312 provenance/supersession columns:
#
#   authority STRING — one of AUTHORITY_VALUES below.
#
# "earned" (the default — see authority_of() in provenance.py) means Campy
# is the only place this fact lives; losing the row loses the fact forever.
# "projected" means the fact is a mirror of something owned elsewhere
# (a harvested capability catalog, another service's records, ...) and
# MUST carry non-NULL `source` + `source_version` so it can be rebuilt —
# see provenance.py's validate_authority(). See docs/ARCHITECTURE.md for
# the full contract.
# ---------------------------------------------------------------------------

AUTHORITY_VALUES = frozenset({
    "earned",     # exists nowhere else — Campy is the source of truth
    "projected",  # mirrored from an external authority — rebuildable, not owned
})

# ---------------------------------------------------------------------------
# B320 — Idempotent writes: content-addressed deduplication
#
# Every table also carries a ninth column, `content_hash`:
#
#   content_hash STRING — sha256 identity hash (see provenance.content_hash())
#                         over the fact's canonical (table, text, source,
#                         workspace_id, extra) tuple. NULL on rows written
#                         before B320 — see provenance.py's dedupe helper for
#                         why a NULL content_hash must never be treated as a
#                         dedup match.
#
# Deliberately narrower than PROVENANCE_TABLES/AUTHORITY_VALUES's table set:
# B320 scopes the column to the Tier 1 claimed/observed-fact tables only
# (excludes the Tier 2 Arc* learned-pattern tables), matching the card's own
# "B312's Tier 1 fact-bearing tables" instruction — dedup-on-write is only
# wired up for capture.py/lessons.py in this card anyway (see
# provenance.content_hash()/campy/brain/thalamus/tools/capture.py,lessons.py),
# so extending the column to tables nothing writes it to yet would be dead
# schema. Computed as "not an Arc* table" rather than hardcoded so it stays
# in lockstep with PROVENANCE_TABLES if Tier 1 ever grows.
# ---------------------------------------------------------------------------

CONTENT_HASH_TABLES = tuple(t for t in PROVENANCE_TABLES if not t.startswith("Arc"))

# ---------------------------------------------------------------------------
# B323 — Task dependency graph, agent provenance, card/branch context bundle
#
# Three additions, all new tables (never redefinitions of BLOCKS/ENABLES,
# which stay untouched — see the B323 backlog card for why reusing those
# names would be a data-loss hazard for ARC's GridEntity BLOCKS edges):
#
#   TASK_BLOCKS / TASK_ENABLES — declared (not learned; that's B322) task
#     dependency, same-type pairs only (MainQuest/SideQuest/ActionItem).
#     Cycle-checked at insert time by campy/brain/thalamus/tools/task_graph.py
#     via a bounded (*1..10) traversal — see add_task_dependency_edge().
#
#   AgentWorker + SOLVED_BY — a traversable node for "what else did this
#     agent touch", reconciled against (not duplicating) B312's `source`
#     string column and the pre-existing `agent_source` column on
#     WorkArtifact/WorkSummary. AgentWorker.worker_id is always the same
#     string a write's B312 `source` column holds (the "agent:<id>"
#     convention) — SOLVED_BY_TABLES lists the PROVENANCE_TABLES subset
#     (Decision, ActionItem, Lesson) a worker can be linked from.
#     upsert_agent_worker_and_link() below is the single write path; call it
#     in the same write that sets B312 provenance, never as a separate pass.
# ---------------------------------------------------------------------------

SOLVED_BY_TABLES: dict[str, str] = {
    "Decision": "decision_id",
    "ActionItem": "action_item_id",
    "Lesson": "lesson_id",
}

# ---------------------------------------------------------------------------
# Node table DDL
# ---------------------------------------------------------------------------

NODE_TABLES = {
    "Concept": """
        concept_id    STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        gist_class    STRING,
        schema_org_type STRING,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        last_accessed_at TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (concept_id)
    """,

    "Decision": """
        decision_id   STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (decision_id)
    """,

    "Constraint": """
        constraint_id STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (constraint_id)
    """,

    "Requirement": """
        requirement_id STRING,
        text_raw       STRING,
        embedding      FLOAT[384],
        embedding_model STRING,
        embedding_dim  INT64,
        confidence     DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived       BOOLEAN,
        anomaly_type   STRING,
        flagged_for_review BOOLEAN,
        created_at     TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (requirement_id)
    """,

    "ActionItem": """
        action_item_id STRING,
        text_raw       STRING,
        embedding      FLOAT[384],
        embedding_model STRING,
        embedding_dim  INT64,
        confidence     DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived       BOOLEAN,
        anomaly_type   STRING,
        flagged_for_review BOOLEAN,
        created_at     TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (action_item_id)
    """,

    "GlobalConstraint": """
        global_constraint_id STRING,
        text_raw             STRING,
        embedding            FLOAT[384],
        embedding_model      STRING,
        embedding_dim        INT64,
        confidence           DOUBLE,
        confidence_low       BOOLEAN,
        pathway_strength     DOUBLE,
        archived             BOOLEAN,
        anomaly_type         STRING,
        flagged_for_review   BOOLEAN,
        created_at           TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (global_constraint_id)
    """,

    "GlobalPreference": """
        global_preference_id STRING,
        text_raw             STRING,
        embedding            FLOAT[384],
        embedding_model      STRING,
        embedding_dim        INT64,
        confidence           DOUBLE,
        confidence_low       BOOLEAN,
        pathway_strength     DOUBLE,
        archived             BOOLEAN,
        anomaly_type         STRING,
        flagged_for_review   BOOLEAN,
        created_at           TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (global_preference_id)
    """,

    "MainQuest": """
        quest_id        STRING,
        name            STRING,
        status          STRING,
        completed_at    TIMESTAMP,
        purpose         STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        created_at      TIMESTAMP,
        last_active_at  TIMESTAMP,
        git_repo_root       STRING,
        purpose_embedding   FLOAT[384],
        routing_method      STRING,
        PRIMARY KEY (quest_id)
    """,

    "SideQuest": """
        quest_id        STRING,
        name            STRING,
        status          STRING,
        completed_at    TIMESTAMP,
        purpose         STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        created_at      TIMESTAMP,
        PRIMARY KEY (quest_id)
    """,

    "Document": """
        document_id      STRING,
        location_uri     STRING,
        content_hash     STRING,
        last_modified_at TIMESTAMP,
        mime_type        STRING,
        PRIMARY KEY (document_id)
    """,

    "Message": """
        message_id      STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        role            STRING,
        byte_start      INT64,
        byte_end        INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        anomaly_type    STRING,
        flagged_for_review BOOLEAN,
        created_at      TIMESTAMP,
        PRIMARY KEY (message_id)
    """,

    "DocumentExtract": """
        extract_id      STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        byte_start      INT64,
        byte_end        INT64,
        line_start      INT64,
        line_end        INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        anomaly_type    STRING,
        flagged_for_review BOOLEAN,
        created_at      TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (extract_id)
    """,

    "Session": """
        session_id           STRING,
        started_at           TIMESTAMP,
        last_active_at       TIMESTAMP,
        onboarded            BOOLEAN,
        purpose              STRING,
        routing_state        STRING,
        routing_confidence   DOUBLE,
        routing_method       STRING,
        token_estimate       INT64,
        token_limit          INT64,
        loaded_node_count    INT32,
        injection_count      INT64,
        dedup_tokens_saved   INT64,
        last_injection_at    TIMESTAMP,
        last_loop_summary    STRING,
        last_warm_frontier_at TIMESTAMP,
        PRIMARY KEY (session_id)
    """,

    # B290 — Continuous Work State: session work summaries and document artifacts
    "WorkSummary": """
        summary_id      STRING,
        session_id      STRING,
        agent_source    STRING,
        git_branch      STRING,
        git_commit      STRING,
        active_card     STRING,
        resume_line     STRING,
        snapshot_text   STRING,
        turn_count      INT32,
        last_updated_at TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (summary_id)
    """,

    "WorkArtifact": """
        artifact_id      STRING,
        file_path        STRING,
        document_type    STRING,
        title            STRING,
        summary          STRING,
        linked_card      STRING,
        session_id       STRING,
        agent_source     STRING,
        created_at       TIMESTAMP,
        last_modified_at TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (artifact_id)
    """,

    "LLMProvider": """
        provider_id   STRING,
        provider_name STRING,
        model_name    STRING,
        is_local      BOOLEAN,
        context_window INT64,
        PRIMARY KEY (provider_id)
    """,

    "Workspace": """
        workspace_id STRING,
        path         STRING,
        os           STRING,
        hostname     STRING,
        PRIMARY KEY (workspace_id)
    """,

    "GistClass": """
        name     STRING,
        centroid FLOAT[384],
        PRIMARY KEY (name)
    """,

    "GistExample": """
        example_id  STRING,
        text        STRING,
        embedding   FLOAT[384],
        gist_class  STRING,
        source      STRING,
        created_at  TIMESTAMP,
        PRIMARY KEY (example_id)
    """,

    "SchemaOrgType": """
        name       STRING,
        properties STRING[],
        PRIMARY KEY (name)
    """,

    "Label": """
        label_id   STRING,
        text       STRING,
        embedding  FLOAT[384],
        language   STRING,
        label_type STRING,
        confidence DOUBLE,
        source     STRING,
        created_at TIMESTAMP,
        PRIMARY KEY (label_id)
    """,

    "MergeEvent": """
        merge_event_id       STRING,
        pre_pathway_strength DOUBLE,
        delta_pathway_strength DOUBLE,
        alias_added          STRING[],
        metadata_patch       STRING,
        created_at           TIMESTAMP,
        PRIMARY KEY (merge_event_id)
    """,

    # B158 — DisambiguationEvent (human-in-the-loop entity curation)
    "DisambiguationEvent": """
        event_id       STRING,
        concept_id_a   STRING,
        concept_id_b   STRING,
        similarity     DOUBLE,
        status         STRING,
        resolved_at    TIMESTAMP,
        resolved_by    STRING,
        created_at     TIMESTAMP,
        PRIMARY KEY (event_id)
    """,

    # B11 — Lesson node (synthesized at quest completion, feeds analogical reasoning)
    "Lesson": """
        lesson_id        STRING,
        text_raw         STRING,
        embedding        FLOAT[384],
        embedding_model  STRING,
        embedding_dim    INT64,
        domain           STRING,
        lesson_type      STRING,
        scene_wl_hash    STRING,
        scene_graph_vector STRING,
        archetype        STRING,
        progress_score   DOUBLE,
        valence          DOUBLE,
        confidence       DOUBLE,
        confidence_low   BOOLEAN,
        pathway_strength DOUBLE,
        archived         BOOLEAN,
        created_at       TIMESTAMP,
        last_audited_at  TIMESTAMP,
        stale_flagged    BOOLEAN,
        stale_flagged_at TIMESTAMP,
        orphan_flagged   BOOLEAN,
        orphan_flagged_at TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (lesson_id)
    """,

    # B194 — Procedure (reusable, parameterized strategy templates)
    "Procedure": """
        procedure_id       STRING,
        name               STRING,
        domain             STRING,
        archetype          STRING,
        description        STRING,
        steps_json         STRING,
        embedding          FLOAT[384],
        embedding_model    STRING,
        embedding_dim      INT64,
        success_count      INT32,
        application_count  INT32,
        success_rate       DOUBLE,
        confidence         DOUBLE,
        pathway_strength   DOUBLE,
        archived           BOOLEAN,
        created_at         TIMESTAMP,
        last_applied_at    TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (procedure_id)
    """,

    # B193 — KnowledgeGap (metacognitive identified gaps)
    "KnowledgeGap": """
        gap_id           STRING,
        domain           STRING,
        gap_type         STRING,
        description      STRING,
        severity         DOUBLE,
        message_count    INT32,
        lesson_count     INT32,
        resolved         BOOLEAN,
        created_at       TIMESTAMP,
        resolved_at      TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (gap_id)
    """,

    # B66 — Plan/PlanStep (active agent planning graph)
    "Plan": """
        plan_id          STRING,
        goal             STRING,
        strategy         STRING,
        source           STRING,
        embedding        FLOAT[384],
        embedding_model  STRING,
        embedding_dim    INT64,
        step_count       INT64,
        valence          DOUBLE,
        valence_source   STRING,
        status           STRING,
        confidence       DOUBLE,
        confidence_low   BOOLEAN,
        pathway_strength DOUBLE,
        archived         BOOLEAN,
        created_at       TIMESTAMP,
        completed_at     TIMESTAMP,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (plan_id)
    """,

    "PlanStep": """
        step_id           STRING,
        step_number       INT64,
        description       STRING,
        embedding         FLOAT[384],
        embedding_model   STRING,
        embedding_dim     INT64,
        expected_outcome  STRING,
        actual_outcome    STRING,
        valence           DOUBLE,
        status            STRING,
        created_at        TIMESTAMP,
        completed_at      TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (step_id)
    """,

    # B88 — Hypothesis (ARC agent systematic exploration)
    "Hypothesis": """
        id               STRING,
        description      STRING,
        category         STRING,
        confidence       FLOAT,
        game_type        STRING,
        task_id          STRING,
        status           STRING,
        evidence_count   INT32,
        text_raw         STRING,
        embedding        FLOAT[384],
        created_at       TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (id)
    """,

    # B127 — DAG Task Graph (dependency-aware execution tracking)
    "TaskGraph": """
        graph_id        STRING,
        name            STRING,
        label           STRING,
        description     STRING,
        session_id      STRING,
        owner           STRING,
        version         INT64,
        status          STRING,
        created_at      TIMESTAMP,
        completed_at    TIMESTAMP,
        PRIMARY KEY (graph_id)
    """,

    "TaskNode": """
        task_id         STRING,
        graph_id        STRING,
        name            STRING,
        label           STRING,
        description     STRING,
        owner           STRING,
        status          STRING,
        input_data      STRING,
        output_data     STRING,
        error_msg       STRING,
        result          STRING,
        created_at      TIMESTAMP,
        started_at      TIMESTAMP,
        completed_at    TIMESTAMP,
        PRIMARY KEY (task_id)
    """,

    # B168 — ARC Exploration Graph nodes
    "GridEntity": """
        entity_id         STRING,
        task_id           STRING,
        level             INT32,
        color_id          INT32,
        region_index      INT32,
        pixel_count       INT32,
        centroid_row      DOUBLE,
        centroid_col      DOUBLE,
        bbox_min_row      INT32,
        bbox_min_col      INT32,
        bbox_max_row      INT32,
        bbox_max_col      INT32,
        location_hint     STRING,
        aspect_ratio      DOUBLE,
        compactness       DOUBLE,
        is_background     BOOLEAN,
        is_mobile         BOOLEAN,
        is_interactive    BOOLEAN,
        inferred_role     STRING,
        role_confidence   DOUBLE,
        last_updated_step INT32,
        created_at        TIMESTAMP,
        PRIMARY KEY (entity_id)
    """,

    "GridSnapshot": """
        snapshot_id       STRING,
        task_id           STRING,
        level             INT32,
        step              INT32,
        grid_hash         STRING,
        rows              INT32,
        cols              INT32,
        n_entities        INT32,
        symmetry_axes     STRING[],
        created_at        TIMESTAMP,
        PRIMARY KEY (snapshot_id)
    """,

    "ActionEffect": """
        effect_id         STRING,
        task_id           STRING,
        level             INT32,
        action_id         STRING,
        step              INT32,
        n_cells_changed   INT32,
        apparent_effect   STRING,
        direction_row     DOUBLE,
        direction_col     DOUBLE,
        created_at        TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (effect_id)
    """,

    "ChunkExecution": """
        execution_id     STRING,
        task_id          STRING,
        level            INT32,
        plan_id          STRING,
        chunk_family     STRING,
        description      STRING,
        status           STRING,
        steps_used       INT32,
        graduation_score DOUBLE,
        evidence_at_end  DOUBLE,
        dissonance_triggered BOOLEAN,
        outcome_summary  STRING,
        created_at       TIMESTAMP,
        last_updated     TIMESTAMP,
        PRIMARY KEY (execution_id)
    """,

    "VictoryCondition": """
        condition_id     STRING,
        task_id          STRING,
        level            INT32,
        condition_type   STRING,
        description      STRING,
        target_color_id  INT32,
        confidence       DOUBLE,
        source           STRING,
        evidence_steps   STRING,
        created_at       TIMESTAMP,
        last_updated     TIMESTAMP,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (condition_id)
    """,

    # B171 — Deterministic action facts persisted from repeated observations
    "ActionFact": """
        fact_id            STRING,
        task_id            STRING,
        level              INT32,
        action_id          STRING,
        fact_type          STRING,
        description        STRING,
        effect_description STRING,
        consistency        DOUBLE,
        confidence         DOUBLE,
        value_status       STRING,
        evidence_count     INT32,
        observation_count  INT32,
        falsified_count    INT32,
        delta_row          DOUBLE,
        delta_col          DOUBLE,
        n_cells_changed    INT32,
        created_at         TIMESTAMP,
        last_updated       TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (fact_id)
    """,

    "PuzzleCostSummary": """
        summary_id    STRING,
        task_id       STRING,
        model         STRING,
        tokens_in     INT64,
        tokens_out    INT64,
        cost_usd      DOUBLE,
        outcome       STRING,
        steps         INT32,
        created_at    TIMESTAMP,
        PRIMARY KEY (summary_id)
    """,

    # B225 — ARC Artifact Ingestion
    "ArcRun": """
        run_id          STRING,
        artifact_hash   STRING,
        source_root     STRING,
        source_files    STRING,
        started_at      STRING,
        completed_at    STRING,
        status          STRING,
        variant         STRING,
        task_count      INT64,
        solved_count    INT64,
        failed_count    INT64,
        step_count      INT64,
        domain          STRING,
        summary         STRING,
        created_at      TIMESTAMP,
        updated_at      TIMESTAMP,
        PRIMARY KEY (run_id)
    """,

    "ArcTaskResult": """
        task_result_id  STRING,
        run_id          STRING,
        task_id         STRING,
        puzzle_id       STRING,
        status          STRING,
        correct         BOOL,
        steps           INT64,
        tokens_input    INT64,
        tokens_output   INT64,
        failure_class   STRING,
        trajectory_score DOUBLE,
        domain          STRING,
        summary         STRING,
        created_at      TIMESTAMP,
        updated_at      TIMESTAMP,
        PRIMARY KEY (task_result_id)
    """,

    "ArcArtifact": """
        artifact_id     STRING,
        artifact_kind   STRING,
        path            STRING,
        content_hash    STRING,
        record_count    INT64,
        captured_at     STRING,
        ingested_at     TIMESTAMP,
        domain          STRING,
        summary         STRING,
        PRIMARY KEY (artifact_id)
    """,

    "ArcEvent": """
        event_id        STRING,
        run_id          STRING,
        task_id         STRING,
        event_type      STRING,
        timestamp       STRING,
        step_index      INT64,
        actor           STRING,
        tool_name       STRING,
        action_name     STRING,
        outcome         STRING,
        domain          STRING,
        summary         STRING,
        PRIMARY KEY (event_id)
    """,

    # B226 — ARC Mechanic Memory
    "ArcMechanic": """
        mechanic_id STRING,
        name STRING,
        signature STRING,
        confidence DOUBLE,
        terminal_relevance DOUBLE,
        coordinate_relevance DOUBLE,
        source_task_ids STRING,
        evidence_count INT64,
        contradiction_count INT64,
        domain STRING,
        summary STRING,
        created_at STRING,
        updated_at STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (mechanic_id)
    """,

    "ArcActionPattern": """
        pattern_id STRING,
        signature STRING,
        action_set STRING,
        action_count INT64,
        summary STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (pattern_id)
    """,

    "ArcEffectPattern": """
        pattern_id STRING,
        signature STRING,
        effect_class STRING,
        terminal_trend STRING,
        object_progress DOUBLE,
        summary STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (pattern_id)
    """,

    "ArcPrecondition": """
        precondition_id STRING,
        kind STRING,
        signature STRING,
        summary STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (precondition_id)
    """,

    "ArcFailureMode": """
        failure_mode_id STRING,
        name STRING,
        signature STRING,
        summary STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (failure_mode_id)
    """,

    "ArcRecoveryPolicy": """
        recovery_policy_id STRING,
        name STRING,
        summary STRING,
        confidence DOUBLE,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (recovery_policy_id)
    """,

    # B229 — ARC World-Model Evaluation
    "ArcWorldModelStep": """
        world_model_step_id STRING,
        run_id STRING,
        task_id STRING,
        step_index INT64,
        node_count INT64,
        edge_count INT64,
        compiled_claim_count INT64,
        action_effect_class STRING,
        reasoning_mode STRING,
        planner_candidate_count INT64,
        single_action_stall_detected BOOL,
        summary STRING,
        created_at STRING,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        PRIMARY KEY (world_model_step_id)
    """,

    "ArcWorldModelSummary": """
        world_model_summary_id STRING,
        run_id STRING,
        task_id STRING,
        graph_bounded BOOL,
        compiler_active BOOL,
        falsification_active BOOL,
        reasoning_gated BOOL,
        planner_grounded BOOL,
        memory_transfer_active BOOL,
        single_action_stall_detected BOOL,
        full_reasoning_cycles_avoided INT64,
        summary STRING,
        created_at STRING,
        PRIMARY KEY (world_model_summary_id)
    """,

    # B249 — Dataset node + tabular data store
    "Dataset": """
        dataset_id STRING,
        name STRING,
        description STRING,
        embedding FLOAT[384],
        embedding_model STRING,
        embedding_dim INT32,
        storage_uri STRING,
        schema_json STRING,
        row_count INT64,
        column_count INT32,
        source_format STRING,
        content_hash STRING,
        confidence DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived BOOLEAN,
        created_at TIMESTAMP,
        last_accessed_at TIMESTAMP,
        PRIMARY KEY (dataset_id)
    """,

    # B309 — A176: persisted color-transition history per ARC entity/action/step
    "Transition": """
        transition_id     STRING,
        task_id           STRING,
        step              INT32,
        action_id         STRING,
        entity_ref        INT32,
        changed_count     INT32,
        color_transitions STRING,
        created_at        TIMESTAMP,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (transition_id)
    """,

    # B309 — A177/A179: causal rules as graph nodes (PREDICTS/confirm/falsify),
    # indexed by fingerprint for A179's cross-game transfer lookup.
    "Rule": """
        rule_id       STRING,
        task_id       STRING,
        action_family STRING,
        from_color    INT32,
        to_color      INT32,
        fingerprint   STRING,
        confidence    DOUBLE,
        falsified     BOOLEAN,
        created_step  INT32,
        source              STRING,
        source_version      STRING,
        observed_at         TIMESTAMP,
        evidence_ref        STRING,
        superseded_by       STRING,
        superseded_at       TIMESTAMP,
        supersession_reason STRING,
        authority            STRING,
        content_hash         STRING,
        PRIMARY KEY (rule_id)
    """,

    # B323 — traversable agent-as-node provenance. worker_id follows the same
    # "agent:<id>" convention as B312's `source` column (see SOLVED_BY_TABLES
    # comment above); model_name/provider are best-effort and may be NULL.
    "AgentWorker": """
        worker_id      STRING,
        model_name     STRING,
        provider       STRING,
        first_seen_at  TIMESTAMP,
        last_seen_at   TIMESTAMP,
        PRIMARY KEY (worker_id)
    """,
}

# ---------------------------------------------------------------------------
# Relationship table DDL
# ---------------------------------------------------------------------------

REL_TABLES = [
    # Quest structure
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO (FROM SideQuest TO MainQuest)",
    # B323: widened FROM MainQuest TO Workspace to also cover
    # FROM ActionItem TO Workspace (card-level anchoring, not just
    # quest-level). No ANCHORED_TO write path exists anywhere in campy/
    # today (only the DDL here and one read in hippocampus.py), so the
    # _REL_MIGRATIONS entry below is a defensive upgrade path, not evidence
    # any edges actually exist to preserve.
    "CREATE REL TABLE IF NOT EXISTS ANCHORED_TO (FROM MainQuest TO Workspace, FROM ActionItem TO Workspace)",
    # Document provenance
    "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM (FROM DocumentExtract TO Document)",
    "CREATE REL TABLE IF NOT EXISTS ESTABLISHED (FROM Message TO Decision, FROM Message TO Constraint, FROM DocumentExtract TO Decision, FROM DocumentExtract TO Constraint)",
    # B249 — Dataset provenance and linkage
    "CREATE REL TABLE IF NOT EXISTS DATASET_DERIVED_FROM (FROM Dataset TO Document)",
    "CREATE REL TABLE IF NOT EXISTS DATASET_BELONGS_TO_QUEST (FROM Dataset TO MainQuest, FROM Dataset TO SideQuest)",
    "CREATE REL TABLE IF NOT EXISTS DESCRIBED_BY_DATASET (FROM Concept TO Dataset, extraction_method STRING, created_at TIMESTAMP)",
    # Audit trail
    "CREATE REL TABLE IF NOT EXISTS DEPRECATED_BY (FROM Concept TO Concept, FROM Decision TO Decision, FROM Constraint TO Constraint, FROM Lesson TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS TRIGGERED (FROM Message TO MergeEvent)",
    "CREATE REL TABLE IF NOT EXISTS UPDATES_PATHWAY (FROM MergeEvent TO Concept)",
    # Session provenance
    "CREATE REL TABLE IF NOT EXISTS USED (FROM Session TO LLMProvider)",
    "CREATE REL TABLE IF NOT EXISTS IN_WORKSPACE (FROM Session TO Workspace)",
    "CREATE REL TABLE IF NOT EXISTS WORKING_ON (FROM Session TO MainQuest, FROM Session TO SideQuest)",
    "CREATE REL TABLE IF NOT EXISTS SENT_IN (FROM Message TO Session)",
    "CREATE REL TABLE IF NOT EXISTS FOLLOWED_BY (FROM Message TO Message, gap_seconds DOUBLE)",
    "CREATE REL TABLE IF NOT EXISTS ESTABLISHED_IN (FROM Decision TO Session, FROM Constraint TO Session, FROM Requirement TO Session, FROM ActionItem TO Session)",
    "CREATE REL TABLE IF NOT EXISTS DECISION_CHAIN (FROM Decision TO Decision, session_id STRING, step_number INT32)",
    # Ontology routing (core IP — Shape-First Principle)
    "CREATE REL TABLE IF NOT EXISTS ROUTES_TO (FROM GistClass TO SchemaOrgType)",
    # SKOS labels
    "CREATE REL TABLE IF NOT EXISTS HAS_PREF_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_ALT_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_HIDDEN_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS LOADED (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, injected_at TIMESTAMP, token_estimate INT32, source STRING, load_hits INT32)",
    "CREATE REL TABLE IF NOT EXISTS WARM_NODE (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, activation_score DOUBLE, activated_at TIMESTAMP)",
    # Concept promotion
    "CREATE REL TABLE IF NOT EXISTS REIFIED_AS (FROM Concept TO Decision, FROM Concept TO Constraint, FROM Concept TO Requirement, FROM Concept TO ActionItem)",
    # Hebbian implicit layer
    "CREATE REL TABLE IF NOT EXISTS CO_OCCURS_WITH (FROM Concept TO Concept, count INT64, strength DOUBLE)",
    # Named semantic relationships — all Concept→Concept (Shape-First Principle IP)
    "CREATE REL TABLE IF NOT EXISTS REQUIRES     (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS ENABLES      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS REPLACES     (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS  (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS PART_OF      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS CHOSEN_OVER  (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS   (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS EXTENDS      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS ALTERNATIVE_TO (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS DISTINCT_FROM (FROM Concept TO Concept, created_at TIMESTAMP, source STRING)",
    # B12 — Anomaly detection
    "CREATE REL TABLE IF NOT EXISTS ANOMALY_DETECTED (FROM Concept TO GlobalConstraint, FROM Concept TO GlobalPreference, FROM Decision TO GlobalConstraint, FROM Constraint TO GlobalConstraint, FROM Requirement TO GlobalConstraint, FROM ActionItem TO GlobalConstraint, FROM Message TO GlobalConstraint, FROM DocumentExtract TO GlobalConstraint, type STRING, confidence DOUBLE, detected_at TIMESTAMP)",
    # B11 — Lesson
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_LESSON (FROM MainQuest TO Lesson)",
    # B277: widened beyond FROM Procedure TO Plan (procedure_synthesis.py's
    # use) to also cover FROM Procedure TO Concept/Decision/Constraint
    # (frustration_clusters.py links avoidance Procedures back to the
    # high-salience source nodes they were distilled from). Kuzu rel tables
    # can't ALTER to add new FROM/TO pairs after creation - `IF NOT EXISTS`
    # means a pre-existing DB with the narrower definition won't gain the
    # new pairs automatically. Low risk today: frustration_clusters.py's
    # CREATE was itself broken (missing Procedure.salience_score) until
    # this same change, so no real installation has ever successfully
    # written a DISTILLED_FROM edge to a non-Plan node to migrate.
    "CREATE REL TABLE IF NOT EXISTS DISTILLED_FROM (FROM Procedure TO Plan, FROM Procedure TO Concept, FROM Procedure TO Decision, FROM Procedure TO Constraint, synthesized_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO_ARCHETYPE (FROM Procedure TO Concept)",
    "CREATE REL TABLE IF NOT EXISTS APPLIED_PROCEDURE (FROM Plan TO Procedure, success BOOLEAN, applied_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS IDENTIFIED_GAP_IN (FROM KnowledgeGap TO MainQuest, FROM KnowledgeGap TO Concept)",
    "CREATE REL TABLE IF NOT EXISTS LEARNED (FROM Session TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO (FROM Lesson TO Concept, FROM Lesson TO Decision, FROM Lesson TO Requirement)",
    "CREATE REL TABLE IF NOT EXISTS RELATED_TO (FROM Lesson TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS GENERALIZES_LESSON (FROM Lesson TO Lesson, synthesized_at TIMESTAMP, cluster_size INT32)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS_LESSON (FROM Message TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS REROUTED_FROM (FROM Session TO MainQuest, rerouted_at TIMESTAMP, reason STRING)",
    # B290 — Continuous Work State: artifact provenance relationships
    "CREATE REL TABLE IF NOT EXISTS CREATED_IN (FROM WorkArtifact TO Session)",
    "CREATE REL TABLE IF NOT EXISTS DOCUMENTS (FROM WorkArtifact TO Plan)",
    # B66/B69 — active planning + outcome propagation
    "CREATE REL TABLE IF NOT EXISTS PLANNED_IN (FROM Plan TO Session)",
    "CREATE REL TABLE IF NOT EXISTS TARGETS (FROM Plan TO MainQuest, FROM Plan TO SideQuest)",
    "CREATE REL TABLE IF NOT EXISTS EXECUTED_AS (FROM Plan TO ChunkExecution, seq INT32)",
    "CREATE REL TABLE IF NOT EXISTS STEP_OF (FROM PlanStep TO Plan)",
    "CREATE REL TABLE IF NOT EXISTS NEXT_STEP (FROM PlanStep TO PlanStep)",
    "CREATE REL TABLE IF NOT EXISTS ACTS_ON (FROM PlanStep TO Concept)",
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_PLAN_LESSON (FROM Plan TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS OUTCOME_SIGNAL (FROM PlanStep TO Concept, valence DOUBLE, plan_id STRING, observed_at TIMESTAMP)",
    # B88 — Hypothesis engine
    "CREATE REL TABLE IF NOT EXISTS HYPOTHESIZED_IN (FROM Hypothesis TO Session)",
    "CREATE REL TABLE IF NOT EXISTS CONFIRMS (FROM Concept TO Hypothesis, weight FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS (FROM Concept TO Hypothesis, weight FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS GENERALIZES (FROM Hypothesis TO Hypothesis)",
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_HYPOTHESIS (FROM Plan TO Hypothesis)",
    "CREATE REL TABLE IF NOT EXISTS SUPPORTS_HYPOTHESIS (FROM ActionFact TO Hypothesis, weight FLOAT)",
    # B127 — DAG task graph
    "CREATE REL TABLE IF NOT EXISTS TASK_OF (FROM TaskNode TO TaskGraph)",
    "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON (FROM TaskNode TO TaskNode)",
    # B168 — ARC Exploration Graph relationships
    "CREATE REL TABLE IF NOT EXISTS OBSERVED_IN (FROM GridEntity TO GridSnapshot, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS ADJACENT_TO (FROM GridEntity TO GridEntity, min_distance DOUBLE, direction STRING, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS STRUCTURALLY_SIMILAR (FROM GridEntity TO GridEntity, similarity DOUBLE, color_shifted BOOLEAN, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS SAME_COLOR_AS (FROM GridEntity TO GridEntity)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS_ENTITY (FROM GridEntity TO GridEntity, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS MOVED_BY (FROM GridEntity TO ActionEffect, delta_row DOUBLE, delta_col DOUBLE)",
    "CREATE REL TABLE IF NOT EXISTS RESPONDS_TO (FROM GridEntity TO ActionEffect, effect_type STRING)",
    "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM_FACT (FROM ActionFact TO ActionEffect, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS BLOCKS (FROM GridEntity TO GridEntity, action_id STRING, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS ENTITY_HYPOTHESIS (FROM GridEntity TO Hypothesis, weight FLOAT, step INT32)",
    # B168 — Inference relationship types
    "CREATE REL TABLE IF NOT EXISTS CO_MOVES_WITH (FROM GridEntity TO GridEntity, step INT32)",
    "CREATE REL TABLE IF NOT EXISTS CORRELATES_WITH (FROM GridEntity TO GridEntity, step INT32, mechanism STRING)",
    "CREATE REL TABLE IF NOT EXISTS CAUSES_CHANGE_IN (FROM GridEntity TO GridEntity, mechanism STRING, confidence DOUBLE, step INT32)",
    # B172 — Victory Condition persistence
    "CREATE REL TABLE IF NOT EXISTS INFERRED_FROM (FROM VictoryCondition TO Hypothesis, weight FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS REQUIRES_ENTITY (FROM VictoryCondition TO GridEntity, requirement STRING)",
    # B309 — A176: Transition -> the GridEntity it was attributed to (entity_ref)
    "CREATE REL TABLE IF NOT EXISTS TRANSITION_OF (FROM Transition TO GridEntity)",
    # B225 — ARC Artifact Ingestion relationships
    "CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_TASK (FROM ArcRun TO ArcTaskResult)",
    "CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_ARTIFACT (FROM ArcRun TO ArcArtifact)",
    "CREATE REL TABLE IF NOT EXISTS ARC_TASK_HAS_EVENT (FROM ArcTaskResult TO ArcEvent)",
    "CREATE REL TABLE IF NOT EXISTS ARC_EVENT_FROM_ARTIFACT (FROM ArcEvent TO ArcArtifact)",
    # B226 — ARC Mechanic Memory relationships
    "CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_HAS_ACTION_PATTERN(FROM ArcMechanic TO ArcActionPattern, confidence DOUBLE, evidence_count INT64)",
    "CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_CAUSES_EFFECT_PATTERN(FROM ArcMechanic TO ArcEffectPattern, confidence DOUBLE, evidence_count INT64)",
    "CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_REQUIRES(FROM ArcMechanic TO ArcPrecondition, confidence DOUBLE)",
    "CREATE REL TABLE IF NOT EXISTS ARC_MECHANIC_FAILS_AS(FROM ArcMechanic TO ArcFailureMode, evidence_count INT64)",
    "CREATE REL TABLE IF NOT EXISTS ARC_FAILURE_RECOVERED_BY(FROM ArcFailureMode TO ArcRecoveryPolicy, confidence DOUBLE)",
    # B229 — ARC World-Model Evaluation relationships
    "CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_WORLD_MODEL_STEP(FROM ArcRun TO ArcWorldModelStep)",
    "CREATE REL TABLE IF NOT EXISTS ARC_RUN_HAS_WORLD_MODEL_SUMMARY(FROM ArcRun TO ArcWorldModelSummary)",
    "CREATE REL TABLE IF NOT EXISTS ARC_WORLD_MODEL_FROM_ARTIFACT(FROM ArcWorldModelStep TO ArcArtifact)",
    "CREATE REL TABLE IF NOT EXISTS ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT(FROM ArcWorldModelSummary TO ArcArtifact)",
    # B312 — explicit supersession lineage. Same-type pairs only (cross-type
    # supersession is out of scope for this card); covers Tier 1 + Tier 2
    # PROVENANCE_TABLES. Direction: (newer)-[:SUPERSEDES]->(older) — the
    # node passed as `superseded_by` points at the node passed as `node_id`
    # in mark_superseded(). Note this is the *opposite* arrow convention
    # from the pre-existing DEPRECATED_BY table above (FROM Concept TO
    # Concept, ...), which reads (older)-[:DEPRECATED_BY]->(newer).
    #
    # B323 audited this drift (its Task 4) and did NOT merge SUPERSEDES into
    # DEPRECATED_BY here: B312 had already landed with SUPERSEDES live
    # (mark_superseded() writes it, tests/test_provenance.py exercises it),
    # so folding the two mechanisms now would mean an in-place rel-table
    # migration whose safety this card did not audit. Per B323's own
    # instructions for this exact situation ("if B312 has already landed,
    # file the reconciliation as a follow-up and say so — do not silently
    # add a third mechanism"), no third table was added; the merge is
    # tracked as a follow-up in backlog/B325.md. Both tables keep working
    # independently until that follow-up lands.
    "CREATE REL TABLE IF NOT EXISTS SUPERSEDES (" +
    ", ".join(f"FROM {t} TO {t}" for t in PROVENANCE_TABLES) +
    ")",

    # ------------------------------------------------------------------
    # B323 — declared task dependency graph (composes with B322's learned
    # coupling). New names, never touching the existing GridEntity BLOCKS /
    # Concept ENABLES tables (see the B323 backlog card's audit for why
    # reusing those names would have been a data-loss hazard for ARC's
    # BLOCKS edges). Cycle safety is enforced at write time by
    # task_graph.add_task_dependency_edge(), not by the schema.
    # ------------------------------------------------------------------
    "CREATE REL TABLE IF NOT EXISTS TASK_BLOCKS ("
    "FROM MainQuest TO MainQuest, FROM SideQuest TO SideQuest, FROM ActionItem TO ActionItem, "
    "declared_by STRING, confidence DOUBLE, observed_at TIMESTAMP, "
    "source STRING, source_version STRING, authority STRING)",
    "CREATE REL TABLE IF NOT EXISTS TASK_ENABLES ("
    "FROM MainQuest TO MainQuest, FROM SideQuest TO SideQuest, FROM ActionItem TO ActionItem, "
    "declared_by STRING, confidence DOUBLE, observed_at TIMESTAMP, "
    "source STRING, source_version STRING, authority STRING)",

    # B323 — agent-as-node provenance (traversal-only; see SOLVED_BY_TABLES
    # comment above for why this doesn't replace B312's `source` column or
    # WorkArtifact/WorkSummary's pre-existing `agent_source` column).
    "CREATE REL TABLE IF NOT EXISTS SOLVED_BY ("
    "FROM Decision TO AgentWorker, FROM ActionItem TO AgentWorker, FROM Lesson TO AgentWorker, "
    "confidence DOUBLE, observed_at TIMESTAMP)",
]

def get_relationship_types() -> list[str]:
    """Parse REL_TABLES to extract all relationship table names."""
    rels = []
    for ddl in REL_TABLES:
        # Match 'CREATE REL TABLE IF NOT EXISTS NAME' or 'CREATE REL TABLE NAME'
        match = re.search(r"CREATE REL TABLE (?:IF NOT EXISTS )?(\w+)", ddl)
        if match:
            rels.append(match.group(1))
    return rels


# ---------------------------------------------------------------------------
# Ontology seed data (gist → schema.org routing table — core IP)
# ---------------------------------------------------------------------------

ROUTING_TABLE = [
    ("Restriction",   "Demand",             ["eligibleCustomerType", "availability", "validFrom", "validThrough", "businessFunction", "description"]),
    ("PlannedEvent",  "Action",             ["agent", "object", "target", "actionStatus", "startTime", "endTime", "result", "instrument"]),
    ("PhysicalThing", "Product",            ["name", "identifier", "description", "version", "inLanguage", "isAccessoryOrSparePartFor"]),
    ("Magnitude",     "QuantitativeValue",  ["value", "unitCode", "unitText", "minValue", "maxValue", "valueReference"]),
    ("Category",      "DefinedTerm",        ["name", "description", "termCode", "inDefinedTermSet", "sameAs"]),
    ("Agent",         "Person",             ["name", "jobTitle", "description", "email", "knowsAbout"]),
    ("Agent",         "Organization",       ["name", "description", "member", "parentOrganization", "contactPoint"]),
    ("Event",         "Event",              ["name", "startDate", "endDate", "eventStatus", "location", "organizer", "description"]),
]

# ---------------------------------------------------------------------------
# Centroid bootstrap — parse GistSeedExamples.md
# ---------------------------------------------------------------------------

def _parse_seed_examples(seed_path: str) -> dict[str, list[str]]:
    """
    Parse GistSeedExamples.md → {gist_class_name: [sentence, ...]}
    Sections are identified by '## gist:ClassName' headers.
    Examples are numbered lines: '1. "sentence text"'
    """
    text = Path(seed_path).read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current_class = None

    for line in text.splitlines():
        header_match = re.match(r"^## gist:(\w+)", line)
        if header_match:
            current_class = header_match.group(1)
            sections[current_class] = []
            continue

        if current_class:
            example_match = re.match(r'^\d+\.\s+"(.+)"', line)
            if example_match:
                sections[current_class].append(example_match.group(1))

    return sections


def _bootstrap_centroids(db: KuzuClient, seed_path: str,
                          embedding_model: str) -> None:
    """
    Embed all seed examples, compute mean per class, store as GistClass.centroid.
    Idempotent: skips classes whose centroid is already populated (Kùzu 0.11.3
    cannot SET an indexed vector property in-place; we DETACH DELETE + re-CREATE,
    which also removes ROUTES_TO edges — those are re-seeded on next startup via
    the MERGE in step 3 of init_schema).
    """
    print("Bootstrapping gist class centroids from seed examples...")
    examples = _parse_seed_examples(seed_path)

    for class_name, sentences in examples.items():
        if not sentences:
            print(f"  WARNING: No seed examples found for gist:{class_name}")
            continue

        vectors = emb.embed_batch(sentences, model_name=embedding_model)
        centroid = emb.mean_pool(vectors)
        # L1 fix: mean-pooling normalized vectors does NOT yield a normalized
        # vector. L2-normalize the centroid so cosine similarity scores are
        # accurate and System 1 thresholds (0.85) behave as intended.
        norm = sum(v * v for v in centroid) ** 0.5
        if norm > 0:
            centroid = [v / norm for v in centroid]

        # Kùzu 0.11.3: cannot SET a vector property in-place when it's indexed.
        # DETACH DELETE removes ROUTES_TO edges — re-seed them immediately after.
        db.execute("MATCH (g:GistClass {name: $name}) DETACH DELETE g", {"name": class_name})
        db.execute(
            "CREATE (:GistClass {name: $name, centroid: $centroid})",
            {"name": class_name, "centroid": centroid}
        )
        # Re-seed ROUTES_TO edges for this class (DETACH DELETE removed them).
        for g_name, s_name, _props in ROUTING_TABLE:
            if g_name == class_name:
                db.execute(
                    "MATCH (g:GistClass {name: $g}), (s:SchemaOrgType {name: $s}) "
                    "MERGE (g)-[:ROUTES_TO]->(s)",
                    {"g": g_name, "s": s_name}
                )
        print(f"  gist:{class_name} — {len(sentences)} examples, centroid computed")

    print("Centroid bootstrap complete.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def init_schema(db: KuzuClient, seed_examples_path: str,
                embedding_model: str) -> None:
    """
    Initialize Kùzu schema. Idempotent — safe to call on every daemon startup.

    SC1 note: schema init uses db.execute() (sync, bypasses asyncio write lock)
    because it runs synchronously during startup before the event loop is
    serving requests. The asyncio lock guards concurrent writes between live
    coroutines — schema init is single-threaded and runs first. This is safe
    as long as init_schema() is always called before BrainDaemon.start() hands
    off to asyncio. Do not call init_schema() after the event loop starts.

    Steps:
      1. Validate embedding dimension
      2. Create all node tables (IF NOT EXISTS)
      3. Create all relationship tables (IF NOT EXISTS)
      4. Seed GistClass + SchemaOrgType nodes + ROUTES_TO edges
      5. Bootstrap GistClass centroids from seed examples
      6. Create HNSW vector indexes
    """
    print("Initializing schema...")

    # B76: Dimension validation
    test_vec = emb.embed("dimension validation test", model_name=embedding_model)
    expected_dim = 384  # matches FLOAT[384] in schema
    if len(test_vec) != expected_dim:
        raise ValueError(
            f"Embedding model produces {len(test_vec)} dimensions "
            f"but schema expects {expected_dim}. "
            f"Check config embedding_model setting."
        )
    print(f"  Embedding validation: {expected_dim} dimensions verified.")

    # 1. Node tables
    for table_name, fields in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table_name} ({fields})")
        print(f"  Node table: {table_name}")

    # 1b. Schema migrations — add columns that may be missing from older DBs
    _MIGRATIONS = [
        # (table, column, type) — ALTER TABLE ADD COLUMN IF NOT EXISTS
        # B278: explicit falsification counter for the ARC evidence loop.
        # Derived-from-value_status was a silent-zero bug — a 'valuable' action
        # contradicted repeatedly read as 0 falsifications, so A135's penalty
        # never fired.
        ("ActionFact", "falsified_count",  "INT32"),
        ("MainQuest", "git_repo_root",     "STRING"),
        ("MainQuest", "purpose_embedding", "FLOAT[384]"),
        ("MainQuest", "routing_method",    "STRING"),
        ("MainQuest", "last_active_at",    "TIMESTAMP"),
        ("Session",   "routing_state",     "STRING"),
        ("Session",   "routing_confidence", "DOUBLE"),
        ("Session",   "routing_method",    "STRING"),
        ("Session",   "token_estimate",    "INT64"),
        ("Session",   "token_limit",       "INT64"),
        ("Session",   "loaded_node_count", "INT64"),
        # last_injection_at and last_loop_summary added in B18 working_memory
        ("Session",   "last_injection_at", "TIMESTAMP"),
        ("Session",   "last_loop_summary", "STRING"),
        ("Session",   "last_warm_frontier_at", "TIMESTAMP"),
        # B127/B128 — DAG task graph back-compat for older DBs
        ("TaskGraph", "label", "STRING"),
        ("TaskGraph", "session_id", "STRING"),
        ("TaskGraph", "owner", "STRING"),
        ("TaskGraph", "version", "INT64"),
        ("TaskNode",  "graph_id", "STRING"),
        ("TaskNode",  "label", "STRING"),
        ("TaskNode",  "owner", "STRING"),
        ("TaskNode",  "result", "STRING"),
        # B12 — anomaly detection columns
        ("Concept",   "anomaly_type",      "STRING"),
        ("Concept",   "flagged_for_review", "BOOLEAN"),
        ("Decision",  "anomaly_type",      "STRING"),
        ("Decision",  "flagged_for_review", "BOOLEAN"),
        ("Constraint", "anomaly_type",     "STRING"),
        ("Constraint", "flagged_for_review", "BOOLEAN"),
        ("Requirement", "anomaly_type",    "STRING"),
        ("Requirement", "flagged_for_review", "BOOLEAN"),
        ("ActionItem", "anomaly_type",     "STRING"),
        ("ActionItem", "flagged_for_review", "BOOLEAN"),
        ("GlobalConstraint", "anomaly_type", "STRING"),
        ("GlobalConstraint", "flagged_for_review", "BOOLEAN"),
        ("GlobalPreference", "anomaly_type", "STRING"),
        ("GlobalPreference", "flagged_for_review", "BOOLEAN"),
        ("Message",   "anomaly_type",      "STRING"),
        ("Message",   "flagged_for_review", "BOOLEAN"),
        ("DocumentExtract", "anomaly_type", "STRING"),
        ("DocumentExtract", "flagged_for_review", "BOOLEAN"),

        # B64: Ensure 'archived' column exists for all relevant tables
        ("Concept",         "archived", "BOOLEAN"),
        ("Decision",        "archived", "BOOLEAN"),
        ("Constraint",      "archived", "BOOLEAN"),
        ("Requirement",     "archived", "BOOLEAN"),
        ("ActionItem",      "archived", "BOOLEAN"),
        ("GlobalConstraint", "archived", "BOOLEAN"),
        ("GlobalPreference", "archived", "BOOLEAN"),
        ("MainQuest",       "archived", "BOOLEAN"),
        ("SideQuest",       "archived", "BOOLEAN"),
        ("Message",         "archived", "BOOLEAN"),
        ("DocumentExtract", "archived", "BOOLEAN"),
        ("Label",           "archived", "BOOLEAN"),
        ("Plan",            "source", "STRING"),
        # Back-compat for older DBs created before expanded Lesson schema
        ("Lesson",          "domain", "STRING"),
        ("Lesson",          "lesson_type", "STRING"),
        ("Lesson",          "scene_wl_hash", "STRING"),
        ("Lesson",          "scene_graph_vector", "STRING"),
        ("Lesson",          "archetype", "STRING"),
        ("Lesson",          "progress_score", "DOUBLE"),
        ("Lesson",          "valence", "DOUBLE"),
        ("Lesson",          "confidence", "DOUBLE"),
        ("Lesson",          "confidence_low", "BOOLEAN"),
        ("Lesson",          "pathway_strength", "DOUBLE"),
        ("Lesson",          "archived", "BOOLEAN"),

        # Phase 2: Associative Hooks — trigger metadata
        ("Procedure",      "trigger_pattern",       "STRING"),
        ("Procedure",      "trigger_hook_type",     "STRING"),
        ("Procedure",      "trigger_tool",          "STRING"),
        ("Procedure",      "trigger_project_scope", "STRING"),
        ("Lesson",         "trigger_pattern",       "STRING"),
        ("Lesson",         "trigger_hook_type",     "STRING"),
        ("Lesson",         "trigger_tool",          "STRING"),
        ("Lesson",         "trigger_project_scope", "STRING"),

        # Basal Ganglia: salience_score — encoding-time emotional intensity
        ("Concept",        "salience_score",        "DOUBLE"),
        ("Decision",       "salience_score",        "DOUBLE"),
        ("Constraint",     "salience_score",        "DOUBLE"),
        # B277: frustration_clusters.py writes salience_score onto the
        # avoidance Procedures it synthesizes (provenance for how salient
        # the source cluster was) - was missing, so every CREATE failed.
        ("Procedure",      "salience_score",        "DOUBLE"),

        # Basal Ganglia: maturity_stage — Procedure lifecycle tracking
        ("Procedure",      "maturity_stage",        "STRING"),

        # B277: reward_predictor.py writes these on every call (live-reachable
        # from campy/brain/thalamus/tools/arc_queries.py) - were missing
        # entirely, so every write silently failed and exploration_policy.py's
        # read of prediction_error could never fire in production.
        ("Plan",           "predicted_valence",     "DOUBLE"),
        ("Plan",           "actual_valence",        "DOUBLE"),
        ("Plan",           "prediction_error",      "DOUBLE"),

        # B250: source_key — deterministic (file_path, sheet) identity for
        # tabular re-upload change detection / archive-on-change, mirroring
        # Document's location_uri-derived identity.
        ("Dataset",        "source_key",             "STRING"),

        # B312: provenance (source, source_version, observed_at, evidence_ref)
        # + explicit supersession (superseded_by, superseded_at,
        # supersession_reason) on every Tier 1 fact-bearing table and the
        # Tier 2 Arc* learned-pattern tables. Plan and VictoryCondition
        # already had a "source" column (plan origin / VC origin — a
        # different, narrower meaning than the provenance "source" defined
        # here); we do not overwrite or duplicate it, so those two tables
        # only pick up the other six columns.
        *[
            (table, col, col_type)
            for table in PROVENANCE_TABLES
            if table not in ("Plan", "VictoryCondition")
            for col, col_type in (
                ("source", "STRING"),
                ("source_version", "STRING"),
                ("observed_at", "TIMESTAMP"),
                ("evidence_ref", "STRING"),
                ("superseded_by", "STRING"),
                ("superseded_at", "TIMESTAMP"),
                ("supersession_reason", "STRING"),
            )
        ],
        # Plan / VictoryCondition: skip "source" (pre-existing column, kept as-is).
        *[
            (table, col, col_type)
            for table in ("Plan", "VictoryCondition")
            for col, col_type in (
                ("source_version", "STRING"),
                ("observed_at", "TIMESTAMP"),
                ("evidence_ref", "STRING"),
                ("superseded_by", "STRING"),
                ("superseded_at", "TIMESTAMP"),
                ("supersession_reason", "STRING"),
            )
        ],

        # B313: authority — projected vs earned memory. Same PROVENANCE_TABLES
        # set as B312's migration above (Plan/VictoryCondition included here
        # too — unlike "source", "authority" has no pre-existing column on
        # either table to collide with).
        *[
            (table, "authority", "STRING")
            for table in PROVENANCE_TABLES
        ],

        # B323: Workspace gains branch_name (for compile_card_context's
        # branch-name resolution) and active (whether this workspace is
        # currently in use). Extends the existing table via the additive
        # migration path — never redefines Workspace's DDL.
        ("Workspace", "branch_name", "STRING"),
        ("Workspace", "active", "BOOLEAN"),

        # B320: content_hash — dedup-on-write identity for retried captures.
        # CONTENT_HASH_TABLES (Tier 1 fact-bearing tables only — see the
        # comment above that constant) is a narrower set than B312/B313's
        # PROVENANCE_TABLES. NULL on every pre-B320 row; provenance.py's
        # dedup helper treats NULL as "never matches" by construction (an
        # equality comparison against NULL is never true in Cypher/Kùzu).
        *[
            (table, "content_hash", "STRING")
            for table in CONTENT_HASH_TABLES
        ],
    ]
    def _column_exists(table: str, col: str) -> bool:
        """Check whether a column already exists via table_info, avoiding
        ambiguous exception-based detection (B35 fix)."""
        try:
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                # row[1] is the column name
                if str(row[1]).lower() == col.lower():
                    return True
        except Exception:
            pass
        return False

    for table, col, col_type in _MIGRATIONS:
        if _column_exists(table, col):
            continue  # Already present — skip silently
        try:
            db.execute(f"ALTER TABLE {table} ADD {col} {col_type}")
            print(f"  Migration: added {table}.{col} ({col_type})")
        except Exception as e:
            # Rare race: another process added the column between the check and
            # the ALTER (safe to ignore).  Any other error is a real problem.
            if "already" in str(e).lower() or "property" in str(e).lower():
                pass
            else:
                print(f"  Migration warning: {table}.{col}: {e}")

    # 1c. Relationship table migrations — handle tables that need FROM clause expansion.
    # Kùzu 0.11.3 doesn't support ALTER REL TABLE. We drop + recreate tables that
    # have expanded FROM clauses. Only safe when no existing edges use the old types.
    # B323: generalized to a "check" query per entry (was hardcoded to the
    # single ESTABLISHED_IN case before this card). Each entry's "check"
    # must raise if-and-only-if the widened FROM type isn't registered yet
    # — behavior for the pre-existing ESTABLISHED_IN entry is unchanged
    # (same check/probe/new_ddl strings as before).
    _REL_MIGRATIONS = [
        # B43: ESTABLISHED_IN expanded to include Requirement and ActionItem.
        # Old definition only had Decision + Constraint. No ESTABLISHED_IN edges
        # were ever written in the old schema (edge code added in this commit),
        # so DETACH DELETE is safe.
        {
            "table": "ESTABLISHED_IN",
            "check": "MATCH (a:Requirement)-[:ESTABLISHED_IN]->(s:Session) "
                     "RETURN count(a) LIMIT 1",
            "probe":  "MATCH ()-[e:ESTABLISHED_IN]->() RETURN count(e) AS cnt",
            "new_ddl": "CREATE REL TABLE ESTABLISHED_IN "
                        "(FROM Decision TO Session, FROM Constraint TO Session, "
                        "FROM Requirement TO Session, FROM ActionItem TO Session)",
        },
        # B323: ANCHORED_TO expanded to include ActionItem alongside
        # MainQuest. No ANCHORED_TO write path exists anywhere in campy/
        # today (grep confirms only this DDL and one read in
        # hippocampus.py), so this branch is defensive — it will typically
        # take the "0 edges, safe to drop+recreate" path on any real DB.
        {
            "table": "ANCHORED_TO",
            "check": "MATCH (a:ActionItem)-[:ANCHORED_TO]->(w:Workspace) "
                     "RETURN count(a) LIMIT 1",
            "probe": "MATCH ()-[e:ANCHORED_TO]->() RETURN count(e) AS cnt",
            "new_ddl": "CREATE REL TABLE ANCHORED_TO "
                       "(FROM MainQuest TO Workspace, FROM ActionItem TO Workspace)",
        },
    ]
    for rmig in _REL_MIGRATIONS:
        try:
            # If this doesn't raise, the table already has the widened FROM
            # type registered — no migration needed.
            db.execute(rmig["check"])
        except Exception:
            # Table either doesn't exist or is missing the new FROM type.
            # Drop and recreate only if no edges exist yet (checked via probe).
            try:
                existing = db.execute(rmig["probe"])
                edge_count = existing.get_next()[0] if existing.has_next() else 0
                if edge_count == 0:
                    db.execute(f"DROP TABLE {rmig['table']}")
                    db.execute(rmig["new_ddl"])
                    print(f"  Rel migration: {rmig['table']} — expanded FROM types")
                else:
                    print(f"  Rel migration: {rmig['table']} — skipped ({edge_count} edges exist, manual migration needed)")
            except Exception as drop_err:
                # Table doesn't exist yet — DDL in step 2 will create it
                print(f"  Rel migration: {rmig['table']} — will be created fresh: {drop_err}")

    # 2. Relationship tables
    for ddl in REL_TABLES:
        db.execute(ddl)

    print("  Relationship tables created.")

    # 3. Seed ontology (GistClass + SchemaOrgType + ROUTES_TO)
    gist_classes_seen = set()
    schema_types_seen = set()

    for gist_name, schema_name, properties in ROUTING_TABLE:
        if gist_name not in gist_classes_seen:
            db.execute(
                "MERGE (g:GistClass {name: $name})",
                {"name": gist_name}
            )
            gist_classes_seen.add(gist_name)

        if schema_name not in schema_types_seen:
            # SC2 fix: MERGE on name only, then SET properties, to avoid
            # duplicate nodes if the properties list changes between versions.
            db.execute(
                "MERGE (s:SchemaOrgType {name: $name}) "
                "SET s.properties = $props",
                {"name": schema_name, "props": properties}
            )
            schema_types_seen.add(schema_name)

        db.execute(
            "MATCH (g:GistClass {name: $g}), (s:SchemaOrgType {name: $s}) "
            "MERGE (g)-[:ROUTES_TO]->(s)",
            {"g": gist_name, "s": schema_name}
        )

    print(f"  Ontology seeded: {len(gist_classes_seen)} gist classes, "
          f"{len(schema_types_seen)} schema.org types.")

    # 4. Bootstrap centroids
    _bootstrap_centroids(db, seed_examples_path, embedding_model)

    # 5. HNSW vector indexes (one per node table with embeddings)
    embedding_tables = [
        "Concept", "Decision", "Constraint", "Requirement", "ActionItem",
        "GlobalConstraint", "GlobalPreference", "MainQuest", "SideQuest",
        "Message", "DocumentExtract", "Label",
        "Lesson",  # B11
        "Plan",    # B66
        "PlanStep",  # B66
        "Hypothesis",  # B88
        "Procedure",  # B194
        "Dataset",  # B249
    ]
    for table in embedding_tables:
        index_name = f"{table.lower()}_emb_idx"
        try:
            db.create_vector_index(table, "embedding", index_name)
            print(f"  HNSW index: {index_name}")
        except Exception as e:
            # Index may already exist on subsequent startups
            if "already exists" not in str(e).lower():
                raise

    # Optional FTS branch: safe to skip on builds that do not expose the
    # extension. B284 keeps the hot-path fallback bounded even when this is off.
    try:
        if getattr(db, "has_fts", None) and db.has_fts() is True:
            db.create_fts_index("Message", "message_fts_idx", ["text_raw"])
            print("  FTS index: message_fts_idx")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

    # GistClass centroid index (for centroid similarity lookups in Step 2)
    try:
        db.create_vector_index("GistClass", "centroid", "gistclass_centroid_idx")
        print("  HNSW index: gistclass_centroid_idx")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

    print("Schema initialization complete.")


async def upsert_agent_worker_and_link(
    db: KuzuClient,
    *,
    worker_id: str | None,
    node_table: str,
    node_id: str | None,
    confidence: float = 1.0,
    observed_at: str | None = None,
    model_name: str | None = None,
    provider: str | None = None,
) -> None:
    """B323 — upsert an AgentWorker node and a SOLVED_BY edge from a
    provenance-carrying node to it.

    Call this in the *same write* that sets a node's B312 `source` column,
    passing that identical string as `worker_id` — never as a separate
    capture pass (see the B323 header comment above SOLVED_BY_TABLES). This
    keeps AgentWorker.worker_id and the B312 `source` column as one
    identity with two access paths (column for filtering, node for
    traversal) rather than a drifting third mechanism.

    No-ops (does not raise) when:
      - `worker_id` is falsy or doesn't follow the "agent:<id>" convention
        this codebase uses for agent-sourced provenance (see
        capture.py/lessons.py) — there is no AgentWorker for a human
        ("user:direct") or harvester ("harvest:*") source.
      - `node_table` isn't in SOLVED_BY_TABLES, or `node_id` is falsy.
    """
    if not worker_id or not worker_id.startswith("agent:"):
        return
    pk = SOLVED_BY_TABLES.get(node_table)
    if not pk or not node_id:
        return

    now_iso = observed_at or datetime.now(timezone.utc).isoformat()

    await db.execute_write(
        "MERGE (w:AgentWorker {worker_id: $wid}) "
        "ON CREATE SET w.first_seen_at = timestamp($now), "
        "w.last_seen_at = timestamp($now), "
        "w.model_name = $model_name, w.provider = $provider "
        "ON MATCH SET w.last_seen_at = timestamp($now)",
        {"wid": worker_id, "now": now_iso, "model_name": model_name, "provider": provider},
    )
    await db.execute_write(
        f"MATCH (n:{node_table} {{{pk}: $nid}}), (w:AgentWorker {{worker_id: $wid}}) "
        f"MERGE (n)-[r:SOLVED_BY]->(w) "
        f"ON CREATE SET r.confidence = $conf, r.observed_at = timestamp($now) "
        f"ON MATCH SET r.confidence = $conf, r.observed_at = timestamp($now)",
        {"nid": node_id, "wid": worker_id, "conf": confidence, "now": now_iso},
    )
