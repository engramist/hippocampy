"""
campy/brain/hippocampus/graph/queries/orchestrator.py — Consolidation loop and orchestrator queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

ORCHESTRATOR_QUERIES = [
    NamedQuery(
        name="orchestrator.create_disambiguation_event",
        cypher="""
        CREATE (e:DisambiguationEvent {
            event_id: $eid,
            concept_id_a: $a,
            concept_id_b: $b,
            similarity: $sim,
            status: 'pending',
            resolved_at: NULL,
            resolved_by: NULL,
            created_at: timestamp($created_at)
        })
        """,
        params=("eid", "a", "b", "sim", "created_at"),
        mutating=True,
        description="Create a pending DisambiguationEvent linking two concepts",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?e a campy:DisambiguationEvent ;
                 campy:event_id ?eid ;
                 campy:concept_id_a ?a ;
                 campy:concept_id_b ?b ;
                 campy:similarity ?sim ;
                 campy:status "pending" ;
                 campy:created_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/DisambiguationEvent/", ENCODE_FOR_URI(STR(?eid)))) AS ?e)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.find_concept_by_exact_text",
        cypher="""
        MATCH (c:Concept)
        WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false
        RETURN c.concept_id, c.pathway_strength
        LIMIT 1
        """,
        params=("t",),
        mutating=False,
        description="Exact match dedup lookup for Concept",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?concept_id ?pathway_strength
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?c campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              FILTER(LCASE(STR(?text_raw)) = LCASE(STR(?t)))
            }
            LIMIT 1
        """,
    ),
    NamedQuery(
        name="orchestrator.touch_dedup_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $id})
        SET c.last_accessed_at = timestamp($now),
            c.pathway_strength = CASE WHEN $ps > c.pathway_strength THEN $ps ELSE c.pathway_strength END,
            c.confidence_low = CASE WHEN $conf >= 0.80 THEN false ELSE c.confidence_low END,
            c.salience_score = CASE WHEN $salience > coalesce(c.salience_score, 1.0) THEN $salience ELSE coalesce(c.salience_score, 1.0) END
        """,
        params=("id", "now", "ps", "conf", "salience"),
        mutating=True,
        description="Update pathway strength and last access on dedup hit",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            DELETE {
              ?c campy:last_accessed_at ?old_accessed .
              ?c campy:pathway_strength ?old_strength .
              ?c campy:confidence_low ?old_low .
              ?c campy:salience_score ?old_salience .
            }
            INSERT {
              ?c campy:last_accessed_at ?now .
              ?c campy:pathway_strength ?target_strength .
              ?c campy:confidence_low ?target_low .
              ?c campy:salience_score ?target_salience .
            }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?id .
              OPTIONAL { ?c campy:last_accessed_at ?old_accessed }
              OPTIONAL { ?c campy:pathway_strength ?old_strength }
              OPTIONAL { ?c campy:confidence_low ?old_low }
              OPTIONAL { ?c campy:salience_score ?old_salience }
              BIND(IF(BOUND(?old_strength) && ?ps > ?old_strength, ?ps, COALESCE(?old_strength, ?ps)) AS ?target_strength)
              BIND(IF(?conf >= "0.80"^^xsd:double, false, COALESCE(?old_low, false)) AS ?target_low)
              BIND(IF(?salience > COALESCE(?old_salience, "1.0"^^xsd:double), ?salience, COALESCE(?old_salience, "1.0"^^xsd:double)) AS ?target_salience)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.create_concept",
        cypher="""
        CREATE (c:Concept {
            concept_id:       $concept_id,
            text_raw:         $text_raw,
            embedding:        $embedding,
            embedding_model:  $embedding_model,
            embedding_dim:    $embedding_dim,
            gist_class:       $gist_class,
            schema_org_type:  $schema_org_type,
            confidence:       $confidence,
            confidence_low:   $confidence_low,
            pathway_strength: $pathway_strength,
            salience_score:   $salience_score,
            archived:         false,
            anomaly_type:     $anomaly_type,
            flagged_for_review: $flagged_for_review,
            created_at:       timestamp($created_at),
            last_accessed_at: timestamp($created_at)
        })
        """,
        params=(
            "concept_id", "text_raw", "embedding", "embedding_model", "embedding_dim",
            "gist_class", "schema_org_type", "confidence", "confidence_low",
            "pathway_strength", "salience_score", "anomaly_type", "flagged_for_review",
            "created_at",
        ),
        mutating=True,
        description="Create a new Concept node",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?c a campy:Concept ;
                 campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:gist_class ?gist_class ;
                 campy:schema_org_type ?schema_org_type ;
                 campy:confidence ?confidence ;
                 campy:confidence_low ?confidence_low ;
                 campy:pathway_strength ?pathway_strength ;
                 campy:salience_score ?salience_score ;
                 campy:archived false ;
                 campy:anomaly_type ?anomaly_type ;
                 campy:flagged_for_review ?flagged_for_review ;
                 campy:created_at ?created_at ;
                 campy:last_accessed_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Concept/", ENCODE_FOR_URI(STR(?concept_id)))) AS ?c)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.create_gist_example",
        cypher="""
        CREATE (e:GistExample {
            example_id: $example_id,
            text:       $text,
            embedding:  $embedding,
            gist_class: $gist_class,
            source:     'system2',
            created_at: timestamp($created_at)
        })
        """,
        params=("example_id", "text", "embedding", "gist_class", "created_at"),
        mutating=True,
        description="Persist System 2 labeled example to GistExample",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?e a campy:GistExample ;
                 campy:example_id ?example_id ;
                 campy:text ?text ;
                 campy:embedding ?embedding ;
                 campy:gist_class ?gist_class ;
                 campy:source "system2" ;
                 campy:created_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/GistExample/", ENCODE_FOR_URI(STR(?example_id)))) AS ?e)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.find_endpoint_concept",
        cypher="""
        MATCH (c:Concept)
        WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false
        RETURN c.concept_id
        ORDER BY c.pathway_strength DESC
        LIMIT 1
        """,
        params=("t",),
        mutating=False,
        description="Find concept endpoint by text for relationship linking",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?concept_id
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ;
                 campy:pathway_strength ?pathway_strength .
              OPTIONAL { ?c campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              FILTER(LCASE(STR(?text_raw)) = LCASE(STR(?t)))
            }
            ORDER BY DESC(?pathway_strength)
            LIMIT 1
        """,
    ),
    NamedQuery(
        name="orchestrator.create_minimal_concept",
        cypher="""
        CREATE (c:Concept {
            concept_id:       $concept_id,
            text_raw:         $text_raw,
            embedding:        $embedding,
            embedding_model:  $embedding_model,
            embedding_dim:    $embedding_dim,
            gist_class:       '',
            schema_org_type:  '',
            confidence:       0.60,
            confidence_low:   true,
            pathway_strength: 0.60,
            archived:         false,
            created_at:       timestamp($created_at),
            last_accessed_at: timestamp($created_at)
        })
        """,
        params=("concept_id", "text_raw", "embedding", "embedding_model", "embedding_dim", "created_at"),
        mutating=True,
        description="Create minimal low-confidence Concept node for relationship endpoint",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?c a campy:Concept ;
                 campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:gist_class "" ;
                 campy:schema_org_type "" ;
                 campy:confidence "0.60"^^xsd:double ;
                 campy:confidence_low true ;
                 campy:pathway_strength "0.60"^^xsd:double ;
                 campy:archived false ;
                 campy:created_at ?created_at ;
                 campy:last_accessed_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Concept/", ENCODE_FOR_URI(STR(?concept_id)))) AS ?c)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.create_lesson",
        cypher="""
        CREATE (l:Lesson {
            lesson_id:        $lesson_id,
            text_raw:         $text_raw,
            embedding:        $embedding,
            embedding_model:  $embedding_model,
            embedding_dim:    $embedding_dim,
            domain:           $domain,
            lesson_type:      $lesson_type,
            confidence:       0.70,
            confidence_low:   true,
            pathway_strength: 0.70,
            archived:         false,
            created_at:       timestamp($created_at)
        })
        """,
        params=("lesson_id", "text_raw", "embedding", "embedding_model", "embedding_dim", "domain", "lesson_type", "created_at"),
        mutating=True,
        description="Create a Lesson node in Step 7.5",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?l a campy:Lesson ;
                 campy:lesson_id ?lesson_id ;
                 campy:text_raw ?text_raw ;
                 campy:embedding ?embedding ;
                 campy:embedding_model ?embedding_model ;
                 campy:embedding_dim ?embedding_dim ;
                 campy:domain ?domain ;
                 campy:lesson_type ?lesson_type ;
                 campy:confidence "0.70"^^xsd:double ;
                 campy:confidence_low true ;
                 campy:pathway_strength "0.70"^^xsd:double ;
                 campy:archived false ;
                 campy:created_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Lesson/", ENCODE_FOR_URI(STR(?lesson_id)))) AS ?l)
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.link_message_contains_lesson",
        cypher="""
        MATCH (m:Message {message_id: $mid}), (l:Lesson {lesson_id: $lid})
        MERGE (m)-[:CONTAINS_LESSON]->(l)
        """,
        params=("mid", "lid"),
        mutating=True,
        description="Link Message to Lesson with CONTAINS_LESSON",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?m campy:CONTAINS_LESSON ?l .
            }
            WHERE {
              ?m a campy:Message ; campy:message_id ?mid .
              ?l a campy:Lesson ; campy:lesson_id ?lid .
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.link_session_learned_lesson",
        cypher="""
        MATCH (s:Session {session_id: $sid}), (l:Lesson {lesson_id: $lid})
        MERGE (s)-[:LEARNED]->(l)
        """,
        params=("sid", "lid"),
        mutating=True,
        description="Link Session to Lesson with LEARNED",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?s campy:LEARNED ?l .
            }
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              ?l a campy:Lesson ; campy:lesson_id ?lid .
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.bind_lesson_trigger",
        cypher="""
        MATCH (l:Lesson {lesson_id: $lid})
        SET l.trigger_pattern = $pattern,
            l.trigger_hook_type = $hook_type,
            l.trigger_tool = $tool,
            l.trigger_project_scope = $scope
        """,
        params=("lid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Set trigger binding properties on Lesson",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?l campy:trigger_pattern ?old_pat .
              ?l campy:trigger_hook_type ?old_hook .
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
              ?l a campy:Lesson ; campy:lesson_id ?lid .
              OPTIONAL { ?l campy:trigger_pattern ?old_pat }
              OPTIONAL { ?l campy:trigger_hook_type ?old_hook }
              OPTIONAL { ?l campy:trigger_tool ?old_tool }
              OPTIONAL { ?l campy:trigger_project_scope ?old_scope }
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.bind_procedure_trigger",
        cypher="""
        MATCH (p:Procedure {procedure_id: $pid})
        SET p.trigger_pattern = $pattern,
            p.trigger_hook_type = $hook_type,
            p.trigger_tool = $tool,
            p.trigger_project_scope = $scope
        """,
        params=("pid", "pattern", "hook_type", "tool", "scope"),
        mutating=True,
        description="Set trigger binding properties on Procedure",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?p campy:trigger_pattern ?old_pat .
              ?p campy:trigger_hook_type ?old_hook .
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
              ?p a campy:Procedure ; campy:procedure_id ?pid .
              OPTIONAL { ?p campy:trigger_pattern ?old_pat }
              OPTIONAL { ?p campy:trigger_hook_type ?old_hook }
              OPTIONAL { ?p campy:trigger_tool ?old_tool }
              OPTIONAL { ?p campy:trigger_project_scope ?old_scope }
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.get_schema_org_routing",
        cypher="""
        MATCH (g:GistClass)-[:ROUTES_TO]->(s:SchemaOrgType)
        RETURN g.name, s.name, s.properties
        """,
        params=(),
        mutating=False,
        description="Load routing table from Kuzu into module cache",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?name ?schema_name ?properties
            WHERE {
              ?g a campy:GistClass ;
                 campy:name ?name ;
                 campy:ROUTES_TO ?s .
              ?s a campy:SchemaOrgType ;
                 campy:name ?schema_name ;
                 campy:properties ?properties .
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.get_gist_centroids",
        cypher="""
        MATCH (g:GistClass)
        RETURN g.name, g.centroid
        """,
        params=(),
        mutating=False,
        description="Load GistClass centroids from Kuzu",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?name ?centroid
            WHERE {
              ?g a campy:GistClass ;
                 campy:name ?name ;
                 campy:centroid ?centroid .
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.get_global_constraints",
        cypher="""
        MATCH (gc:GlobalConstraint)
        WHERE gc.pathway_strength > $threshold AND NOT gc.archived
        RETURN gc.global_constraint_id, gc.text_raw, gc.embedding
        """,
        params=("threshold",),
        mutating=False,
        description="Get high confidence global constraints",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?global_constraint_id ?text_raw ?embedding
            WHERE {
              ?gc a campy:GlobalConstraint ;
                  campy:global_constraint_id ?global_constraint_id ;
                  campy:pathway_strength ?pathway_strength ;
                  campy:text_raw ?text_raw .
              FILTER(?pathway_strength > ?threshold)
              OPTIONAL { ?gc campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?gc campy:embedding ?embedding }
            }
        """,
    ),
    NamedQuery(
        name="orchestrator.get_global_preferences",
        cypher="""
        MATCH (gp:GlobalPreference)
        WHERE gp.pathway_strength > $threshold AND NOT gp.archived
        RETURN gp.global_preference_id, gp.text_raw, gp.embedding
        """,
        params=("threshold",),
        mutating=False,
        description="Get high confidence global preferences",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?global_preference_id ?text_raw ?embedding
            WHERE {
              ?gp a campy:GlobalPreference ;
                  campy:global_preference_id ?global_preference_id ;
                  campy:pathway_strength ?pathway_strength ;
                  campy:text_raw ?text_raw .
              FILTER(?pathway_strength > ?threshold)
              OPTIONAL { ?gp campy:archived ?archived }
              FILTER(!BOUND(?archived) || ?archived = false)
              OPTIONAL { ?gp campy:embedding ?embedding }
            }
        """,
    ),
]

_ARTIFACT_SPECS = [
    ("Decision", "decision_id", "decision"),
    ("Constraint", "constraint_id", "constraint"),
    ("Requirement", "requirement_id", "requirement"),
    ("ActionItem", "action_item_id", "actionitem"),
]

for label, pk, key in _ARTIFACT_SPECS:
    ORCHESTRATOR_QUERIES.extend([
        NamedQuery(
            name=f"orchestrator.create_artifact_{key}",
            cypher=f"""
            CREATE (a:{label} {{
                {pk}:              $artifact_id,
                text_raw:          $text_raw,
                embedding:         $embedding,
                embedding_model:   $embedding_model,
                embedding_dim:     $embedding_dim,
                confidence:        $confidence,
                confidence_low:    false,
                pathway_strength:  $pathway_strength,
                archived:          false,
                created_at:        timestamp($created_at)
            }})
            """,
            params=("artifact_id", "text_raw", "embedding", "embedding_model", "embedding_dim", "confidence", "pathway_strength", "created_at"),
            mutating=True,
            description=f"Create {label} artifact node",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?a a campy:{label} ;
                     campy:{pk} ?artifact_id ;
                     campy:text_raw ?text_raw ;
                     campy:embedding ?embedding ;
                     campy:embedding_model ?embedding_model ;
                     campy:embedding_dim ?embedding_dim ;
                     campy:confidence ?confidence ;
                     campy:confidence_low false ;
                     campy:pathway_strength ?pathway_strength ;
                     campy:archived false ;
                     campy:created_at ?created_at .
                }}
                WHERE {{
                  BIND(IRI(CONCAT("https://campy.dev/data/{label}/", ENCODE_FOR_URI(STR(?artifact_id)))) AS ?a)
                }}
            """,
        ),
        NamedQuery(
            name=f"orchestrator.link_concept_reified_{key}",
            cypher=f"""
            MATCH (c:Concept {{concept_id: $concept_id}}),
                  (a:{label} {{{pk}: $artifact_id}})
            CREATE (c)-[:REIFIED_AS]->(a)
            """,
            params=("concept_id", "artifact_id"),
            mutating=True,
            description=f"Link Concept to {label} with REIFIED_AS",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?c campy:REIFIED_AS ?a .
                }}
                WHERE {{
                  ?c a campy:Concept ; campy:concept_id ?concept_id .
                  ?a a campy:{label} ; campy:{pk} ?artifact_id .
                }}
            """,
        ),
        NamedQuery(
            name=f"orchestrator.link_message_established_{key}",
            cypher=f"""
            MATCH (m:Message {{message_id: $mid}}),
                  (a:{label} {{{pk}: $artifact_id}})
            MERGE (m)-[:ESTABLISHED]->(a)
            """,
            params=("mid", "artifact_id"),
            mutating=True,
            description=f"Link Message to {label} with ESTABLISHED",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?m campy:ESTABLISHED ?a .
                }}
                WHERE {{
                  ?m a campy:Message ; campy:message_id ?mid .
                  ?a a campy:{label} ; campy:{pk} ?artifact_id .
                }}
            """,
        ),
        NamedQuery(
            name=f"orchestrator.link_artifact_session_{key}",
            cypher=f"""
            MATCH (a:{label} {{{pk}: $artifact_id}}),
                  (s:Session {{session_id: $sid}})
            MERGE (a)-[:ESTABLISHED_IN]->(s)
            """,
            params=("artifact_id", "sid"),
            mutating=True,
            description=f"Link {label} to Session with ESTABLISHED_IN",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?a campy:ESTABLISHED_IN ?s .
                }}
                WHERE {{
                  ?a a campy:{label} ; campy:{pk} ?artifact_id .
                  ?s a campy:Session ; campy:session_id ?sid .
                }}
            """,
        ),
    ])

_SEMANTIC_RELS = [
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
]

for rel_type in _SEMANTIC_RELS:
    ORCHESTRATOR_QUERIES.append(
        NamedQuery(
            name=f"orchestrator.merge_semantic_rel_{rel_type.lower()}",
            cypher=f"""
            MATCH (h:Concept {{concept_id: $hid}}),
                  (t:Concept {{concept_id: $tid}})
            MERGE (h)-[r:{rel_type}]->(t)
            ON CREATE SET r.confidence   = $confidence,
                          r.inferred_by  = $inferred_by,
                          r.inferred_at  = timestamp($now)
            """,
            params=("hid", "tid", "confidence", "inferred_by", "now"),
            mutating=True,
            description=f"Merge {rel_type} relation between Concepts",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?h campy:{rel_type} ?t .
                  << ?h campy:{rel_type} ?t >> campy:confidence ?target_conf ;
                                              campy:inferred_by ?target_by ;
                                              campy:inferred_at ?target_at .
                }}
                WHERE {{
                  ?h a campy:Concept ; campy:concept_id ?hid .
                  ?t a campy:Concept ; campy:concept_id ?tid .
                  OPTIONAL {{
                    << ?h campy:{rel_type} ?t >> campy:confidence ?old_conf ;
                                                campy:inferred_by ?old_by ;
                                                campy:inferred_at ?old_at .
                  }}
                  BIND(COALESCE(?old_conf, ?confidence) AS ?target_conf)
                  BIND(COALESCE(?old_by, ?inferred_by) AS ?target_by)
                  BIND(COALESCE(?old_at, ?now) AS ?target_at)
                }}
            """,
        )
    )

_ANOMALY_NODE_SPECS = [
    ("Concept", "concept_id", "concept"),
    ("Decision", "decision_id", "decision"),
    ("Constraint", "constraint_id", "constraint"),
    ("Requirement", "requirement_id", "requirement"),
    ("ActionItem", "action_item_id", "actionitem"),
    ("Message", "message_id", "message"),
    ("DocumentExtract", "extract_id", "documentextract"),
]

for label, pk, key in _ANOMALY_NODE_SPECS:
    ORCHESTRATOR_QUERIES.extend([
        NamedQuery(
            name=f"orchestrator.set_anomaly_flags_{key}",
            cypher=f"""
            MATCH (n:{label} {{{pk}: $node_id}})
            SET n.anomaly_type = $anomaly_type,
                n.flagged_for_review = true
            """,
            params=("node_id", "anomaly_type"),
            mutating=True,
            description=f"Set anomaly flags on {label}",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                DELETE {{
                  ?n campy:anomaly_type ?old_type .
                  ?n campy:flagged_for_review ?old_flag .
                }}
                INSERT {{
                  ?n campy:anomaly_type ?anomaly_type .
                  ?n campy:flagged_for_review true .
                }}
                WHERE {{
                  ?n a campy:{label} ; campy:{pk} ?node_id .
                  OPTIONAL {{ ?n campy:anomaly_type ?old_type }}
                  OPTIONAL {{ ?n campy:flagged_for_review ?old_flag }}
                }}
            """,
        ),
        NamedQuery(
            name=f"orchestrator.link_anomaly_detected_{key}",
            cypher=f"""
            MATCH (n:{label} {{{pk}: $node_id}})
            MATCH (gc:GlobalConstraint {{global_constraint_id: $constraint_id}})
            MERGE (n)-[r:ANOMALY_DETECTED]->(gc)
            SET r.type = $type,
                r.confidence = $confidence,
                r.detected_at = $detected_at
            """,
            params=("node_id", "constraint_id", "type", "confidence", "detected_at"),
            mutating=True,
            description=f"Create ANOMALY_DETECTED edge from {label} to GlobalConstraint",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?n campy:ANOMALY_DETECTED ?gc .
                  << ?n campy:ANOMALY_DETECTED ?gc >> campy:type ?type ;
                                                      campy:confidence ?confidence ;
                                                      campy:detected_at ?detected_at .
                }}
                WHERE {{
                  ?n a campy:{label} ; campy:{pk} ?node_id .
                  ?gc a campy:GlobalConstraint ; campy:global_constraint_id ?constraint_id .
                }}
            """,
        ),
    ])
