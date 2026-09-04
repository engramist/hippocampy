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
        ),
    ])
