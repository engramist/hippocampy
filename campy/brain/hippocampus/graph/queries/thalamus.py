"""thalamus.py — named queries for Thalamus context tools, bundle compiler, wiki projection, etc.

B393: `sparql=` added per docs/rdf-schema-mapping.md to every query that has
a graph-traversal SPARQL equivalent. This is the batch's largest
Python-handler group: every `bundle_exact_*` / `bundle_semantic_*` /
`bundle_graph_anchors*` / `bundle_tabular_*` / `bundle_wiki_*` query below
computes `array_cosine_similarity(n.embedding, $query_embedding)` — a
brute-force vector search over the `embedding` column. Per spec §3.1/§5,
`FLOAT[384]` columns are never written to Oxigraph (they live in
sqlite-vec, keyed by the node's instance URI) — there is no `campy:embedding`
triple to match against, so none of these can get a `sparql=` string. They
are documented Python-handler exceptions, same category as
`QUERY_VECTOR_INDEX`/`QUERY_FTS_INDEX` even though the Cypher text itself
never calls either macro directly. `thalamus.analogical_get_quest_embedding`
is the same case by extension: it RETURNs the raw embedding column, which
likewise cannot be projected from Oxigraph.

Other conventions shared with the rest of the B393 batch (full rationale
in capture.py's and working_memory.py's module docstrings): `LIMIT $param`
drops the `LIMIT` clause (SPARQL's `LIMIT` takes only an integer literal;
`ORDER BY` is kept and the caller-supplied limit becomes a post-query
slice); array-valued params (`$domains`) are an empty `VALUES ?var { }`
block for the future binding layer to expand; un-aliased Cypher
`RETURN n.prop` columns are named `?prop` (bare property name) in SPARQL.

`label(r)`/`type(r)` (Cypher's relationship-type function, used where a
traversal spans a fixed set of alternative predicates) has no direct
SPARQL equivalent either — translated as a free predicate variable
constrained by `VALUES`, with `STRAFTER(STR(?p), "https://campy.dev/ns#")`
recovering the bare predicate name Cypher's `label()`/`type()` returns.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_GRAPH_REL_TYPES = (
    "REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER"
    "|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO"
)

# The 9 relationship types _GRAPH_REL_TYPES spans, as `campy:` SPARQL terms,
# for the VALUES-constrained free-predicate translation of Cypher's
# `[r:A|B|C]` alternation (all 9 are "star" class in EDGE_REIFICATION, but
# bundle_graph_* below never reads their quoted-triple properties — only
# the predicate identity itself — so no `<< >>` annotation lookup is
# needed here).
_GRAPH_REL_VALUES = (
    "campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS "
    "campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS "
    "campy:ALTERNATIVE_TO"
)

THALAMUS_QUERIES: tuple[NamedQuery, ...] = (
    # _shared.py
    NamedQuery(
        name="thalamus.session_active_plan_id",
        cypher="MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
               "WHERE p.status = 'active' "
               "RETURN p.plan_id "
               "ORDER BY p.created_at DESC LIMIT 1",
        params=("sid",),
        mutating=False,
        description="Get active plan_id for session",
        # PLANNED_IN is "plain" in EDGE_REIFICATION.
        sparql="""
            SELECT ?plan_id WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?p campy:PLANNED_IN ?s ;
                   a campy:Plan ;
                   campy:plan_id ?plan_id ;
                   campy:status ?status ;
                   campy:created_at ?created_at .
                FILTER(?status = "active")
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
            """,
    ),

    # trigger_manifest.py
    NamedQuery(
        name="thalamus.trigger_manifest_procedures",
        cypher="MATCH (p:Procedure) "
               "WHERE p.archived = false "
               "  AND p.trigger_pattern IS NOT NULL "
               "  AND p.trigger_pattern <> '' "
               "RETURN p.procedure_id AS id, p.name AS name, "
               "       p.description AS description, p.steps_json AS steps_json, "
               "       p.trigger_pattern AS pattern, p.trigger_hook_type AS hook_type, "
               "       p.trigger_tool AS tool, p.trigger_project_scope AS project_scope, "
               "       p.pathway_strength AS strength, p.domain AS domain "
               "ORDER BY p.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Get active procedures with trigger patterns",
        sparql="""
            SELECT ?id ?name ?description ?steps_json ?pattern ?hook_type
                   ?tool ?project_scope ?strength ?domain WHERE {
                ?p a campy:Procedure ;
                   campy:procedure_id ?id ;
                   campy:name ?name ;
                   campy:description ?description ;
                   campy:steps_json ?steps_json ;
                   campy:trigger_pattern ?pattern ;
                   campy:pathway_strength ?strength ;
                   campy:domain ?domain .
                OPTIONAL { ?p campy:trigger_hook_type ?hook_type }
                OPTIONAL { ?p campy:trigger_tool ?tool }
                OPTIONAL { ?p campy:trigger_project_scope ?project_scope }
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER(?pattern != "")
            }
            ORDER BY DESC(?strength)
            """,
    ),
    NamedQuery(
        name="thalamus.trigger_manifest_lessons",
        cypher="MATCH (l:Lesson) "
               "WHERE l.archived = false "
               "  AND l.trigger_pattern IS NOT NULL "
               "  AND l.trigger_pattern <> '' "
               "RETURN l.lesson_id AS id, l.text_raw AS text, "
               "       l.lesson_type AS lesson_type, "
               "       l.trigger_pattern AS pattern, l.trigger_hook_type AS hook_type, "
               "       l.trigger_tool AS tool, l.trigger_project_scope AS project_scope, "
               "       l.pathway_strength AS strength, l.domain AS domain "
               "ORDER BY l.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Get active lessons with trigger patterns",
        sparql="""
            SELECT ?id ?text ?lesson_type ?pattern ?hook_type ?tool
                   ?project_scope ?strength ?domain WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_id ?id ;
                   campy:text_raw ?text ;
                   campy:lesson_type ?lesson_type ;
                   campy:trigger_pattern ?pattern ;
                   campy:pathway_strength ?strength ;
                   campy:domain ?domain .
                OPTIONAL { ?l campy:trigger_hook_type ?hook_type }
                OPTIONAL { ?l campy:trigger_tool ?tool }
                OPTIONAL { ?l campy:trigger_project_scope ?project_scope }
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER(?pattern != "")
            }
            ORDER BY DESC(?strength)
            """,
    ),

    # file_bridge.py
    NamedQuery(
        name="thalamus.file_bridge_concepts",
        cypher="MATCH (c:Concept) "
               "WHERE c.archived = false AND c.confidence >= 0.6 "
               "RETURN c.concept_id AS id, c.prefLabel AS name, "
               "       c.text_raw AS definition, c.gist_class AS gist_class, "
               "       c.altLabel AS alt_labels, c.pathway_strength AS strength "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch concepts for CONTEXT.md file bridge",
        # NOTE (pre-existing, not introduced by this translation):
        # `c.prefLabel`/`c.altLabel` reference columns schema.py never
        # declares on Concept (SKOS labels live on separate `Label` nodes
        # via HAS_PREF_LABEL/HAS_ALT_LABEL) — the same class of latent bug
        # B389's report flagged elsewhere (e.g. HAS_ALT_LABEL's create-with-
        # undeclared-property call sites). Preserved faithfully: OPTIONAL
        # so the row still projects, matching that these always come back
        # unset rather than raising.
        sparql="""
            SELECT ?id ?name ?definition ?gist_class ?alt_labels ?strength WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?id ;
                   campy:confidence ?confidence ;
                   campy:pathway_strength ?strength .
                OPTIONAL { ?c campy:prefLabel ?name }
                OPTIONAL { ?c campy:text_raw ?definition }
                OPTIONAL { ?c campy:gist_class ?gist_class }
                OPTIONAL { ?c campy:altLabel ?alt_labels }
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER(?confidence >= "0.6"^^xsd:double)
            }
            ORDER BY DESC(?strength)
            """,
    ),
    NamedQuery(
        name="thalamus.file_bridge_concept_relationships",
        cypher="MATCH (a:Concept)-[r]->(b:Concept) "
               "WHERE a.archived = false AND b.archived = false "
               "RETURN a.prefLabel AS from_name, type(r) AS rel_type, "
               "       b.prefLabel AS to_name "
               "ORDER BY a.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch concept relationships for CONTEXT.md file bridge",
        # Free predicate (no fixed alternation here, unlike bundle_graph_*
        # below) — any Concept->Concept relationship type qualifies, same
        # as Cypher's unbound `[r]`. See prefLabel/altLabel note above.
        sparql="""
            SELECT ?from_name ?rel_type ?to_name WHERE {
                ?a a campy:Concept ;
                   campy:pathway_strength ?a_strength .
                ?b a campy:Concept .
                ?a ?p ?b .
                BIND(STRAFTER(STR(?p), "https://campy.dev/ns#") AS ?rel_type)
                OPTIONAL { ?a campy:prefLabel ?from_name }
                OPTIONAL { ?b campy:prefLabel ?to_name }
                OPTIONAL { ?a campy:archived ?a_archived }
                FILTER(!BOUND(?a_archived) || ?a_archived = false)
                OPTIONAL { ?b campy:archived ?b_archived }
                FILTER(!BOUND(?b_archived) || ?b_archived = false)
            }
            ORDER BY DESC(?a_strength)
            """,
    ),
    NamedQuery(
        name="thalamus.file_bridge_global_constraints",
        cypher="MATCH (g:GlobalConstraint) "
               "WHERE g.archived = false "
               "RETURN g.text_raw AS text "
               "ORDER BY g.pathway_strength DESC LIMIT 3",
        params=(),
        mutating=False,
        description="Fetch global constraints for CONTEXT.md file bridge",
        sparql="""
            SELECT ?text WHERE {
                ?g a campy:GlobalConstraint ;
                   campy:text_raw ?text ;
                   campy:pathway_strength ?strength .
                OPTIONAL { ?g campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?strength)
            LIMIT 3
            """,
    ),
    NamedQuery(
        name="thalamus.file_bridge_decisions",
        cypher="MATCH (d:Decision) "
               "WHERE d.archived = false AND d.confidence >= 0.8 "
               "RETURN d.decision_id AS id, d.prefLabel AS title, "
               "       d.text_raw AS context, d.created_at AS created_at "
               "ORDER BY d.created_at ASC",
        params=(),
        mutating=False,
        description="Fetch decisions for ADR generation",
        # See prefLabel note on thalamus.file_bridge_concepts above.
        sparql="""
            SELECT ?id ?title ?context ?created_at WHERE {
                ?d a campy:Decision ;
                   campy:decision_id ?id ;
                   campy:text_raw ?context ;
                   campy:confidence ?confidence ;
                   campy:created_at ?created_at .
                OPTIONAL { ?d campy:prefLabel ?title }
                OPTIONAL { ?d campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                FILTER(?confidence >= "0.8"^^xsd:double)
            }
            ORDER BY ASC(?created_at)
            """,
    ),

    # artifacts.py
    NamedQuery(
        name="thalamus.artifacts_find_existing",
        cypher="MATCH (wa:WorkArtifact {file_path: $fp}) RETURN wa.artifact_id",
        params=("fp",),
        mutating=False,
        description="Find existing WorkArtifact by file_path",
        sparql="""
            SELECT ?artifact_id WHERE {
                ?wa a campy:WorkArtifact ;
                    campy:file_path ?fp ;
                    campy:artifact_id ?artifact_id .
            }
            """,
    ),
    NamedQuery(
        name="thalamus.artifacts_update",
        cypher="MATCH (wa:WorkArtifact {file_path: $fp}) "
               "SET wa.last_modified_at = timestamp($ts), "
               "    wa.title = CASE WHEN $ti IS NOT NULL THEN $ti ELSE wa.title END, "
               "    wa.summary = CASE WHEN $su IS NOT NULL THEN $su ELSE wa.summary END, "
               "    wa.linked_card = CASE WHEN $lc IS NOT NULL THEN $lc ELSE wa.linked_card END, "
               "    wa.document_type = CASE WHEN $dt IS NOT NULL THEN $dt ELSE wa.document_type END",
        params=("fp", "ts", "ti", "su", "lc", "dt"),
        mutating=True,
        description="Update WorkArtifact properties",
        # The Cypher CASE tests whether the CALLER passed a value for an
        # optional field (not whether a stored property is null — a
        # different question from spec §3.4's NULL-vs-absent rule). COALESCE
        # picks the incoming param when bound, else keeps the existing
        # stored value. This assumes the (not-yet-built) binding layer
        # leaves an unset optional param genuinely UNBOUND rather than
        # substituting a stringified `None` — flagged as a dependency on
        # that future infrastructure, same category as B391's "params on
        # Update text" gap.
        sparql="""
            DELETE {
                ?wa campy:last_modified_at ?old_last_modified_at .
                ?wa campy:title ?old_title .
                ?wa campy:summary ?old_summary .
                ?wa campy:linked_card ?old_linked_card .
                ?wa campy:document_type ?old_document_type .
            }
            INSERT {
                ?wa campy:last_modified_at ?ts .
                ?wa campy:title ?new_title .
                ?wa campy:summary ?new_summary .
                ?wa campy:linked_card ?new_linked_card .
                ?wa campy:document_type ?new_document_type .
            }
            WHERE {
                ?wa a campy:WorkArtifact ;
                    campy:file_path ?fp .
                OPTIONAL { ?wa campy:last_modified_at ?old_last_modified_at }
                OPTIONAL { ?wa campy:title ?old_title }
                OPTIONAL { ?wa campy:summary ?old_summary }
                OPTIONAL { ?wa campy:linked_card ?old_linked_card }
                OPTIONAL { ?wa campy:document_type ?old_document_type }
                BIND(COALESCE(?ti, ?old_title) AS ?new_title)
                BIND(COALESCE(?su, ?old_summary) AS ?new_summary)
                BIND(COALESCE(?lc, ?old_linked_card) AS ?new_linked_card)
                BIND(COALESCE(?dt, ?old_document_type) AS ?new_document_type)
            }
            """,
    ),
    NamedQuery(
        name="thalamus.artifacts_create",
        cypher="CREATE (wa:WorkArtifact {\n"
               "  artifact_id: $aid, file_path: $fp, document_type: $dt,\n"
               "  title: $ti, summary: $su, linked_card: $lc,\n"
               "  session_id: $sess, agent_source: $ag_src,\n"
               "  created_at: timestamp($ts), last_modified_at: timestamp($ts)\n"
               "})",
        params=("aid", "fp", "dt", "ti", "su", "lc", "sess", "ag_src", "ts"),
        mutating=True,
        description="Create WorkArtifact node",
        sparql="""
            INSERT {
                ?wa a campy:WorkArtifact ;
                    campy:artifact_id ?aid ;
                    campy:file_path ?fp ;
                    campy:document_type ?dt ;
                    campy:title ?ti ;
                    campy:summary ?su ;
                    campy:linked_card ?lc ;
                    campy:session_id ?sess ;
                    campy:agent_source ?ag_src ;
                    campy:created_at ?ts ;
                    campy:last_modified_at ?ts .
            }
            WHERE {
                BIND(IRI(CONCAT("https://campy.dev/id/WorkArtifact/", ?aid)) AS ?wa)
            }
            """,
    ),
    NamedQuery(
        name="thalamus.artifacts_link_session",
        cypher="MATCH (wa:WorkArtifact {artifact_id: $aid}), (s:Session {session_id: $sid}) "
               "MERGE (wa)-[:CREATED_IN]->(s)",
        params=("aid", "sid"),
        mutating=True,
        description="Link WorkArtifact CREATED_IN Session",
        # CREATED_IN is "plain" in EDGE_REIFICATION.
        sparql="""
            INSERT {
                ?wa campy:CREATED_IN ?s .
            }
            WHERE {
                ?wa a campy:WorkArtifact ;
                    campy:artifact_id ?aid .
                ?s a campy:Session ;
                   campy:session_id ?sid .
            }
            """,
    ),

    # work_summary.py
    NamedQuery(
        name="thalamus.work_summary_active_plan",
        cypher="MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: $sid}) "
               "WHERE p.archived = false "
               "RETURN p.plan_id, p.goal "
               "ORDER BY p.created_at DESC LIMIT 1",
        params=("sid",),
        mutating=False,
        description="Fetch active plan for session work summary",
        sparql="""
            SELECT ?plan_id ?goal WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?p campy:PLANNED_IN ?s ;
                   a campy:Plan ;
                   campy:plan_id ?plan_id ;
                   campy:goal ?goal ;
                   campy:created_at ?created_at .
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.work_summary_recent_decisions",
        cypher="MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: $sid}) "
               "WHERE d.archived = false "
               "RETURN d.text_raw "
               "ORDER BY d.created_at DESC LIMIT 5",
        params=("sid",),
        mutating=False,
        description="Fetch recent decisions for session work summary",
        sparql="""
            SELECT ?text_raw WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?d campy:ESTABLISHED_IN ?s ;
                   a campy:Decision ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                OPTIONAL { ?d campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?created_at)
            LIMIT 5
            """,
    ),
    NamedQuery(
        name="thalamus.work_summary_files_in_flight",
        cypher="MATCH (wa:WorkArtifact)-[:CREATED_IN]->(s:Session {session_id: $sid}) "
               "RETURN wa.file_path, wa.title "
               "ORDER BY wa.last_modified_at DESC LIMIT 10",
        params=("sid",),
        mutating=False,
        description="Fetch files in flight for session work summary",
        sparql="""
            SELECT ?file_path ?title WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?wa campy:CREATED_IN ?s ;
                    a campy:WorkArtifact ;
                    campy:file_path ?file_path ;
                    campy:last_modified_at ?last_modified_at .
                OPTIONAL { ?wa campy:title ?title }
            }
            ORDER BY DESC(?last_modified_at)
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.work_summary_get_existing",
        cypher="MATCH (ws:WorkSummary {summary_id: $sid}) RETURN ws.turn_count",
        params=("sid",),
        mutating=False,
        description="Fetch existing WorkSummary turn_count",
        sparql="""
            SELECT ?turn_count WHERE {
                ?ws a campy:WorkSummary ;
                    campy:summary_id ?sid .
                OPTIONAL { ?ws campy:turn_count ?turn_count }
            }
            """,
    ),
    NamedQuery(
        name="thalamus.work_summary_update",
        # B399: param was `$as` (matching the `agent_source` field name too
        # loosely abbreviated); `as` is a reserved Python keyword, so the
        # `gw.run(..., as=agent_source)` call site was a SyntaxError and the
        # module could not even be imported. Renamed to `$agent_source`.
        cypher="MATCH (ws:WorkSummary {summary_id: $sid}) "
               "SET ws.resume_line = $rl, ws.turn_count = $tc, "
               "    ws.last_updated_at = timestamp($ts), ws.git_branch = $br, "
               "    ws.git_commit = $co, ws.agent_source = $agent_source, ws.active_card = $card, "
               "    ws.snapshot_text = CASE WHEN $has_snap = true THEN $snap ELSE ws.snapshot_text END",
        params=("sid", "rl", "tc", "ts", "br", "co", "agent_source", "card", "has_snap", "snap"),
        mutating=True,
        description="Update WorkSummary node",
        # Unlike artifacts_update's CASE, `$has_snap` is an explicit boolean
        # flag the caller sets deliberately (not a NULL-param proxy) —
        # SPARQL's IF() maps directly, no binding-layer assumption needed.
        sparql="""
            DELETE {
                ?ws campy:resume_line ?old_resume_line .
                ?ws campy:turn_count ?old_turn_count .
                ?ws campy:last_updated_at ?old_last_updated_at .
                ?ws campy:git_branch ?old_git_branch .
                ?ws campy:git_commit ?old_git_commit .
                ?ws campy:agent_source ?old_agent_source .
                ?ws campy:active_card ?old_active_card .
                ?ws campy:snapshot_text ?old_snapshot_text .
            }
            INSERT {
                ?ws campy:resume_line ?rl .
                ?ws campy:turn_count ?tc .
                ?ws campy:last_updated_at ?ts .
                ?ws campy:git_branch ?br .
                ?ws campy:git_commit ?co .
                ?ws campy:agent_source ?agent_source .
                ?ws campy:active_card ?card .
                ?ws campy:snapshot_text ?new_snapshot_text .
            }
            WHERE {
                ?ws a campy:WorkSummary ;
                    campy:summary_id ?sid .
                OPTIONAL { ?ws campy:resume_line ?old_resume_line }
                OPTIONAL { ?ws campy:turn_count ?old_turn_count }
                OPTIONAL { ?ws campy:last_updated_at ?old_last_updated_at }
                OPTIONAL { ?ws campy:git_branch ?old_git_branch }
                OPTIONAL { ?ws campy:git_commit ?old_git_commit }
                OPTIONAL { ?ws campy:agent_source ?old_agent_source }
                OPTIONAL { ?ws campy:active_card ?old_active_card }
                OPTIONAL { ?ws campy:snapshot_text ?old_snapshot_text }
                BIND(IF(?has_snap = true, ?snap, ?old_snapshot_text) AS ?new_snapshot_text)
            }
            """,
    ),
    NamedQuery(
        name="thalamus.work_summary_create",
        # B399: see work_summary_update above — `$as` renamed to
        # `$agent_source` (was a Python SyntaxError at the call site).
        cypher="CREATE (ws:WorkSummary {\n"
               "  summary_id: $sid, session_id: $sess, agent_source: $agent_source,\n"
               "  git_branch: $br, git_commit: $co, active_card: $card,\n"
               "  resume_line: $rl, snapshot_text: $snap, turn_count: $tc,\n"
               "  last_updated_at: timestamp($ts)\n"
               "})",
        params=("sid", "sess", "agent_source", "br", "co", "card", "rl", "snap", "tc", "ts"),
        mutating=True,
        description="Create WorkSummary node",
        sparql="""
            INSERT {
                ?ws a campy:WorkSummary ;
                    campy:summary_id ?sid ;
                    campy:session_id ?sess ;
                    campy:agent_source ?agent_source ;
                    campy:git_branch ?br ;
                    campy:git_commit ?co ;
                    campy:active_card ?card ;
                    campy:resume_line ?rl ;
                    campy:snapshot_text ?snap ;
                    campy:turn_count ?tc ;
                    campy:last_updated_at ?ts .
            }
            WHERE {
                BIND(IRI(CONCAT("https://campy.dev/id/WorkSummary/", ?sid)) AS ?ws)
            }
            """,
    ),

    # analogical.py
    NamedQuery(
        name="thalamus.analogical_resolve_quest_concept",
        cypher="MATCH (art:Concept {concept_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Concept node",
        sparql="""
            SELECT ?quest_id ?name WHERE {
                ?art a campy:Concept ;
                     campy:concept_id ?nid .
                ?msg a campy:Message ;
                     campy:ESTABLISHED ?art ;
                     campy:SENT_IN ?sess .
                ?sess a campy:Session ;
                      campy:WORKING_ON ?q .
                ?q a campy:MainQuest ;
                   campy:quest_id ?quest_id ;
                   campy:name ?name .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.analogical_resolve_quest_decision",
        cypher="MATCH (art:Decision {decision_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Decision node",
        sparql="""
            SELECT ?quest_id ?name WHERE {
                ?art a campy:Decision ;
                     campy:decision_id ?nid .
                ?msg a campy:Message ;
                     campy:ESTABLISHED ?art ;
                     campy:SENT_IN ?sess .
                ?sess a campy:Session ;
                      campy:WORKING_ON ?q .
                ?q a campy:MainQuest ;
                   campy:quest_id ?quest_id ;
                   campy:name ?name .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.analogical_resolve_quest_constraint",
        cypher="MATCH (art:Constraint {constraint_id: $nid}) "
               "MATCH (msg:Message)-[:ESTABLISHED]->(art) "
               "MATCH (msg)-[:SENT_IN]->(sess:Session) "
               "MATCH (sess)-[:WORKING_ON]->(q:MainQuest) "
               "RETURN q.quest_id, q.name LIMIT 1",
        params=("nid",),
        mutating=False,
        description="Resolve MainQuest for Constraint node",
        sparql="""
            SELECT ?quest_id ?name WHERE {
                ?art a campy:Constraint ;
                     campy:constraint_id ?nid .
                ?msg a campy:Message ;
                     campy:ESTABLISHED ?art ;
                     campy:SENT_IN ?sess .
                ?sess a campy:Session ;
                      campy:WORKING_ON ?q .
                ?q a campy:MainQuest ;
                   campy:quest_id ?quest_id ;
                   campy:name ?name .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.analogical_get_quest_embedding",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.embedding, q.name",
        params=("qid",),
        mutating=False,
        description="Get MainQuest embedding and name",
        # No sparql=: `q.embedding` is FLOAT[384] — never written to
        # Oxigraph (spec §3.1/§5). Python handler: sqlite-vec lookup by
        # this node's instance URI for the vector, plus a trivial
        # `campy:name` read (or a dedicated small query) for the name.
    ),

    # wiki_projection.py
    NamedQuery(
        name="thalamus.wiki_lessons",
        cypher="MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type = 'synthesis' "
               "RETURN l.lesson_id, l.text_raw, l.domain, l.pathway_strength "
               "ORDER BY l.pathway_strength DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch synthesis lessons for wiki projection",
        sparql="""
            SELECT ?lesson_id ?text_raw ?domain ?pathway_strength WHERE {
                ?l a campy:Lesson ;
                   campy:lesson_type "synthesis" ;
                   campy:lesson_id ?lesson_id ;
                   campy:text_raw ?text_raw ;
                   campy:domain ?domain ;
                   campy:pathway_strength ?pathway_strength .
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?pathway_strength)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_lessons_by_domain",
        cypher="MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type = 'synthesis' AND l.domain IN $domains "
               "RETURN l.lesson_id, l.text_raw, l.domain, l.pathway_strength "
               "ORDER BY l.pathway_strength DESC LIMIT $lim",
        params=("domains", "lim"),
        mutating=False,
        description="Fetch synthesis lessons by domain for wiki projection",
        sparql="""
            SELECT ?lesson_id ?text_raw ?domain ?pathway_strength WHERE {
                VALUES ?domain { }
                ?l a campy:Lesson ;
                   campy:lesson_type "synthesis" ;
                   campy:domain ?domain ;
                   campy:lesson_id ?lesson_id ;
                   campy:text_raw ?text_raw ;
                   campy:pathway_strength ?pathway_strength .
                OPTIONAL { ?l campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?pathway_strength)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_procedures",
        cypher="MATCH (p:Procedure) WHERE p.archived = false "
               "RETURN p.procedure_id, p.name, p.description, p.archetype "
               "ORDER BY p.name LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch procedures for wiki projection",
        sparql="""
            SELECT ?procedure_id ?name ?description ?archetype WHERE {
                ?p a campy:Procedure ;
                   campy:procedure_id ?procedure_id ;
                   campy:name ?name ;
                   campy:description ?description ;
                   campy:archetype ?archetype .
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY ASC(?name)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_procedures_by_domain",
        cypher="MATCH (p:Procedure) WHERE p.archived = false AND p.domain IN $domains "
               "RETURN p.procedure_id, p.name, p.description, p.archetype "
               "ORDER BY p.name LIMIT $lim",
        params=("domains", "lim"),
        mutating=False,
        description="Fetch procedures by domain for wiki projection",
        sparql="""
            SELECT ?procedure_id ?name ?description ?archetype WHERE {
                VALUES ?domain { }
                ?p a campy:Procedure ;
                   campy:domain ?domain ;
                   campy:procedure_id ?procedure_id ;
                   campy:name ?name ;
                   campy:description ?description ;
                   campy:archetype ?archetype .
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY ASC(?name)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_runs",
        cypher="MATCH (r:ArcRun) "
               "RETURN r.run_id, r.summary, r.domain, r.status, r.task_count, "
               "       r.solved_count, r.failed_count, r.step_count, r.source_files "
               "ORDER BY r.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcRuns for wiki projection",
        sparql="""
            SELECT ?run_id ?summary ?domain ?status ?task_count ?solved_count
                   ?failed_count ?step_count ?source_files WHERE {
                ?r a campy:ArcRun ;
                   campy:run_id ?run_id ;
                   campy:domain ?domain ;
                   campy:status ?status ;
                   campy:task_count ?task_count ;
                   campy:solved_count ?solved_count ;
                   campy:failed_count ?failed_count ;
                   campy:step_count ?step_count ;
                   campy:created_at ?created_at .
                OPTIONAL { ?r campy:summary ?summary }
                OPTIONAL { ?r campy:source_files ?source_files }
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_run_wm_summary",
        cypher="MATCH (r:ArcRun {run_id: $run_id})-[:ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(s:ArcWorldModelSummary) "
               "RETURN s.graph_bounded, s.compiler_active, s.falsification_active, "
               "       s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
               "       s.single_action_stall_detected, s.full_reasoning_cycles_avoided "
               "ORDER BY s.created_at DESC LIMIT 1",
        params=("run_id",),
        mutating=False,
        description="Fetch ArcWorldModelSummary for an ArcRun",
        # ARC_RUN_HAS_WORLD_MODEL_SUMMARY is "plain" in EDGE_REIFICATION.
        sparql="""
            SELECT ?graph_bounded ?compiler_active ?falsification_active
                   ?reasoning_gated ?planner_grounded ?memory_transfer_active
                   ?single_action_stall_detected ?full_reasoning_cycles_avoided WHERE {
                ?r a campy:ArcRun ;
                   campy:run_id ?run_id .
                ?r campy:ARC_RUN_HAS_WORLD_MODEL_SUMMARY ?s .
                ?s a campy:ArcWorldModelSummary ;
                   campy:graph_bounded ?graph_bounded ;
                   campy:compiler_active ?compiler_active ;
                   campy:falsification_active ?falsification_active ;
                   campy:reasoning_gated ?reasoning_gated ;
                   campy:planner_grounded ?planner_grounded ;
                   campy:memory_transfer_active ?memory_transfer_active ;
                   campy:single_action_stall_detected ?single_action_stall_detected ;
                   campy:full_reasoning_cycles_avoided ?full_reasoning_cycles_avoided ;
                   campy:created_at ?created_at .
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_task_results",
        cypher="MATCH (t:ArcTaskResult) "
               "RETURN t.task_result_id, t.summary, t.domain, t.status, t.task_id, "
               "       t.puzzle_id, t.correct, t.steps, t.failure_class "
               "ORDER BY t.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcTaskResults for wiki projection",
        sparql="""
            SELECT ?task_result_id ?summary ?domain ?status ?task_id ?puzzle_id
                   ?correct ?steps ?failure_class WHERE {
                ?t a campy:ArcTaskResult ;
                   campy:task_result_id ?task_result_id ;
                   campy:domain ?domain ;
                   campy:status ?status ;
                   campy:task_id ?task_id ;
                   campy:puzzle_id ?puzzle_id ;
                   campy:correct ?correct ;
                   campy:steps ?steps ;
                   campy:created_at ?created_at .
                OPTIONAL { ?t campy:summary ?summary }
                OPTIONAL { ?t campy:failure_class ?failure_class }
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_artifacts",
        cypher="MATCH (a:ArcArtifact) "
               "RETURN a.artifact_id, a.artifact_kind, a.path, a.content_hash, "
               "       a.record_count, a.captured_at, a.ingested_at, a.domain, a.summary "
               "ORDER BY a.ingested_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcArtifacts for wiki projection",
        sparql="""
            SELECT ?artifact_id ?artifact_kind ?path ?content_hash ?record_count
                   ?captured_at ?ingested_at ?domain ?summary WHERE {
                ?a a campy:ArcArtifact ;
                   campy:artifact_id ?artifact_id ;
                   campy:artifact_kind ?artifact_kind ;
                   campy:path ?path ;
                   campy:content_hash ?content_hash ;
                   campy:record_count ?record_count ;
                   campy:ingested_at ?ingested_at ;
                   campy:domain ?domain .
                OPTIONAL { ?a campy:captured_at ?captured_at }
                OPTIONAL { ?a campy:summary ?summary }
            }
            ORDER BY DESC(?ingested_at)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_events",
        cypher="MATCH (e:ArcEvent) "
               "RETURN e.event_id, e.run_id, e.task_id, e.event_type, e.timestamp, "
               "       e.step_index, e.actor, e.tool_name, e.action_name, e.outcome, "
               "       e.domain, e.summary "
               "ORDER BY e.timestamp DESC, e.step_index DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcEvents for wiki projection",
        sparql="""
            SELECT ?event_id ?run_id ?task_id ?event_type ?timestamp ?step_index
                   ?actor ?tool_name ?action_name ?outcome ?domain ?summary WHERE {
                ?e a campy:ArcEvent ;
                   campy:event_id ?event_id ;
                   campy:run_id ?run_id ;
                   campy:task_id ?task_id ;
                   campy:event_type ?event_type ;
                   campy:timestamp ?timestamp ;
                   campy:step_index ?step_index ;
                   campy:domain ?domain .
                OPTIONAL { ?e campy:actor ?actor }
                OPTIONAL { ?e campy:tool_name ?tool_name }
                OPTIONAL { ?e campy:action_name ?action_name }
                OPTIONAL { ?e campy:outcome ?outcome }
                OPTIONAL { ?e campy:summary ?summary }
            }
            ORDER BY DESC(?timestamp) DESC(?step_index)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_wm_steps",
        cypher="MATCH (s:ArcWorldModelStep) "
               "RETURN s.world_model_step_id, s.task_id, s.step_index, s.node_count, "
               "       s.edge_count, s.compiled_claim_count, s.action_effect_class, s.reasoning_mode, "
               "       s.planner_candidate_count, s.single_action_stall_detected, s.summary "
               "ORDER BY s.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcWorldModelSteps for wiki projection",
        sparql="""
            SELECT ?world_model_step_id ?task_id ?step_index ?node_count ?edge_count
                   ?compiled_claim_count ?action_effect_class ?reasoning_mode
                   ?planner_candidate_count ?single_action_stall_detected ?summary WHERE {
                ?s a campy:ArcWorldModelStep ;
                   campy:world_model_step_id ?world_model_step_id ;
                   campy:task_id ?task_id ;
                   campy:step_index ?step_index ;
                   campy:node_count ?node_count ;
                   campy:edge_count ?edge_count ;
                   campy:compiled_claim_count ?compiled_claim_count ;
                   campy:single_action_stall_detected ?single_action_stall_detected ;
                   campy:created_at ?created_at .
                OPTIONAL { ?s campy:action_effect_class ?action_effect_class }
                OPTIONAL { ?s campy:reasoning_mode ?reasoning_mode }
                OPTIONAL { ?s campy:planner_candidate_count ?planner_candidate_count }
                OPTIONAL { ?s campy:summary ?summary }
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_wm_summaries",
        cypher="MATCH (s:ArcWorldModelSummary) "
               "RETURN s.world_model_summary_id, s.task_id, s.graph_bounded, s.compiler_active, "
               "       s.falsification_active, s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
               "       s.single_action_stall_detected, s.full_reasoning_cycles_avoided, s.summary "
               "ORDER BY s.created_at DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcWorldModelSummaries for wiki projection",
        sparql="""
            SELECT ?world_model_summary_id ?task_id ?graph_bounded ?compiler_active
                   ?falsification_active ?reasoning_gated ?planner_grounded
                   ?memory_transfer_active ?single_action_stall_detected
                   ?full_reasoning_cycles_avoided ?summary WHERE {
                ?s a campy:ArcWorldModelSummary ;
                   campy:world_model_summary_id ?world_model_summary_id ;
                   campy:task_id ?task_id ;
                   campy:graph_bounded ?graph_bounded ;
                   campy:compiler_active ?compiler_active ;
                   campy:falsification_active ?falsification_active ;
                   campy:reasoning_gated ?reasoning_gated ;
                   campy:planner_grounded ?planner_grounded ;
                   campy:memory_transfer_active ?memory_transfer_active ;
                   campy:single_action_stall_detected ?single_action_stall_detected ;
                   campy:full_reasoning_cycles_avoided ?full_reasoning_cycles_avoided ;
                   campy:created_at ?created_at .
                OPTIONAL { ?s campy:summary ?summary }
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="thalamus.wiki_arc_mechanics",
        cypher="MATCH (m:ArcMechanic) "
               "RETURN m.mechanic_id, m.name, m.signature, m.confidence, "
               "       m.terminal_relevance, m.coordinate_relevance, m.evidence_count, m.summary "
               "ORDER BY m.confidence DESC LIMIT $lim",
        params=("lim",),
        mutating=False,
        description="Fetch ArcMechanics for wiki projection",
        sparql="""
            SELECT ?mechanic_id ?name ?signature ?confidence ?terminal_relevance
                   ?coordinate_relevance ?evidence_count ?summary WHERE {
                ?m a campy:ArcMechanic ;
                   campy:mechanic_id ?mechanic_id ;
                   campy:name ?name ;
                   campy:signature ?signature ;
                   campy:confidence ?confidence ;
                   campy:terminal_relevance ?terminal_relevance ;
                   campy:coordinate_relevance ?coordinate_relevance ;
                   campy:evidence_count ?evidence_count .
                OPTIONAL { ?m campy:summary ?summary }
            }
            ORDER BY DESC(?confidence)
            """,
    ),

    # context_tools.py
    # Target resolution: exact
    NamedQuery(
        name="thalamus.context_resolve_exact_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.name = $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in MainQuest",
        sparql="""
            SELECT ?quest_id WHERE {
                ?n a campy:MainQuest ;
                   campy:name ?tid ;
                   campy:quest_id ?quest_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.name = $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in SideQuest",
        sparql="""
            SELECT ?quest_id WHERE {
                ?n a campy:SideQuest ;
                   campy:name ?tid ;
                   campy:quest_id ?quest_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_plan",
        cypher="MATCH (n:Plan) WHERE n.goal = $tid RETURN n.plan_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Plan",
        sparql="""
            SELECT ?plan_id WHERE {
                ?n a campy:Plan ;
                   campy:goal ?tid ;
                   campy:plan_id ?plan_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_lesson",
        cypher="MATCH (n:Lesson) WHERE n.text_raw = $tid RETURN n.lesson_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Lesson",
        sparql="""
            SELECT ?lesson_id WHERE {
                ?n a campy:Lesson ;
                   campy:text_raw ?tid ;
                   campy:lesson_id ?lesson_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_procedure",
        cypher="MATCH (n:Procedure) WHERE n.name = $tid RETURN n.procedure_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in Procedure",
        sparql="""
            SELECT ?procedure_id WHERE {
                ?n a campy:Procedure ;
                   campy:name ?tid ;
                   campy:procedure_id ?procedure_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_exact_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.text_raw = $tid RETURN n.action_item_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id exact match in ActionItem",
        sparql="""
            SELECT ?action_item_id WHERE {
                ?n a campy:ActionItem ;
                   campy:text_raw ?tid ;
                   campy:action_item_id ?action_item_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.text_raw CONTAINS $tid RETURN n.action_item_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in ActionItem",
        sparql="""
            SELECT ?action_item_id WHERE {
                ?n a campy:ActionItem ;
                   campy:text_raw ?text_raw ;
                   campy:action_item_id ?action_item_id .
                FILTER(CONTAINS(?text_raw, ?tid))
            }
            LIMIT 1
            """,
    ),

    # Target resolution: contains
    NamedQuery(
        name="thalamus.context_resolve_contains_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.name CONTAINS $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in MainQuest",
        sparql="""
            SELECT ?quest_id WHERE {
                ?n a campy:MainQuest ;
                   campy:name ?name ;
                   campy:quest_id ?quest_id .
                FILTER(CONTAINS(?name, ?tid))
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.name CONTAINS $tid RETURN n.quest_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in SideQuest",
        sparql="""
            SELECT ?quest_id WHERE {
                ?n a campy:SideQuest ;
                   campy:name ?name ;
                   campy:quest_id ?quest_id .
                FILTER(CONTAINS(?name, ?tid))
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_plan",
        cypher="MATCH (n:Plan) WHERE n.goal CONTAINS $tid RETURN n.plan_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Plan",
        sparql="""
            SELECT ?plan_id WHERE {
                ?n a campy:Plan ;
                   campy:goal ?goal ;
                   campy:plan_id ?plan_id .
                FILTER(CONTAINS(?goal, ?tid))
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_lesson",
        cypher="MATCH (n:Lesson) WHERE n.text_raw CONTAINS $tid RETURN n.lesson_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Lesson",
        sparql="""
            SELECT ?lesson_id WHERE {
                ?n a campy:Lesson ;
                   campy:text_raw ?text_raw ;
                   campy:lesson_id ?lesson_id .
                FILTER(CONTAINS(?text_raw, ?tid))
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="thalamus.context_resolve_contains_procedure",
        cypher="MATCH (n:Procedure) WHERE n.name CONTAINS $tid RETURN n.procedure_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id contains match in Procedure",
        sparql="""
            SELECT ?procedure_id WHERE {
                ?n a campy:Procedure ;
                   campy:name ?name ;
                   campy:procedure_id ?procedure_id .
                FILTER(CONTAINS(?name, ?tid))
            }
            LIMIT 1
            """,
    ),

    # Target resolution: workspace
    NamedQuery(
        name="thalamus.context_resolve_workspace",
        cypher="MATCH (w:Workspace) WHERE w.branch_name = $tid RETURN w.workspace_id LIMIT 1",
        params=("tid",),
        mutating=False,
        description="Resolve target_id branch_name match in Workspace",
        sparql="""
            SELECT ?workspace_id WHERE {
                ?w a campy:Workspace ;
                   campy:branch_name ?tid ;
                   campy:workspace_id ?workspace_id .
            }
            LIMIT 1
            """,
    ),

    # Lessons for quest
    NamedQuery(
        name="thalamus.context_lessons_for_quest",
        cypher="MATCH (q:MainQuest {quest_id: $qid})-[:PRODUCED_LESSON]->(l:Lesson) "
               "RETURN l.lesson_id, l.text_raw, l.confidence, l.archived LIMIT 20",
        params=("qid",),
        mutating=False,
        description="Fetch lessons produced by MainQuest",
        # PRODUCED_LESSON is "plain" in EDGE_REIFICATION.
        sparql="""
            SELECT ?lesson_id ?text_raw ?confidence ?archived WHERE {
                ?q a campy:MainQuest ;
                   campy:quest_id ?qid .
                ?q campy:PRODUCED_LESSON ?l .
                ?l a campy:Lesson ;
                   campy:lesson_id ?lesson_id ;
                   campy:text_raw ?text_raw ;
                   campy:confidence ?confidence .
                OPTIONAL { ?l campy:archived ?archived }
            }
            LIMIT 20
            """,
    ),

    # DEPRECATED_BY
    NamedQuery(
        name="thalamus.context_deprecated_by_out_concept",
        cypher="MATCH (a:Concept {concept_id: $id})-[:DEPRECATED_BY]->(b:Concept) RETURN b.concept_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Concept is deprecated by",
        sparql="""
            SELECT ?concept_id WHERE {
                ?a a campy:Concept ;
                   campy:concept_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?b a campy:Concept ;
                   campy:concept_id ?concept_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_concept",
        cypher="MATCH (a:Concept)-[:DEPRECATED_BY]->(b:Concept {concept_id: $id}) RETURN a.concept_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Concept deprecates",
        sparql="""
            SELECT ?concept_id WHERE {
                ?b a campy:Concept ;
                   campy:concept_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?a a campy:Concept ;
                   campy:concept_id ?concept_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_decision",
        cypher="MATCH (a:Decision {decision_id: $id})-[:DEPRECATED_BY]->(b:Decision) RETURN b.decision_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Decision is deprecated by",
        sparql="""
            SELECT ?decision_id WHERE {
                ?a a campy:Decision ;
                   campy:decision_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?b a campy:Decision ;
                   campy:decision_id ?decision_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_decision",
        cypher="MATCH (a:Decision)-[:DEPRECATED_BY]->(b:Decision {decision_id: $id}) RETURN a.decision_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Decision deprecates",
        sparql="""
            SELECT ?decision_id WHERE {
                ?b a campy:Decision ;
                   campy:decision_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?a a campy:Decision ;
                   campy:decision_id ?decision_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_constraint",
        cypher="MATCH (a:Constraint {constraint_id: $id})-[:DEPRECATED_BY]->(b:Constraint) RETURN b.constraint_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Constraint is deprecated by",
        sparql="""
            SELECT ?constraint_id WHERE {
                ?a a campy:Constraint ;
                   campy:constraint_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?b a campy:Constraint ;
                   campy:constraint_id ?constraint_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_constraint",
        cypher="MATCH (a:Constraint)-[:DEPRECATED_BY]->(b:Constraint {constraint_id: $id}) RETURN a.constraint_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Constraint deprecates",
        sparql="""
            SELECT ?constraint_id WHERE {
                ?b a campy:Constraint ;
                   campy:constraint_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?a a campy:Constraint ;
                   campy:constraint_id ?constraint_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_out_lesson",
        cypher="MATCH (a:Lesson {lesson_id: $id})-[:DEPRECATED_BY]->(b:Lesson) RETURN b.lesson_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Lesson is deprecated by",
        sparql="""
            SELECT ?lesson_id WHERE {
                ?a a campy:Lesson ;
                   campy:lesson_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?b a campy:Lesson ;
                   campy:lesson_id ?lesson_id .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_deprecated_by_in_lesson",
        cypher="MATCH (a:Lesson)-[:DEPRECATED_BY]->(b:Lesson {lesson_id: $id}) RETURN a.lesson_id LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find what Lesson deprecates",
        sparql="""
            SELECT ?lesson_id WHERE {
                ?b a campy:Lesson ;
                   campy:lesson_id ?id .
                ?a campy:DEPRECATED_BY ?b .
                ?a a campy:Lesson ;
                   campy:lesson_id ?lesson_id .
            }
            LIMIT 10
            """,
    ),

    # SOLVED_BY
    NamedQuery(
        name="thalamus.context_solved_by_decision",
        cypher="MATCH (n:Decision {decision_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving Decision",
        # SOLVED_BY is "star" in EDGE_REIFICATION.
        sparql="""
            SELECT ?worker_id ?confidence ?observed_at WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?id .
                ?n campy:SOLVED_BY ?w .
                ?w a campy:AgentWorker ;
                   campy:worker_id ?worker_id .
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:confidence ?confidence }
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:observed_at ?observed_at }
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_solved_by_actionitem",
        cypher="MATCH (n:ActionItem {action_item_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving ActionItem",
        sparql="""
            SELECT ?worker_id ?confidence ?observed_at WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?id .
                ?n campy:SOLVED_BY ?w .
                ?w a campy:AgentWorker ;
                   campy:worker_id ?worker_id .
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:confidence ?confidence }
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:observed_at ?observed_at }
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.context_solved_by_lesson",
        cypher="MATCH (n:Lesson {lesson_id: $id})-[r:SOLVED_BY]->(w:AgentWorker) "
               "RETURN w.worker_id, r.confidence, r.observed_at LIMIT 10",
        params=("id",),
        mutating=False,
        description="Find worker solving Lesson",
        sparql="""
            SELECT ?worker_id ?confidence ?observed_at WHERE {
                ?n a campy:Lesson ;
                   campy:lesson_id ?id .
                ?n campy:SOLVED_BY ?w .
                ?w a campy:AgentWorker ;
                   campy:worker_id ?worker_id .
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:confidence ?confidence }
                OPTIONAL { << ?n campy:SOLVED_BY ?w >> campy:observed_at ?observed_at }
            }
            LIMIT 10
            """,
    ),

    # bundle_compiler.py
    # Exact facts
    # Concept
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept",
        # No sparql=: brute-force cosine similarity over n.embedding
        # (FLOAT[384], never written to Oxigraph — spec §3.1/§5). Python
        # handler: sqlite-vec ANN over the same threshold, then Oxigraph
        # hydration of text_raw/confidence for the surviving URIs.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_concept_flagged_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Concept with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Decision
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_flagged",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_decision_flagged_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Decision with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Constraint
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_flagged",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_exact_facts_constraint_flagged_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
               "LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Exact facts for Constraint with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Semantic context
    # Concept
    NamedQuery(
        name="thalamus.bundle_semantic_concept",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_concept_flagged_auth",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Concept with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Decision
    NamedQuery(
        name="thalamus.bundle_semantic_decision",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_flagged",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_decision_flagged_auth",
        cypher="MATCH (n:Decision) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Decision with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Constraint
    NamedQuery(
        name="thalamus.bundle_semantic_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint with authority",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_flagged",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_constraint_flagged_auth",
        cypher="MATCH (n:Constraint) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context for Constraint with authority excluding flagged",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Graph structure
    NamedQuery(
        name="thalamus.bundle_graph_anchors",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.concept_id as id, n.text_raw as text, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch anchor concepts for bundle graph structure",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_graph_anchors_flagged",
        cypher="MATCH (n:Concept) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.concept_id as id, n.text_raw as text, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch anchor concepts excluding flagged for bundle graph structure",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_graph_one_hop",
        cypher="MATCH (a:Concept)-[r:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(b:Concept) "
               "WHERE a.concept_id = $aid "
               "RETURN label(r), b.concept_id, b.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 1-hop neighbors for anchor concept",
        # All 9 alternatives are "star" but only the predicate identity is
        # read here, never a quoted-triple property — see module docstring.
        sparql="""
            SELECT ?rel_type ?concept_id ?text_raw WHERE {
                ?a a campy:Concept ;
                   campy:concept_id ?aid .
                VALUES ?p { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                            campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                            campy:ALTERNATIVE_TO }
                { ?a ?p ?b } UNION { ?b ?p ?a }
                BIND(STRAFTER(STR(?p), "https://campy.dev/ns#") AS ?rel_type)
                ?b a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw .
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.bundle_graph_one_hop_flagged",
        cypher="MATCH (a:Concept)-[r:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(b:Concept) "
               "WHERE a.concept_id = $aid "
               "  AND (b.flagged_for_review IS NULL OR b.flagged_for_review = false) "
               "RETURN label(r), b.concept_id, b.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 1-hop neighbors for anchor concept excluding flagged",
        sparql="""
            SELECT ?rel_type ?concept_id ?text_raw WHERE {
                ?a a campy:Concept ;
                   campy:concept_id ?aid .
                VALUES ?p { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                            campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                            campy:ALTERNATIVE_TO }
                { ?a ?p ?b } UNION { ?b ?p ?a }
                BIND(STRAFTER(STR(?p), "https://campy.dev/ns#") AS ?rel_type)
                ?b a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw .
                OPTIONAL { ?b campy:flagged_for_review ?flagged }
                FILTER(!BOUND(?flagged) || ?flagged = false)
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.bundle_graph_two_hop",
        cypher="MATCH (a:Concept)-[r1:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(mid:Concept) "
               "      -[r2:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(c:Concept) "
               "WHERE a.concept_id = $aid AND c.concept_id <> a.concept_id "
               "RETURN label(r1), mid.text_raw, label(r2), c.concept_id, c.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 2-hop neighbors for anchor concept",
        sparql="""
            SELECT ?rel_type1 ?mid_text ?rel_type2 ?concept_id ?text_raw WHERE {
                ?a a campy:Concept ;
                   campy:concept_id ?aid .
                VALUES ?p1 { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                             campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                             campy:ALTERNATIVE_TO }
                { ?a ?p1 ?mid } UNION { ?mid ?p1 ?a }
                BIND(STRAFTER(STR(?p1), "https://campy.dev/ns#") AS ?rel_type1)
                ?mid a campy:Concept ;
                     campy:text_raw ?mid_text .
                VALUES ?p2 { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                             campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                             campy:ALTERNATIVE_TO }
                { ?mid ?p2 ?c } UNION { ?c ?p2 ?mid }
                BIND(STRAFTER(STR(?p2), "https://campy.dev/ns#") AS ?rel_type2)
                ?c a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw .
                FILTER(?concept_id != ?aid)
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="thalamus.bundle_graph_two_hop_flagged",
        cypher="MATCH (a:Concept)-[r1:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(mid:Concept) "
               "      -[r2:REQUIRES|ENABLES|REPLACES|CONTRADICTS|PART_OF|CHOSEN_OVER|IMPLEMENTS|EXTENDS|ALTERNATIVE_TO]-(c:Concept) "
               "WHERE a.concept_id = $aid AND c.concept_id <> a.concept_id "
               "  AND (mid.flagged_for_review IS NULL OR mid.flagged_for_review = false) "
               "  AND (c.flagged_for_review IS NULL OR c.flagged_for_review = false) "
               "RETURN label(r1), mid.text_raw, label(r2), c.concept_id, c.text_raw LIMIT 10",
        params=("aid",),
        mutating=False,
        description="Fetch 2-hop neighbors for anchor concept excluding flagged",
        sparql="""
            SELECT ?rel_type1 ?mid_text ?rel_type2 ?concept_id ?text_raw WHERE {
                ?a a campy:Concept ;
                   campy:concept_id ?aid .
                VALUES ?p1 { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                             campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                             campy:ALTERNATIVE_TO }
                { ?a ?p1 ?mid } UNION { ?mid ?p1 ?a }
                BIND(STRAFTER(STR(?p1), "https://campy.dev/ns#") AS ?rel_type1)
                ?mid a campy:Concept ;
                     campy:text_raw ?mid_text .
                OPTIONAL { ?mid campy:flagged_for_review ?mid_flagged }
                FILTER(!BOUND(?mid_flagged) || ?mid_flagged = false)
                VALUES ?p2 { campy:REQUIRES campy:ENABLES campy:REPLACES campy:CONTRADICTS
                             campy:PART_OF campy:CHOSEN_OVER campy:IMPLEMENTS campy:EXTENDS
                             campy:ALTERNATIVE_TO }
                { ?mid ?p2 ?c } UNION { ?c ?p2 ?mid }
                BIND(STRAFTER(STR(?p2), "https://campy.dev/ns#") AS ?rel_type2)
                ?c a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw .
                FILTER(?concept_id != ?aid)
                OPTIONAL { ?c campy:flagged_for_review ?c_flagged }
                FILTER(!BOUND(?c_flagged) || ?c_flagged = false)
            }
            LIMIT 10
            """,
    ),

    # Tabular
    NamedQuery(
        name="thalamus.bundle_tabular_described_by_dataset",
        cypher="MATCH (n:Concept)-[:DESCRIBED_BY_DATASET]->(d:Dataset) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND d.archived = false "
               "RETURN DISTINCT d.dataset_id as dataset_id, d.name as name, "
               "       d.description as description LIMIT 5",
        params=("query_embedding",),
        mutating=False,
        description="Fetch datasets describing concept",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),

    # Wiki
    NamedQuery(
        name="thalamus.bundle_wiki_lessons",
        cypher="MATCH (n:Lesson) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND n.archived = false AND n.lesson_type = 'synthesis' "
               "RETURN n.lesson_id as id, n.text_raw as text, 'Lesson' as node_type, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Fetch wiki lessons for bundle",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
    NamedQuery(
        name="thalamus.bundle_wiki_procedures",
        cypher="MATCH (n:Procedure) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "      AND n.archived = false "
               "RETURN n.procedure_id as id, n.description as text, 'Procedure' as node_type, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Fetch wiki procedures for bundle",
        # No sparql= — see thalamus.bundle_exact_facts_concept above.
    ),
)


def build_card_hop_query(table: str, pk: str, rel: str, direction: str, props: tuple[str, ...]) -> str:
    """Build single hop query for card context traversal."""
    prop_select = "".join(f", r.{p} AS {p}" for p in props)
    if direction == "out":
        pattern = f"(a:{table} {{{pk}: $id}})-[r:{rel}]->(b)"
    else:
        pattern = f"(a:{table} {{{pk}: $id}})<-[r:{rel}]-(b)"
    return f"MATCH {pattern} RETURN label(b) AS b_label, b{prop_select} LIMIT 20"


# B393: the 3 possible PK columns `b` (an untyped node in Cypher) can carry
# across this loop's 4 tables — MainQuest/SideQuest share `quest_id`,
# ActionItem has `action_item_id`, Workspace has `workspace_id`. Cypher's
# `RETURN ... b` returns the whole node object, which has no direct SPARQL
# column equivalent; narrowed to exactly what the sole call site
# (campy/brain/thalamus/tools/context_tools.py:_card_context_dependency_hop)
# actually reads off `b`: `b_label` plus whichever of these 3 columns
# matches that label (via `b_dict.get(b_pk)`).
_CARD_HOP_PK_COLUMNS = ("quest_id", "action_item_id", "workspace_id")

CARD_HOP_QUERIES: list[NamedQuery] = []
for _table, _pk in (("MainQuest", "quest_id"), ("SideQuest", "quest_id"), ("ActionItem", "action_item_id"), ("Workspace", "workspace_id")):
    for _rel in ("TASK_BLOCKS", "TASK_ENABLES", "ANCHORED_TO"):
        _props = ("declared_by", "confidence", "observed_at", "source", "source_version", "authority") if _rel != "ANCHORED_TO" else ()
        _prop_select = "".join(f", r.{p} AS {p}" for p in _props)
        for _direction, _pattern in (
            ("out", f"(a:{_table} {{{_pk}: $id}})-[r:{_rel}]->(b)"),
            ("in", f"(a:{_table} {{{_pk}: $id}})<-[r:{_rel}]-(b)"),
        ):
            # TASK_BLOCKS/TASK_ENABLES are "star" (confirmed MERGE...SET call
            # site); ANCHORED_TO is "plain" (props=() so no annotation lookup
            # is emitted for it below).
            if _direction == "out":
                _edge_triple = f"?a campy:{_rel} ?b ."
                _quoted = f"<< ?a campy:{_rel} ?b >>"
            else:
                _edge_triple = f"?b campy:{_rel} ?a ."
                _quoted = f"<< ?b campy:{_rel} ?a >>"
            _pk_optionals = "".join(
                f"\n                    OPTIONAL {{ ?b campy:{_pkcol} ?{_pkcol} }}"
                for _pkcol in _CARD_HOP_PK_COLUMNS
            )
            _prop_optionals = "".join(
                f"\n                    OPTIONAL {{ {_quoted} campy:{_p} ?{_p} }}"
                for _p in _props
            )
            _select_cols = " ".join(f"?{_pkcol}" for _pkcol in _CARD_HOP_PK_COLUMNS) + "".join(f" ?{_p}" for _p in _props)
            CARD_HOP_QUERIES.append(
                NamedQuery(
                    name=f"thalamus.card_hop_{_table.lower()}_{_rel.lower()}_{_direction}",
                    cypher=f"MATCH {_pattern} RETURN label(b) AS b_label, b{_prop_select} LIMIT 25",
                    params=("id",),
                    mutating=False,
                    description=f"Card context dependency hop {_table} {_rel} {_direction}",
                    sparql=f"""
                        SELECT ?b_label {_select_cols} WHERE {{
                            ?a a campy:{_table} ;
                               campy:{_pk} ?id .
                            {_edge_triple}
                            ?b a ?b_class .
                            BIND(STRAFTER(STR(?b_class), "https://campy.dev/ns#") AS ?b_label){_pk_optionals}{_prop_optionals}
                        }}
                        LIMIT 25
                        """,
                )
            )

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + CARD_HOP_QUERIES


# B393: every query in BUNDLE_EXTRA_QUERIES computes
# array_cosine_similarity(n.embedding, ...) — brute-force vector search
# over a FLOAT[384] column never written to Oxigraph (spec §3.1/§5). None
# of these get a sparql= field; all are Python-handler exceptions (sqlite-vec
# ANN + Oxigraph hydration), same as thalamus.bundle_exact_facts_concept
# above. Listed individually in the B393 PR report rather than repeating
# the same comment 12 times inline.
BUNDLE_EXTRA_QUERIES: list[NamedQuery] = []

for _label in ("GlobalConstraint", "GlobalPreference"):
    _lbl_lower = _label.lower()
    BUNDLE_EXTRA_QUERIES.extend([
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} base",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_auth",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} with authority",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_flagged",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} excluding flagged",
        ),
        NamedQuery(
            name=f"thalamus.bundle_exact_{_lbl_lower}_flagged_auth",
            cypher=f"MATCH (n:{_label}) "
                   "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                   "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
                   "RETURN n.text_raw as text, label(n) as node_type, n.confidence as confidence, n.authority as authority "
                   "LIMIT $limit",
            params=("query_embedding", "limit"),
            mutating=False,
            description=f"Exact facts {_label} with authority excluding flagged",
        ),
    ])

BUNDLE_EXTRA_QUERIES.extend([
    NamedQuery(
        name="thalamus.bundle_semantic_requirement",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement base",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_auth",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement with authority",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_flagged",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement excluding flagged",
    ),
    NamedQuery(
        name="thalamus.bundle_semantic_requirement_flagged_auth",
        cypher="MATCH (n:Requirement) "
               "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
               "  AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false) "
               "RETURN n.text_raw as text, label(n) as node_type, "
               "       n.pathway_strength as pathway_strength, n.confidence as confidence, "
               "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist, n.authority as authority "
               "ORDER BY dist ASC LIMIT $limit",
        params=("query_embedding", "limit"),
        mutating=False,
        description="Semantic context Requirement with authority excluding flagged",
    ),
])

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + BUNDLE_EXTRA_QUERIES


# B374: bundle_semantic_*/bundle_graph_anchors* variants for archived and
# superseded_by filtering. archived/superseded_by are base columns on every
# real schema.py-created table, but a handful of reduced test fixtures build
# these tables directly without them (see _table_has_column's docstring), so
# — same as flagged/authority above — a missing column needs its own query
# text rather than a runtime-toggled WHERE clause (Kuzu's binder validates
# every referenced column regardless of runtime branching). The base
# (archived=False, superseded=False) slice is exactly the 16 bundle_semantic_*
# and 2 bundle_graph_anchors* queries registered above; this generates the
# remaining combinations rather than hand-duplicating them.
#
# B393: every query below also computes array_cosine_similarity — same
# Python-handler exception as BUNDLE_EXTRA_QUERIES/bundle_exact_facts_*
# above (spec §3.1/§5), so none of these get sparql= either.
ARCHIVED_SUPERSEDED_QUERIES: list[NamedQuery] = []

for _label in ("Concept", "Decision", "Constraint", "Requirement"):
    _lbl_lower = _label.lower()
    for _flagged in (False, True):
        for _archived in (False, True):
            for _superseded in (False, True):
                for _auth in (False, True):
                    if not _archived and not _superseded:
                        continue  # already registered above
                    _suffix_parts = []
                    _filters = []
                    if _flagged:
                        _suffix_parts.append("flagged")
                        _filters.append(
                            "AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                        )
                    if _archived:
                        _suffix_parts.append("archived")
                        _filters.append("AND (n.archived IS NULL OR n.archived = false)")
                    if _superseded:
                        _suffix_parts.append("superseded")
                        _filters.append(
                            "AND (n.superseded_by IS NULL OR n.superseded_by = '')"
                        )
                    if _auth:
                        _suffix_parts.append("auth")
                    _suffix = "".join(f"_{p}" for p in _suffix_parts)
                    _filter_text = " ".join(_filters)
                    _auth_select = ", n.authority as authority" if _auth else ""
                    ARCHIVED_SUPERSEDED_QUERIES.append(
                        NamedQuery(
                            name=f"thalamus.bundle_semantic_{_lbl_lower}{_suffix}",
                            cypher=f"MATCH (n:{_label}) "
                                   f"WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                                   f"{_filter_text} "
                                   f"RETURN n.text_raw as text, label(n) as node_type, "
                                   f"       n.pathway_strength as pathway_strength, n.confidence as confidence, "
                                   f"       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist{_auth_select} "
                                   f"ORDER BY dist ASC LIMIT $limit",
                            params=("query_embedding", "limit"),
                            mutating=False,
                            description=f"Semantic context for {_label}"
                                        + (f" ({', '.join(_suffix_parts)})" if _suffix_parts else ""),
                        )
                    )

for _flagged in (False, True):
    for _archived in (False, True):
        for _superseded in (False, True):
            if not _archived and not _superseded:
                continue  # already registered above
            _suffix_parts = []
            _filters = []
            if _flagged:
                _suffix_parts.append("flagged")
                _filters.append(
                    "AND (n.flagged_for_review IS NULL OR n.flagged_for_review = false)"
                )
            if _archived:
                _suffix_parts.append("archived")
                _filters.append("AND (n.archived IS NULL OR n.archived = false)")
            if _superseded:
                _suffix_parts.append("superseded")
                _filters.append("AND (n.superseded_by IS NULL OR n.superseded_by = '')")
            _suffix = "".join(f"_{p}" for p in _suffix_parts)
            _filter_text = " ".join(_filters)
            ARCHIVED_SUPERSEDED_QUERIES.append(
                NamedQuery(
                    name=f"thalamus.bundle_graph_anchors{_suffix}",
                    cypher="MATCH (n:Concept) "
                           "WHERE (1 - array_cosine_similarity(n.embedding, $query_embedding)) < 0.30 "
                           f"{_filter_text} "
                           "RETURN n.concept_id as id, n.text_raw as text, "
                           "       (1 - array_cosine_similarity(n.embedding, $query_embedding)) as dist "
                           "ORDER BY dist ASC LIMIT 5",
                    params=("query_embedding",),
                    mutating=False,
                    description=f"Fetch anchor concepts for bundle graph structure ({', '.join(_suffix_parts)})",
                )
            )

THALAMUS_QUERIES = list(THALAMUS_QUERIES) + ARCHIVED_SUPERSEDED_QUERIES
