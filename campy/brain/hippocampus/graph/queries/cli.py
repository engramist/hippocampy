"""campy/brain/hippocampus/graph/queries/cli.py — Named queries for CLI commands (trigger, graph_repair)."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

CLI_QUERIES: tuple[NamedQuery, ...] = (
    # -----------------------------------------------------------------------
    # trigger.py queries
    # -----------------------------------------------------------------------
    NamedQuery(
        name="cli.trigger_find_procedure",
        cypher="""
            MATCH (p:Procedure) WHERE p.name = $name AND p.archived = false
            RETURN p.procedure_id AS id, p.name AS name
            """,
        params=("name",),
        mutating=False,
        description="Find active Procedure by name for trigger binding.",
    ),
    NamedQuery(
        name="cli.trigger_update_procedure",
        cypher="""
            MATCH (p:Procedure {procedure_id: $pid})
            SET p.trigger_pattern = $pattern,
                p.trigger_hook_type = $hook_type,
                p.trigger_tool = $tool,
                p.trigger_project_scope = $scope
            """,
        params=("pid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Update trigger metadata on a Procedure.",
    ),
    NamedQuery(
        name="cli.trigger_find_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid}) WHERE l.archived = false
            RETURN l.lesson_id AS id, l.text_raw AS text
            """,
        params=("lid",),
        mutating=False,
        description="Find active Lesson by ID for trigger binding.",
    ),
    NamedQuery(
        name="cli.trigger_update_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.trigger_pattern = $pattern,
                l.trigger_hook_type = $hook_type,
                l.trigger_tool = $tool,
                l.trigger_project_scope = $scope
            """,
        params=("lid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Update trigger metadata on a Lesson.",
    ),
    NamedQuery(
        name="cli.trigger_list_procedures",
        cypher="""
            MATCH (p:Procedure)
            WHERE p.archived = false
              AND p.trigger_pattern IS NOT NULL
              AND p.trigger_pattern <> ''
            RETURN p.procedure_id AS id, p.name AS name,
                   p.trigger_pattern AS pattern, p.trigger_hook_type AS hook_type,
                   p.trigger_tool AS tool, p.trigger_project_scope AS scope,
                   p.pathway_strength AS strength
            ORDER BY p.pathway_strength DESC
            """,
        params=(),
        mutating=False,
        description="List active procedures with trigger patterns.",
    ),
    NamedQuery(
        name="cli.trigger_list_lessons",
        cypher="""
            MATCH (l:Lesson)
            WHERE l.archived = false
              AND l.trigger_pattern IS NOT NULL
              AND l.trigger_pattern <> ''
            RETURN l.lesson_id AS id, l.text_raw AS text,
                   l.trigger_pattern AS pattern, l.trigger_hook_type AS hook_type,
                   l.trigger_tool AS tool, l.trigger_project_scope AS scope,
                   l.pathway_strength AS strength
            ORDER BY l.pathway_strength DESC
            """,
        params=(),
        mutating=False,
        description="List active lessons with trigger patterns.",
    ),
    NamedQuery(
        name="cli.trigger_remove_procedure",
        cypher="""
            MATCH (p:Procedure) WHERE p.name = $name
            SET p.trigger_pattern = '',
                p.trigger_hook_type = '',
                p.trigger_tool = '',
                p.trigger_project_scope = ''
            """,
        params=("name",),
        mutating=True,
        description="Clear trigger metadata on a Procedure.",
    ),
    NamedQuery(
        name="cli.trigger_remove_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid})
            SET l.trigger_pattern = '',
                l.trigger_hook_type = '',
                l.trigger_tool = '',
                l.trigger_project_scope = ''
            """,
        params=("lid",),
        mutating=True,
        description="Clear trigger metadata on a Lesson.",
    ),

    # -----------------------------------------------------------------------
    # graph_repair.py queries
    # -----------------------------------------------------------------------
    NamedQuery(
        name="cli.graph_repair_find_outcome_candidates",
        cypher="""
            MATCH (l:Lesson)
            WHERE l.text_raw STARTS WITH 'Plan outcome ('
            AND NOT l.text_raw CONTAINS '[valence_trigger:'
            AND NOT l.text_raw CONTAINS '[valence_relabel:'
            AND (l.archived IS NULL OR l.archived = false)
            RETURN l.lesson_id AS lesson_id, l.text_raw AS text_raw
            """,
        params=(),
        mutating=False,
        description="Find outcome Lessons eligible for polarity repair.",
    ),
    NamedQuery(
        name="cli.graph_repair_linked_plan_failure",
        cypher="""
            MATCH (p:Plan)-[:PRODUCED_PLAN_LESSON]->(l:Lesson {lesson_id: $lid})
            WHERE p.valence_source = 'system' AND p.valence < 0
            SET p.valence = $valence
            """,
        params=("lid", "valence"),
        mutating=True,
        description="Correct linked Plan valence for failure outcome.",
    ),
    NamedQuery(
        name="cli.graph_repair_linked_plan_success",
        cypher="""
            MATCH (p:Plan)-[:PRODUCED_PLAN_LESSON]->(l:Lesson {lesson_id: $lid})
            WHERE p.valence_source = 'system' AND p.valence > 0
            SET p.valence = $valence
            """,
        params=("lid", "valence"),
        mutating=True,
        description="Correct linked Plan valence for success outcome.",
    ),
    NamedQuery(
        name="cli.graph_repair_flip_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid}) SET l.text_raw = $text, l.valence = $valence
            """,
        params=("lid", "text", "valence"),
        mutating=True,
        description="Update Lesson text and valence for repaired polarity.",
    ),
    NamedQuery(
        name="cli.graph_repair_archive_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid}) SET l.archived = true
            """,
        params=("lid",),
        mutating=True,
        description="Archive ambiguous Lesson during polarity repair.",
    ),
    NamedQuery(
        name="cli.graph_repair_find_plan_candidates",
        cypher="""
            MATCH (p:Plan)
            WHERE (p.valence_source IS NULL OR p.valence_source = 'system')
            AND p.valence IS NOT NULL
            AND (p.archived IS NULL OR p.archived = false)
            RETURN p.plan_id AS plan_id, p.goal AS goal, p.valence AS valence
            """,
        params=(),
        mutating=False,
        description="Find candidate Plans for valence repair.",
    ),
    NamedQuery(
        name="cli.graph_repair_plan_steps",
        cypher="""
            MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
            RETURN ps.actual_outcome AS actual_outcome ORDER BY ps.step_number ASC
            """,
        params=("pid",),
        mutating=False,
        description="Fetch PlanStep outcomes for a Plan.",
    ),
    NamedQuery(
        name="cli.graph_repair_set_plan_valence",
        cypher="""
            MATCH (p:Plan {plan_id: $pid}) SET p.valence = $valence, p.valence_source = $source
            """,
        params=("pid", "valence", "source"),
        mutating=True,
        description="Update Plan valence and source during valence repair.",
    ),
)
