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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?name WHERE {
                ?p a campy:Procedure ;
                   campy:name ?name .
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?p campy:procedure_id ?id }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?p campy:trigger_pattern ?old_pattern .
                ?p campy:trigger_hook_type ?old_hook_type .
                ?p campy:trigger_tool ?old_tool .
                ?p campy:trigger_project_scope ?old_scope .
            }
            INSERT {
                ?p campy:trigger_pattern ?pattern .
                ?p campy:trigger_hook_type ?hook_type .
                ?p campy:trigger_tool ?tool .
                ?p campy:trigger_project_scope ?scope .
            }
            WHERE {
                ?p a campy:Procedure ;
                   campy:procedure_id ?pid .
                OPTIONAL { ?p campy:trigger_pattern ?old_pattern }
                OPTIONAL { ?p campy:trigger_hook_type ?old_hook_type }
                OPTIONAL { ?p campy:trigger_tool ?old_tool }
                OPTIONAL { ?p campy:trigger_project_scope ?old_scope }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?l campy:lesson_id ?id }
                OPTIONAL { ?l campy:text_raw ?text }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?l campy:trigger_pattern ?old_pattern .
                ?l campy:trigger_hook_type ?old_hook_type .
                ?l campy:trigger_tool ?old_tool .
                ?l campy:trigger_project_scope ?old_scope .
            }
            INSERT {
                ?l campy:trigger_pattern ?pattern .
                ?l campy:trigger_hook_type ?hook_type .
                ?l campy:trigger_tool ?tool .
                ?l campy:trigger_project_scope ?scope .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                OPTIONAL { ?l campy:trigger_pattern ?old_pattern }
                OPTIONAL { ?l campy:trigger_hook_type ?old_hook_type }
                OPTIONAL { ?l campy:trigger_tool ?old_tool }
                OPTIONAL { ?l campy:trigger_project_scope ?old_scope }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?name ?pattern ?hook_type ?tool ?scope ?strength WHERE {
                ?p a campy:Procedure ;
                   campy:trigger_pattern ?pattern .
                FILTER(?pattern != "")
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?p campy:procedure_id ?id }
                OPTIONAL { ?p campy:name ?name }
                OPTIONAL { ?p campy:trigger_hook_type ?hook_type }
                OPTIONAL { ?p campy:trigger_tool ?tool }
                OPTIONAL { ?p campy:trigger_project_scope ?scope }
                OPTIONAL { ?p campy:pathway_strength ?strength }
            }
            ORDER BY DESC(?strength)
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text ?pattern ?hook_type ?tool ?scope ?strength WHERE {
                ?l a campy:Lesson ;
                   campy:trigger_pattern ?pattern .
                FILTER(?pattern != "")
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?l campy:lesson_id ?id }
                OPTIONAL { ?l campy:text_raw ?text }
                OPTIONAL { ?l campy:trigger_hook_type ?hook_type }
                OPTIONAL { ?l campy:trigger_tool ?tool }
                OPTIONAL { ?l campy:trigger_project_scope ?scope }
                OPTIONAL { ?l campy:pathway_strength ?strength }
            }
            ORDER BY DESC(?strength)
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?p campy:trigger_pattern ?old_pattern .
                ?p campy:trigger_hook_type ?old_hook_type .
                ?p campy:trigger_tool ?old_tool .
                ?p campy:trigger_project_scope ?old_scope .
            }
            INSERT {
                ?p campy:trigger_pattern "" .
                ?p campy:trigger_hook_type "" .
                ?p campy:trigger_tool "" .
                ?p campy:trigger_project_scope "" .
            }
            WHERE {
                ?p a campy:Procedure ;
                   campy:name ?name .
                OPTIONAL { ?p campy:trigger_pattern ?old_pattern }
                OPTIONAL { ?p campy:trigger_hook_type ?old_hook_type }
                OPTIONAL { ?p campy:trigger_tool ?old_tool }
                OPTIONAL { ?p campy:trigger_project_scope ?old_scope }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?l campy:trigger_pattern ?old_pattern .
                ?l campy:trigger_hook_type ?old_hook_type .
                ?l campy:trigger_tool ?old_tool .
                ?l campy:trigger_project_scope ?old_scope .
            }
            INSERT {
                ?l campy:trigger_pattern "" .
                ?l campy:trigger_hook_type "" .
                ?l campy:trigger_tool "" .
                ?l campy:trigger_project_scope "" .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                OPTIONAL { ?l campy:trigger_pattern ?old_pattern }
                OPTIONAL { ?l campy:trigger_hook_type ?old_hook_type }
                OPTIONAL { ?l campy:trigger_tool ?old_tool }
                OPTIONAL { ?l campy:trigger_project_scope ?old_scope }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?lesson_id ?text_raw WHERE {
                ?l a campy:Lesson ;
                   campy:text_raw ?text_raw .
                FILTER(STRSTARTS(?text_raw, "Plan outcome ("))
                FILTER(!CONTAINS(?text_raw, "[valence_trigger:"))
                FILTER(!CONTAINS(?text_raw, "[valence_relabel:"))
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?l campy:lesson_id ?lesson_id }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?p campy:valence ?old_valence .
            }
            INSERT {
                ?p campy:valence ?valence .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                ?p a campy:Plan ;
                   campy:PRODUCED_PLAN_LESSON ?l ;
                   campy:valence_source "system" ;
                   campy:valence ?old_valence .
                FILTER(?old_valence < "0.0"^^xsd:double)
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?p campy:valence ?old_valence .
            }
            INSERT {
                ?p campy:valence ?valence .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                ?p a campy:Plan ;
                   campy:PRODUCED_PLAN_LESSON ?l ;
                   campy:valence_source "system" ;
                   campy:valence ?old_valence .
                FILTER(?old_valence > "0.0"^^xsd:double)
            }
            """,
    ),
    NamedQuery(
        name="cli.graph_repair_flip_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid}) SET l.text_raw = $text, l.valence = $valence
            """,
        params=("lid", "text", "valence"),
        mutating=True,
        description="Update Lesson text and valence for repaired polarity.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?l campy:text_raw ?old_text .
                ?l campy:valence ?old_valence .
            }
            INSERT {
                ?l campy:text_raw ?text .
                ?l campy:valence ?valence .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                OPTIONAL { ?l campy:text_raw ?old_text }
                OPTIONAL { ?l campy:valence ?old_valence }
            }
            """,
    ),
    NamedQuery(
        name="cli.graph_repair_archive_lesson",
        cypher="""
            MATCH (l:Lesson {lesson_id: $lid}) SET l.archived = true
            """,
        params=("lid",),
        mutating=True,
        description="Archive ambiguous Lesson during polarity repair.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?l campy:archived ?old_archived .
            }
            INSERT {
                ?l campy:archived true .
            }
            WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?lid .
                OPTIONAL { ?l campy:archived ?old_archived }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?plan_id ?goal ?valence WHERE {
                ?p a campy:Plan ;
                   campy:valence ?valence .
                OPTIONAL { ?p campy:valence_source ?valence_source }
                FILTER(!BOUND(?valence_source) || ?valence_source = "system")
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?p campy:plan_id ?plan_id }
                OPTIONAL { ?p campy:goal ?goal }
            }
            """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?actual_outcome WHERE {
                ?p a campy:Plan ;
                   campy:plan_id ?pid .
                ?ps a campy:PlanStep ;
                    campy:STEP_OF ?p ;
                    campy:actual_outcome ?actual_outcome .
                OPTIONAL { ?ps campy:step_number ?step_number }
            }
            ORDER BY ASC(?step_number)
            """,
    ),
    NamedQuery(
        name="cli.graph_repair_set_plan_valence",
        cypher="""
            MATCH (p:Plan {plan_id: $pid}) SET p.valence = $valence, p.valence_source = $source
            """,
        params=("pid", "valence", "source"),
        mutating=True,
        description="Update Plan valence and source during valence repair.",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?p campy:valence ?old_valence .
                ?p campy:valence_source ?old_source .
            }
            INSERT {
                ?p campy:valence ?valence .
                ?p campy:valence_source ?source .
            }
            WHERE {
                ?p a campy:Plan ;
                   campy:plan_id ?pid .
                OPTIONAL { ?p campy:valence ?old_valence }
                OPTIONAL { ?p campy:valence_source ?old_source }
            }
            """,
    ),
)
