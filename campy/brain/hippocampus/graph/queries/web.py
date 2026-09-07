"""web.py — named queries for the Memory Control Panel web server & routes."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

WEB_QUERIES: tuple[NamedQuery, ...] = (
    # Node detail & 1-hop neighbors (for each table)
    # Concept
    NamedQuery(
        name="web.get_node_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Concept node by concept_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Concept ;
                   campy:concept_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_concept",
        cypher="MATCH (n:Concept)-[r]-(m) WHERE n.concept_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Concept",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Concept ;
                   campy:concept_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Decision
    NamedQuery(
        name="web.get_node_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Decision node by decision_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_decision",
        cypher="MATCH (n:Decision)-[r]-(m) WHERE n.decision_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Decision",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Constraint
    NamedQuery(
        name="web.get_node_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Constraint node by constraint_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Constraint ;
                   campy:constraint_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_constraint",
        cypher="MATCH (n:Constraint)-[r]-(m) WHERE n.constraint_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Constraint",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Constraint ;
                   campy:constraint_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Requirement
    NamedQuery(
        name="web.get_node_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Requirement node by requirement_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Requirement ;
                   campy:requirement_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_requirement",
        cypher="MATCH (n:Requirement)-[r]-(m) WHERE n.requirement_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Requirement",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Requirement ;
                   campy:requirement_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # ActionItem
    NamedQuery(
        name="web.get_node_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch ActionItem node by action_item_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_actionitem",
        cypher="MATCH (n:ActionItem)-[r]-(m) WHERE n.action_item_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for ActionItem",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Message
    NamedQuery(
        name="web.get_node_message",
        cypher="MATCH (n:Message) WHERE n.message_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Message node by message_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Message ;
                   campy:message_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_message",
        cypher="MATCH (n:Message)-[r]-(m) WHERE n.message_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Message",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Message ;
                   campy:message_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Document
    NamedQuery(
        name="web.get_node_document",
        cypher="MATCH (n:Document) WHERE n.document_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Document node by document_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Document ;
                   campy:document_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_document",
        cypher="MATCH (n:Document)-[r]-(m) WHERE n.document_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Document",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Document ;
                   campy:document_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # MainQuest
    NamedQuery(
        name="web.get_node_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.quest_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch MainQuest node by quest_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:MainQuest ;
                   campy:quest_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_mainquest",
        cypher="MATCH (n:MainQuest)-[r]-(m) WHERE n.quest_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for MainQuest",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:MainQuest ;
                   campy:quest_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # SideQuest
    NamedQuery(
        name="web.get_node_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.quest_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch SideQuest node by quest_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:SideQuest ;
                   campy:quest_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_sidequest",
        cypher="MATCH (n:SideQuest)-[r]-(m) WHERE n.quest_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for SideQuest",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:SideQuest ;
                   campy:quest_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Lesson
    NamedQuery(
        name="web.get_node_lesson",
        cypher="MATCH (n:Lesson) WHERE n.lesson_id = $id RETURN n",
        params=("id",),
        mutating=False,
        description="Fetch Lesson node by lesson_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?n WHERE {
                ?n a campy:Lesson ;
                   campy:lesson_id ?id .
            }
        """,
    ),
    NamedQuery(
        name="web.get_neighbors_lesson",
        cypher="MATCH (n:Lesson)-[r]-(m) WHERE n.lesson_id = $id RETURN m, label(m), label(r) LIMIT 20",
        params=("id",),
        mutating=False,
        description="Fetch 1-hop neighbors for Lesson",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?m ?m_label ?r_label WHERE {
                ?n a campy:Lesson ;
                   campy:lesson_id ?id .
                {
                    ?n ?r ?m .
                    FILTER(isIRI(?m) && ?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                } UNION {
                    ?m ?r ?n .
                    FILTER(?r != rdf:type && STRSTARTS(STR(?r), "https://campy.dev/ns#"))
                }
                ?m a ?m_class .
                FILTER(STRSTARTS(STR(?m_class), "https://campy.dev/ns#"))
                BIND(STRAFTER(STR(?m_class), "https://campy.dev/ns#") AS ?m_label)
                BIND(STRAFTER(STR(?r), "https://campy.dev/ns#") AS ?r_label)
            } LIMIT 20
        """,
    ),
    # Stats counts
    NamedQuery(
        name="web.count_active_concept",
        cypher="MATCH (n:Concept) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Concept nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Concept .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_decision",
        cypher="MATCH (n:Decision) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Decision nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Decision .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_constraint",
        cypher="MATCH (n:Constraint) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Constraint nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Constraint .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_requirement",
        cypher="MATCH (n:Requirement) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Requirement nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Requirement .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active ActionItem nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:ActionItem .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_message",
        cypher="MATCH (n:Message) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active Message nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Message .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_total_document",
        cypher="MATCH (n:Document) RETURN count(n)",
        params=(),
        mutating=False,
        description="Count total Document nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Document .
            }
        """,
    ),
    NamedQuery(
        name="web.count_total_mergeevent",
        cypher="MATCH (n:MergeEvent) RETURN count(n)",
        params=(),
        mutating=False,
        description="Count total MergeEvent nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:MergeEvent .
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_mainquest",
        cypher="MATCH (n:MainQuest) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active MainQuest nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:MainQuest .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_active_sidequest",
        cypher="MATCH (n:SideQuest) WHERE n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count active SideQuest nodes",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:SideQuest .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    # Graph visualization
    NamedQuery(
        name="web.graph_concepts",
        cypher="MATCH (c:Concept) WHERE c.archived = false "
               "RETURN c.concept_id, c.text_raw, c.gist_class, "
               "       c.confidence, c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 30",
        params=(),
        mutating=False,
        description="Fetch top active concepts for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?concept_id ?text_raw ?gist_class ?confidence ?pathway_strength ?confidence_low WHERE {
                ?c a campy:Concept .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:concept_id ?concept_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:gist_class ?gist_class }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 30
        """,
    ),
    NamedQuery(
        name="web.graph_decisions",
        cypher="MATCH (d:Decision) WHERE d.archived = false "
               "RETURN d.decision_id, d.text_raw, d.confidence, "
               "       d.pathway_strength, d.confidence_low "
               "ORDER BY d.pathway_strength DESC LIMIT 20",
        params=(),
        mutating=False,
        description="Fetch top active decisions for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?decision_id ?text_raw ?confidence ?pathway_strength ?confidence_low WHERE {
                ?d a campy:Decision .
                OPTIONAL { ?d campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?d campy:decision_id ?decision_id }
                OPTIONAL { ?d campy:text_raw ?text_raw }
                OPTIONAL { ?d campy:confidence ?confidence }
                OPTIONAL { ?d campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?d campy:confidence_low ?confidence_low }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 20
        """,
    ),
    NamedQuery(
        name="web.graph_constraints",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 20",
        params=(),
        mutating=False,
        description="Fetch top active constraints for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?constraint_id ?text_raw ?confidence ?pathway_strength ?confidence_low WHERE {
                ?c a campy:Constraint .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:constraint_id ?constraint_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 20
        """,
    ),
    NamedQuery(
        name="web.graph_main_quests",
        cypher="MATCH (q:MainQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch active main quests for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?quest_id ?name ?status WHERE {
                ?q a campy:MainQuest .
                OPTIONAL { ?q campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?q campy:quest_id ?quest_id }
                OPTIONAL { ?q campy:name ?name }
                OPTIONAL { ?q campy:status ?status }
            } LIMIT 10
        """,
    ),
    NamedQuery(
        name="web.graph_side_quests",
        cypher="MATCH (q:SideQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch active side quests for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?quest_id ?name ?status WHERE {
                ?q a campy:SideQuest .
                OPTIONAL { ?q campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?q campy:quest_id ?quest_id }
                OPTIONAL { ?q campy:name ?name }
                OPTIONAL { ?q campy:status ?status }
            } LIMIT 10
        """,
    ),
    NamedQuery(
        name="web.graph_co_occurs_with",
        cypher="MATCH (a:Concept)-[r:CO_OCCURS_WITH]->(b:Concept) "
               "WHERE a.archived = false AND b.archived = false "
               "RETURN a.concept_id, b.concept_id, r.strength, r.count "
               "ORDER BY r.strength DESC LIMIT 60",
        params=(),
        mutating=False,
        description="Fetch CO_OCCURS_WITH edges for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?a_concept_id ?b_concept_id ?strength ?count WHERE {
                ?a a campy:Concept ; campy:concept_id ?a_concept_id .
                ?b a campy:Concept ; campy:concept_id ?b_concept_id .
                OPTIONAL { ?a campy:archived ?a_archived }
                FILTER(!BOUND(?a_archived) || ?a_archived = false)
                OPTIONAL { ?b campy:archived ?b_archived }
                FILTER(!BOUND(?b_archived) || ?b_archived = false)
                ?a campy:CO_OCCURS_WITH ?b .
                << ?a campy:CO_OCCURS_WITH ?b >> campy:strength ?strength ;
                                                 campy:count ?count .
            }
            ORDER BY DESC(?strength) LIMIT 60
        """,
    ),
    NamedQuery(
        name="web.graph_deprecated_by",
        cypher="MATCH (old:Concept)-[:DEPRECATED_BY]->(new:Concept) "
               "RETURN old.concept_id, new.concept_id LIMIT 30",
        params=(),
        mutating=False,
        description="Fetch DEPRECATED_BY edges for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?old_concept_id ?new_concept_id WHERE {
                ?old a campy:Concept ; campy:concept_id ?old_concept_id ; campy:DEPRECATED_BY ?new .
                ?new a campy:Concept ; campy:concept_id ?new_concept_id .
            } LIMIT 30
        """,
    ),
    NamedQuery(
        name="web.graph_belongs_to",
        cypher="MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
               "RETURN sq.quest_id, mq.quest_id",
        params=(),
        mutating=False,
        description="Fetch BELONGS_TO edges for graph visualization",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?sq_quest_id ?mq_quest_id WHERE {
                ?sq a campy:SideQuest ; campy:quest_id ?sq_quest_id ; campy:BELONGS_TO ?mq .
                ?mq a campy:MainQuest ; campy:quest_id ?mq_quest_id .
            }
        """,
    ),
    # Open loops
    NamedQuery(
        name="web.open_loops_concept",
        cypher="MATCH (n:Concept) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.concept_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Concepts",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text_raw ?confidence ?created_at WHERE {
                ?n a campy:Concept ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?n campy:concept_id ?id }
                OPTIONAL { ?n campy:text_raw ?text_raw }
                OPTIONAL { ?n campy:confidence ?confidence }
                OPTIONAL { ?n campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    NamedQuery(
        name="web.open_loops_decision",
        cypher="MATCH (n:Decision) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.decision_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Decisions",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text_raw ?confidence ?created_at WHERE {
                ?n a campy:Decision ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?n campy:decision_id ?id }
                OPTIONAL { ?n campy:text_raw ?text_raw }
                OPTIONAL { ?n campy:confidence ?confidence }
                OPTIONAL { ?n campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    NamedQuery(
        name="web.open_loops_constraint",
        cypher="MATCH (n:Constraint) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.constraint_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Constraints",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text_raw ?confidence ?created_at WHERE {
                ?n a campy:Constraint ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?n campy:constraint_id ?id }
                OPTIONAL { ?n campy:text_raw ?text_raw }
                OPTIONAL { ?n campy:confidence ?confidence }
                OPTIONAL { ?n campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    NamedQuery(
        name="web.open_loops_requirement",
        cypher="MATCH (n:Requirement) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.requirement_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop Requirements",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text_raw ?confidence ?created_at WHERE {
                ?n a campy:Requirement ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?n campy:requirement_id ?id }
                OPTIONAL { ?n campy:text_raw ?text_raw }
                OPTIONAL { ?n campy:confidence ?confidence }
                OPTIONAL { ?n campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    NamedQuery(
        name="web.open_loops_actionitem",
        cypher="MATCH (n:ActionItem) "
               "WHERE n.confidence_low = true AND n.archived = false "
               "RETURN n.action_item_id, n.text_raw, n.confidence, n.created_at "
               "ORDER BY n.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="Fetch open loop ActionItems",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?id ?text_raw ?confidence ?created_at WHERE {
                ?n a campy:ActionItem ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?n campy:action_item_id ?id }
                OPTIONAL { ?n campy:text_raw ?text_raw }
                OPTIONAL { ?n campy:confidence ?confidence }
                OPTIONAL { ?n campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    # Soft-lock confirm / reject
    # Concept
    NamedQuery(
        name="web.find_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid RETURN n.concept_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Concept by concept_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?nid WHERE {
                ?n a campy:Concept ;
                   campy:concept_id ?nid .
            }
        """,
    ),
    NamedQuery(
        name="web.confirm_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Concept",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?n campy:confidence_low ?old_low .
                ?n campy:confidence ?old_conf .
            }
            INSERT {
                ?n campy:confidence_low false .
                ?n campy:confidence "0.95"^^xsd:double .
            }
            WHERE {
                ?n a campy:Concept ;
                   campy:concept_id ?nid .
                OPTIONAL { ?n campy:confidence_low ?old_low }
                OPTIONAL { ?n campy:confidence ?old_conf }
            }
        """,
    ),
    NamedQuery(
        name="web.reject_soft_lock_concept",
        cypher="MATCH (n:Concept) WHERE n.concept_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Concept",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?n campy:archived ?old_archived .
            }
            INSERT {
                ?n campy:archived true .
            }
            WHERE {
                ?n a campy:Concept ;
                   campy:concept_id ?nid .
                OPTIONAL { ?n campy:archived ?old_archived }
            }
        """,
    ),
    # Decision
    NamedQuery(
        name="web.find_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid RETURN n.decision_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Decision by decision_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?nid WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?nid .
            }
        """,
    ),
    NamedQuery(
        name="web.confirm_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Decision",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?n campy:confidence_low ?old_low .
                ?n campy:confidence ?old_conf .
            }
            INSERT {
                ?n campy:confidence_low false .
                ?n campy:confidence "0.95"^^xsd:double .
            }
            WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?nid .
                OPTIONAL { ?n campy:confidence_low ?old_low }
                OPTIONAL { ?n campy:confidence ?old_conf }
            }
        """,
    ),
    NamedQuery(
        name="web.reject_soft_lock_decision",
        cypher="MATCH (n:Decision) WHERE n.decision_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Decision",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?n campy:archived ?old_archived .
            }
            INSERT {
                ?n campy:archived true .
            }
            WHERE {
                ?n a campy:Decision ;
                   campy:decision_id ?nid .
                OPTIONAL { ?n campy:archived ?old_archived }
            }
        """,
    ),
    # Constraint
    NamedQuery(
        name="web.find_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid RETURN n.constraint_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Constraint by constraint_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?nid WHERE {
                ?n a campy:Constraint ;
                   campy:constraint_id ?nid .
            }
        """,
    ),
    NamedQuery(
        name="web.confirm_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Constraint",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?n campy:confidence_low ?old_low .
                ?n campy:confidence ?old_conf .
            }
            INSERT {
                ?n campy:confidence_low false .
                ?n campy:confidence "0.95"^^xsd:double .
            }
            WHERE {
                ?n a campy:Constraint ;
                   campy:constraint_id ?nid .
                OPTIONAL { ?n campy:confidence_low ?old_low }
                OPTIONAL { ?n campy:confidence ?old_conf }
            }
        """,
    ),
    NamedQuery(
        name="web.reject_soft_lock_constraint",
        cypher="MATCH (n:Constraint) WHERE n.constraint_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Constraint",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?n campy:archived ?old_archived .
            }
            INSERT {
                ?n campy:archived true .
            }
            WHERE {
                ?n a campy:Constraint ;
                   campy:constraint_id ?nid .
                OPTIONAL { ?n campy:archived ?old_archived }
            }
        """,
    ),
    # Requirement
    NamedQuery(
        name="web.find_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid RETURN n.requirement_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock Requirement by requirement_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?nid WHERE {
                ?n a campy:Requirement ;
                   campy:requirement_id ?nid .
            }
        """,
    ),
    NamedQuery(
        name="web.confirm_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock Requirement",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?n campy:confidence_low ?old_low .
                ?n campy:confidence ?old_conf .
            }
            INSERT {
                ?n campy:confidence_low false .
                ?n campy:confidence "0.95"^^xsd:double .
            }
            WHERE {
                ?n a campy:Requirement ;
                   campy:requirement_id ?nid .
                OPTIONAL { ?n campy:confidence_low ?old_low }
                OPTIONAL { ?n campy:confidence ?old_conf }
            }
        """,
    ),
    NamedQuery(
        name="web.reject_soft_lock_requirement",
        cypher="MATCH (n:Requirement) WHERE n.requirement_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock Requirement",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?n campy:archived ?old_archived .
            }
            INSERT {
                ?n campy:archived true .
            }
            WHERE {
                ?n a campy:Requirement ;
                   campy:requirement_id ?nid .
                OPTIONAL { ?n campy:archived ?old_archived }
            }
        """,
    ),
    # ActionItem
    NamedQuery(
        name="web.find_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid RETURN n.action_item_id",
        params=("nid",),
        mutating=False,
        description="Find soft-lock ActionItem by action_item_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?nid WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?nid .
            }
        """,
    ),
    NamedQuery(
        name="web.confirm_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid "
               "SET n.confidence_low = false, n.confidence = 0.95",
        params=("nid",),
        mutating=True,
        description="Confirm soft-lock ActionItem",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            DELETE {
                ?n campy:confidence_low ?old_low .
                ?n campy:confidence ?old_conf .
            }
            INSERT {
                ?n campy:confidence_low false .
                ?n campy:confidence "0.95"^^xsd:double .
            }
            WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?nid .
                OPTIONAL { ?n campy:confidence_low ?old_low }
                OPTIONAL { ?n campy:confidence ?old_conf }
            }
        """,
    ),
    NamedQuery(
        name="web.reject_soft_lock_actionitem",
        cypher="MATCH (n:ActionItem) WHERE n.action_item_id = $nid "
               "SET n.archived = true",
        params=("nid",),
        mutating=True,
        description="Reject soft-lock ActionItem",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?n campy:archived ?old_archived .
            }
            INSERT {
                ?n campy:archived true .
            }
            WHERE {
                ?n a campy:ActionItem ;
                   campy:action_item_id ?nid .
                OPTIONAL { ?n campy:archived ?old_archived }
            }
        """,
    ),
    # Merge events
    NamedQuery(
        name="web.list_merge_events",
        cypher="MATCH (me:MergeEvent) "
               "RETURN me.merge_event_id, me.pre_pathway_strength, "
               "       me.delta_pathway_strength, me.metadata_patch, me.created_at "
               "ORDER BY me.created_at DESC LIMIT 50",
        params=(),
        mutating=False,
        description="List recent MergeEvents with rollback metadata",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?merge_event_id ?pre_pathway_strength ?delta_pathway_strength ?metadata_patch ?created_at WHERE {
                ?me a campy:MergeEvent .
                OPTIONAL { ?me campy:merge_event_id ?merge_event_id }
                OPTIONAL { ?me campy:pre_pathway_strength ?pre_pathway_strength }
                OPTIONAL { ?me campy:delta_pathway_strength ?delta_pathway_strength }
                OPTIONAL { ?me campy:metadata_patch ?metadata_patch }
                OPTIONAL { ?me campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at) LIMIT 50
        """,
    ),
    NamedQuery(
        name="web.get_merge_event",
        cypher="MATCH (me:MergeEvent) WHERE me.merge_event_id = $meid "
               "RETURN me.metadata_patch, me.pre_pathway_strength",
        params=("meid",),
        mutating=False,
        description="Fetch MergeEvent by merge_event_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?metadata_patch ?pre_pathway_strength WHERE {
                ?me a campy:MergeEvent ;
                    campy:merge_event_id ?meid .
                OPTIONAL { ?me campy:metadata_patch ?metadata_patch }
                OPTIONAL { ?me campy:pre_pathway_strength ?pre_pathway_strength }
            }
        """,
    ),
    NamedQuery(
        name="web.rollback_restore_old_concept",
        cypher="MATCH (c:Concept) WHERE c.concept_id = $id "
               "SET c.archived = false, c.pathway_strength = $strength",
        params=("id", "strength"),
        mutating=True,
        description="Restore old concept during contradiction rollback",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?c campy:archived ?old_archived .
                ?c campy:pathway_strength ?old_strength .
            }
            INSERT {
                ?c campy:archived false .
                ?c campy:pathway_strength ?strength .
            }
            WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?id .
                OPTIONAL { ?c campy:archived ?old_archived }
                OPTIONAL { ?c campy:pathway_strength ?old_strength }
            }
        """,
    ),
    NamedQuery(
        name="web.rollback_archive_new_concept",
        cypher="MATCH (c:Concept) WHERE c.concept_id = $id "
               "SET c.archived = true",
        params=("id",),
        mutating=True,
        description="Archive new concept during contradiction rollback",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?c campy:archived ?old_archived .
            }
            INSERT {
                ?c campy:archived true .
            }
            WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?id .
                OPTIONAL { ?c campy:archived ?old_archived }
            }
        """,
    ),
    NamedQuery(
        name="web.rollback_delete_deprecated_by",
        cypher="MATCH (old:Concept)-[d:DEPRECATED_BY]->(new:Concept) "
               "WHERE old.concept_id = $old_id AND new.concept_id = $new_id "
               "DELETE d",
        params=("old_id", "new_id"),
        mutating=True,
        description="Delete DEPRECATED_BY edge during contradiction rollback",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?old campy:DEPRECATED_BY ?new .
            }
            WHERE {
                ?old a campy:Concept ; campy:concept_id ?old_id .
                ?new a campy:Concept ; campy:concept_id ?new_id .
                ?old campy:DEPRECATED_BY ?new .
            }
        """,
    ),
    NamedQuery(
        name="web.rollback_mark_merge_event",
        cypher="MATCH (me:MergeEvent) WHERE me.merge_event_id = $meid "
               "SET me.metadata_patch = $meta",
        params=("meid", "meta"),
        mutating=True,
        description="Mark MergeEvent metadata as rolled back",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            DELETE {
                ?me campy:metadata_patch ?old_meta .
            }
            INSERT {
                ?me campy:metadata_patch ?meta .
            }
            WHERE {
                ?me a campy:MergeEvent ;
                    campy:merge_event_id ?meid .
                OPTIONAL { ?me campy:metadata_patch ?old_meta }
            }
        """,
    ),
    # Ledger export
    NamedQuery(
        name="web.ledger_constraint",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.confidence_low, c.pathway_strength, c.created_at "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch active constraints for ledger",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?constraint_id ?text_raw ?confidence ?confidence_low ?pathway_strength ?created_at WHERE {
                ?c a campy:Constraint .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:constraint_id ?constraint_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:created_at ?created_at }
            }
            ORDER BY DESC(?pathway_strength)
        """,
    ),
    NamedQuery(
        name="web.ledger_global_constraint",
        cypher="MATCH (c:GlobalConstraint) WHERE c.archived = false "
               "RETURN c.global_constraint_id, c.text_raw, c.confidence, "
               "       c.confidence_low, c.pathway_strength, c.created_at "
               "ORDER BY c.pathway_strength DESC",
        params=(),
        mutating=False,
        description="Fetch active global constraints for ledger",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?global_constraint_id ?text_raw ?confidence ?confidence_low ?pathway_strength ?created_at WHERE {
                ?c a campy:GlobalConstraint .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:global_constraint_id ?global_constraint_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:created_at ?created_at }
            }
            ORDER BY DESC(?pathway_strength)
        """,
    ),
    # Quests
    NamedQuery(
        name="web.quests_main",
        cypher="MATCH (q:MainQuest) WHERE q.archived = false "
               "RETURN q.quest_id, q.name, q.status, q.purpose, q.created_at "
               "ORDER BY q.created_at DESC",
        params=(),
        mutating=False,
        description="Fetch active main quests",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?quest_id ?name ?status ?purpose ?created_at WHERE {
                ?q a campy:MainQuest .
                OPTIONAL { ?q campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?q campy:quest_id ?quest_id }
                OPTIONAL { ?q campy:name ?name }
                OPTIONAL { ?q campy:status ?status }
                OPTIONAL { ?q campy:purpose ?purpose }
                OPTIONAL { ?q campy:created_at ?created_at }
            }
            ORDER BY DESC(?created_at)
        """,
    ),
    NamedQuery(
        name="web.quests_side_belongs_to",
        cypher="MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest) "
               "WHERE sq.archived = false "
               "RETURN sq.quest_id, sq.name, sq.status, sq.purpose, "
               "       sq.created_at, mq.quest_id",
        params=(),
        mutating=False,
        description="Fetch active side quests with parent quest_id",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?quest_id ?name ?status ?purpose ?created_at ?mq_quest_id WHERE {
                ?sq a campy:SideQuest ;
                    campy:BELONGS_TO ?mq .
                ?mq a campy:MainQuest ;
                    campy:quest_id ?mq_quest_id .
                OPTIONAL { ?sq campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?sq campy:quest_id ?quest_id }
                OPTIONAL { ?sq campy:name ?name }
                OPTIONAL { ?sq campy:status ?status }
                OPTIONAL { ?sq campy:purpose ?purpose }
                OPTIONAL { ?sq campy:created_at ?created_at }
            }
        """,
    ),
    # Thinking tab
    NamedQuery(
        name="web.thinking_decisions",
        cypher="MATCH (d:Decision) WHERE d.archived = false "
               "RETURN d.decision_id, d.text_raw, d.confidence, "
               "       d.pathway_strength, d.confidence_low, d.created_at "
               "ORDER BY d.pathway_strength DESC LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch top decisions for thinking tab",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?decision_id ?text_raw ?confidence ?pathway_strength ?confidence_low ?created_at WHERE {
                ?d a campy:Decision .
                OPTIONAL { ?d campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?d campy:decision_id ?decision_id }
                OPTIONAL { ?d campy:text_raw ?text_raw }
                OPTIONAL { ?d campy:confidence ?confidence }
                OPTIONAL { ?d campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?d campy:confidence_low ?confidence_low }
                OPTIONAL { ?d campy:created_at ?created_at }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 10
        """,
    ),
    NamedQuery(
        name="web.thinking_concepts",
        cypher="MATCH (c:Concept) WHERE c.archived = false "
               "RETURN c.concept_id, c.text_raw, c.gist_class, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 25",
        params=(),
        mutating=False,
        description="Fetch top concepts for thinking tab",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?concept_id ?text_raw ?gist_class ?pathway_strength ?confidence_low WHERE {
                ?c a campy:Concept .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:concept_id ?concept_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:gist_class ?gist_class }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 25
        """,
    ),
    NamedQuery(
        name="web.thinking_constraints",
        cypher="MATCH (c:Constraint) WHERE c.archived = false "
               "RETURN c.constraint_id, c.text_raw, c.confidence, "
               "       c.pathway_strength, c.confidence_low "
               "ORDER BY c.pathway_strength DESC LIMIT 10",
        params=(),
        mutating=False,
        description="Fetch top constraints for thinking tab",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?constraint_id ?text_raw ?confidence ?pathway_strength ?confidence_low WHERE {
                ?c a campy:Constraint .
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?c campy:constraint_id ?constraint_id }
                OPTIONAL { ?c campy:text_raw ?text_raw }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
            }
            ORDER BY DESC(?pathway_strength) LIMIT 10
        """,
    ),
    NamedQuery(
        name="web.count_open_loops_concept",
        cypher="MATCH (n:Concept) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Concept table",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Concept ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_open_loops_decision",
        cypher="MATCH (n:Decision) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Decision table",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Decision ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    NamedQuery(
        name="web.count_open_loops_constraint",
        cypher="MATCH (n:Constraint) WHERE n.confidence_low = true "
               "AND n.archived = false RETURN count(n)",
        params=(),
        mutating=False,
        description="Count open loops in Constraint table",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT (COUNT(?n) AS ?count) WHERE {
                ?n a campy:Constraint ;
                   campy:confidence_low true .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
        """,
    ),
    # Metrics
    NamedQuery(
        name="web.recent_sessions_token_metrics",
        cypher="MATCH (s:Session) "
               "RETURN s.session_id, s.started_at, s.last_active_at, "
               "       s.token_estimate, s.token_limit, "
               "       s.loaded_node_count, s.injection_count, "
               "       s.dedup_tokens_saved "
               "ORDER BY s.last_active_at DESC "
               "LIMIT $limit",
        params=("limit",),
        mutating=False,
        description="Fetch recent sessions token metrics",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            SELECT ?session_id ?started_at ?last_active_at ?token_estimate ?token_limit ?loaded_node_count ?injection_count ?dedup_tokens_saved WHERE {
                ?s a campy:Session .
                OPTIONAL { ?s campy:session_id ?session_id }
                OPTIONAL { ?s campy:started_at ?started_at }
                OPTIONAL { ?s campy:last_active_at ?last_active_at }
                OPTIONAL { ?s campy:token_estimate ?token_estimate }
                OPTIONAL { ?s campy:token_limit ?token_limit }
                OPTIONAL { ?s campy:loaded_node_count ?loaded_node_count }
                OPTIONAL { ?s campy:injection_count ?injection_count }
                OPTIONAL { ?s campy:dedup_tokens_saved ?dedup_tokens_saved }
            }
            ORDER BY DESC(?last_active_at)
        """,
    ),
)
