"""campy/brain/hippocampus/graph/queries/quests.py — Named queries for quest and session management."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

QUEST_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="quests.get_main_quest_by_id",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.quest_id",
        params=("qid",),
        mutating=False,
        description="Check if MainQuest exists by quest_id.",
        sparql="""
            SELECT ?qid WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid .
            }
            """,
    ),
    NamedQuery(
        name="quests.touch_main_quest",
        cypher="MATCH (q:MainQuest {quest_id: $quest_id}) SET q.last_active_at = timestamp($now)",
        params=("quest_id", "now"),
        mutating=True,
        description="Update last_active_at timestamp on MainQuest.",
        sparql="""
            DELETE { ?q campy:last_active_at ?old_last_active_at . }
            INSERT { ?q campy:last_active_at ?now . }
            WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?quest_id .
                OPTIONAL { ?q campy:last_active_at ?old_last_active_at }
            }
            """,
    ),
    NamedQuery(
        name="quests.create_main_quest",
        cypher="""
            CREATE (q:MainQuest {
                quest_id:           $quest_id,
                name:               $name,
                status:             $status,
                completed_at:       null,
                purpose:            $purpose,
                text_raw:           $name,
                embedding:          $embedding,
                embedding_model:    $embedding_model,
                embedding_dim:      $embedding_dim,
                confidence:         1.0,
                confidence_low:     false,
                pathway_strength:   1.0,
                archived:           false,
                created_at:         timestamp($created_at),
                last_active_at:     timestamp($last_active_at),
                git_repo_root:      $git_repo_root,
                purpose_embedding:  $purpose_embedding,
                routing_method:     $routing_method
            })
            """,
        params=(
            "quest_id", "name", "status", "purpose", "embedding", "embedding_model",
            "embedding_dim", "created_at", "last_active_at", "git_repo_root",
            "purpose_embedding", "routing_method",
        ),
        mutating=True,
        description="Create a new MainQuest node.",
        sparql="""
            INSERT {
                ?q a campy:MainQuest ;
                   campy:quest_id ?quest_id ;
                   campy:name ?name ;
                   campy:status ?status ;
                   campy:purpose ?purpose ;
                   campy:text_raw ?name ;
                   campy:embedding_model ?embedding_model ;
                   campy:embedding_dim ?embedding_dim ;
                   campy:confidence "1.0"^^xsd:double ;
                   campy:confidence_low false ;
                   campy:pathway_strength "1.0"^^xsd:double ;
                   campy:archived false ;
                   campy:created_at ?created_at ;
                   campy:last_active_at ?last_active_at ;
                   campy:git_repo_root ?git_repo_root ;
                   campy:routing_method ?routing_method .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "MainQuest/", ENCODE_FOR_URI(?quest_id))) AS ?q)
            }
            """,
    ),
    NamedQuery(
        name="quests.merge_session_git_locked",
        cypher="""
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at          = timestamp($now),
                          s.last_active_at      = timestamp($now),
                          s.onboarded           = false,
                          s.purpose             = '',
                          s.routing_state       = 'locked',
                          s.routing_confidence  = 0.95,
                          s.routing_method      = 'git'
            ON MATCH SET  s.last_active_at      = timestamp($now),
                          s.routing_state       = 'locked',
                          s.routing_confidence  = 0.95,
                          s.routing_method      = 'git'
            """,
        params=("sid", "now"),
        mutating=True,
        description="Merge Session node and set git-locked routing metadata.",
        sparql="""
            DELETE {
                ?s campy:last_active_at ?old_last_active_at .
                ?s campy:routing_state ?old_routing_state .
                ?s campy:routing_confidence ?old_routing_confidence .
                ?s campy:routing_method ?old_routing_method .
            }
            INSERT {
                ?s a campy:Session ;
                   campy:session_id ?sid ;
                   campy:started_at ?started_at_val ;
                   campy:last_active_at ?now ;
                   campy:onboarded ?onboarded_val ;
                   campy:purpose ?purpose_val ;
                   campy:routing_state "locked" ;
                   campy:routing_confidence "0.95"^^xsd:double ;
                   campy:routing_method "git" .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "Session/", ENCODE_FOR_URI(?sid))) AS ?s)
                OPTIONAL { ?s campy:started_at ?existing_started_at }
                OPTIONAL { ?s campy:last_active_at ?old_last_active_at }
                OPTIONAL { ?s campy:routing_state ?old_routing_state }
                OPTIONAL { ?s campy:routing_confidence ?old_routing_confidence }
                OPTIONAL { ?s campy:routing_method ?old_routing_method }
                OPTIONAL { ?s campy:onboarded ?existing_onboarded }
                OPTIONAL { ?s campy:purpose ?existing_purpose }
                BIND(COALESCE(?existing_started_at, ?now) AS ?started_at_val)
                BIND(COALESCE(?existing_onboarded, false) AS ?onboarded_val)
                BIND(COALESCE(?existing_purpose, "") AS ?purpose_val)
            }
            """,
    ),
    NamedQuery(
        name="quests.merge_session",
        cypher="""
            MERGE (s:Session {session_id: $sid})
            ON CREATE SET s.started_at          = timestamp($now),
                          s.last_active_at      = timestamp($now),
                          s.onboarded           = false,
                          s.purpose             = '',
                          s.routing_state       = $routing_state,
                          s.routing_confidence  = $routing_confidence,
                          s.routing_method      = $routing_method
            ON MATCH SET  s.last_active_at      = timestamp($now),
                          s.routing_state       = $routing_state,
                          s.routing_confidence  = $routing_confidence,
                          s.routing_method      = $routing_method
            """,
        params=("sid", "now", "routing_state", "routing_confidence", "routing_method"),
        mutating=True,
        description="Merge Session node and update routing metadata.",
        sparql="""
            DELETE {
                ?s campy:last_active_at ?old_last_active_at .
                ?s campy:routing_state ?old_routing_state .
                ?s campy:routing_confidence ?old_routing_confidence .
                ?s campy:routing_method ?old_routing_method .
            }
            INSERT {
                ?s a campy:Session ;
                   campy:session_id ?sid ;
                   campy:started_at ?started_at_val ;
                   campy:last_active_at ?now ;
                   campy:onboarded ?onboarded_val ;
                   campy:purpose ?purpose_val ;
                   campy:routing_state ?routing_state ;
                   campy:routing_confidence ?routing_confidence ;
                   campy:routing_method ?routing_method .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "Session/", ENCODE_FOR_URI(?sid))) AS ?s)
                OPTIONAL { ?s campy:started_at ?existing_started_at }
                OPTIONAL { ?s campy:last_active_at ?old_last_active_at }
                OPTIONAL { ?s campy:routing_state ?old_routing_state }
                OPTIONAL { ?s campy:routing_confidence ?old_routing_confidence }
                OPTIONAL { ?s campy:routing_method ?old_routing_method }
                OPTIONAL { ?s campy:onboarded ?existing_onboarded }
                OPTIONAL { ?s campy:purpose ?existing_purpose }
                BIND(COALESCE(?existing_started_at, ?now) AS ?started_at_val)
                BIND(COALESCE(?existing_onboarded, false) AS ?onboarded_val)
                BIND(COALESCE(?existing_purpose, "") AS ?purpose_val)
            }
            """,
    ),
    NamedQuery(
        name="quests.link_session_quest",
        cypher="""
            MATCH (s:Session {session_id: $sid}),
                  (q:MainQuest {quest_id: $qid})
            MERGE (s)-[:WORKING_ON]->(q)
            """,
        params=("sid", "qid"),
        mutating=True,
        description="Link Session to MainQuest via WORKING_ON.",
        sparql="""
            INSERT { ?s campy:WORKING_ON ?q . }
            WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
            }
            """,
    ),
    NamedQuery(
        name="quests.create_side_quest",
        cypher="""
            CREATE (sq:SideQuest {
                quest_id:         $quest_id,
                name:             $name,
                status:           'active',
                completed_at:     null,
                purpose:          $purpose,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                confidence:       1.0,
                confidence_low:   false,
                pathway_strength: 1.0,
                archived:         false,
                created_at:       timestamp($created_at)
            })
            """,
        params=(
            "quest_id", "name", "purpose", "text_raw", "embedding",
            "embedding_model", "embedding_dim", "created_at",
        ),
        mutating=True,
        description="Create a new SideQuest node.",
        sparql="""
            INSERT {
                ?sq a campy:SideQuest ;
                    campy:quest_id ?quest_id ;
                    campy:name ?name ;
                    campy:status "active" ;
                    campy:purpose ?purpose ;
                    campy:text_raw ?text_raw ;
                    campy:embedding_model ?embedding_model ;
                    campy:embedding_dim ?embedding_dim ;
                    campy:confidence "1.0"^^xsd:double ;
                    campy:confidence_low false ;
                    campy:pathway_strength "1.0"^^xsd:double ;
                    campy:archived false ;
                    campy:created_at ?created_at .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "SideQuest/", ENCODE_FOR_URI(?quest_id))) AS ?sq)
            }
            """,
    ),
    NamedQuery(
        name="quests.link_side_quest",
        cypher="""
            MATCH (sq:SideQuest {quest_id: $sqid}),
                  (mq:MainQuest {quest_id: $mqid})
            CREATE (sq)-[:BELONGS_TO]->(mq)
            """,
        params=("sqid", "mqid"),
        mutating=True,
        description="Link SideQuest to MainQuest via BELONGS_TO.",
        sparql="""
            INSERT { ?sq campy:BELONGS_TO ?mq . }
            WHERE {
                ?sq a campy:SideQuest ; campy:quest_id ?sqid .
                ?mq a campy:MainQuest ; campy:quest_id ?mqid .
            }
            """,
    ),
    NamedQuery(
        name="quests.get_quest_name_and_status",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.status",
        params=("qid",),
        mutating=False,
        description="Fetch MainQuest name and status.",
        sparql="""
            SELECT ?name ?status WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid ; campy:name ?name ; campy:status ?status .
            }
            """,
    ),
    NamedQuery(
        name="quests.get_open_loop_concepts",
        cypher="""
            MATCH (c:Concept {confidence_low: true, archived: false})
            WHERE c.created_at IS NOT NULL
            RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch confidence_low Concepts as open loops.",
        sparql="""
            SELECT ?concept_id ?text_raw ?gist_class ?confidence WHERE {
                ?c a campy:Concept ;
                   campy:confidence_low true ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw ;
                   campy:created_at ?created_at .
                OPTIONAL { ?c campy:gist_class ?gist_class }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="quests.get_active_side_quests",
        cypher="""
            MATCH (sq:SideQuest)-[:BELONGS_TO]->(mq:MainQuest {quest_id: $qid})
            WHERE sq.status = 'active'
            RETURN sq.quest_id, sq.name, sq.purpose
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch active SideQuests belonging to a MainQuest.",
        sparql="""
            SELECT ?quest_id ?name ?purpose WHERE {
                ?sq a campy:SideQuest ;
                    campy:BELONGS_TO ?mq ;
                    campy:status "active" ;
                    campy:quest_id ?quest_id ;
                    campy:name ?name .
                OPTIONAL { ?sq campy:purpose ?purpose }
                ?mq a campy:MainQuest ; campy:quest_id ?qid .
            }
            """,
    ),
    NamedQuery(
        name="quests.get_quest_decisions",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Decision {archived: false})
            RETURN a.decision_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Decisions for a MainQuest.",
        sparql="""
            SELECT ?decision_id ?text_raw ?confidence_low ?pathway_strength WHERE {
                ?s a campy:Session ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                ?m a campy:Message ; campy:SENT_IN ?s .
                ?m campy:ESTABLISHED ?a .
                ?a a campy:Decision ;
                   campy:decision_id ?decision_id ;
                   campy:text_raw ?text_raw ;
                   campy:pathway_strength ?pathway_strength .
                OPTIONAL { ?a campy:confidence_low ?confidence_low }
                OPTIONAL { ?a campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?pathway_strength)
            """,
    ),
    NamedQuery(
        name="quests.get_quest_constraints",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Constraint {archived: false})
            RETURN a.constraint_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Constraints for a MainQuest.",
        sparql="""
            SELECT ?constraint_id ?text_raw ?confidence_low ?pathway_strength WHERE {
                ?s a campy:Session ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                ?m a campy:Message ; campy:SENT_IN ?s .
                ?m campy:ESTABLISHED ?a .
                ?a a campy:Constraint ;
                   campy:constraint_id ?constraint_id ;
                   campy:text_raw ?text_raw ;
                   campy:pathway_strength ?pathway_strength .
                OPTIONAL { ?a campy:confidence_low ?confidence_low }
                OPTIONAL { ?a campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?pathway_strength)
            """,
    ),
    NamedQuery(
        name="quests.get_quest_concepts",
        cypher="""
            MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            MATCH (m:Message)-[:SENT_IN]->(s)
            MATCH (m)-[:ESTABLISHED]->(a:Concept {archived: false})
            RETURN a.concept_id, a.text_raw, a.confidence_low, a.pathway_strength
            ORDER BY a.pathway_strength DESC
            LIMIT $limit
            """,
        params=("qid", "limit"),
        mutating=False,
        description="Fetch recent Concepts for a MainQuest.",
        sparql="""
            SELECT ?concept_id ?text_raw ?confidence_low ?pathway_strength WHERE {
                ?s a campy:Session ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                ?m a campy:Message ; campy:SENT_IN ?s .
                ?m campy:ESTABLISHED ?a .
                ?a a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw ;
                   campy:pathway_strength ?pathway_strength .
                OPTIONAL { ?a campy:confidence_low ?confidence_low }
                OPTIONAL { ?a campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?pathway_strength)
            """,
    ),
    NamedQuery(
        name="quests.get_session_by_message",
        cypher="""
            MATCH (m:Message {message_id: $mid})-[:SENT_IN]->(s:Session)
            RETURN s.session_id, s.purpose
            """,
        params=("mid",),
        mutating=False,
        description="Fetch Session id and purpose for a Message.",
        sparql="""
            SELECT ?session_id ?purpose WHERE {
                ?m a campy:Message ; campy:message_id ?mid ; campy:SENT_IN ?s .
                ?s a campy:Session ; campy:session_id ?session_id .
                OPTIONAL { ?s campy:purpose ?purpose }
            }
            """,
    ),
    NamedQuery(
        name="quests.get_quest_by_session",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id, q.name
            """,
        params=("sid",),
        mutating=False,
        description="Fetch MainQuest working on by a Session.",
        sparql="""
            SELECT ?quest_id ?name WHERE {
                ?s a campy:Session ; campy:session_id ?sid ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?quest_id ; campy:name ?name .
            }
            """,
    ),
    NamedQuery(
        name="quests.get_session_messages",
        cypher="""
            MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
            RETURN m.text_raw, m.role
            ORDER BY m.created_at ASC
            LIMIT $limit
            """,
        params=("sid", "limit"),
        mutating=False,
        description="Fetch recent messages for a session.",
        sparql="""
            SELECT ?text_raw ?role WHERE {
                ?m a campy:Message ;
                   campy:SENT_IN ?s ;
                   campy:text_raw ?text_raw ;
                   campy:role ?role ;
                   campy:created_at ?created_at .
                ?s a campy:Session ; campy:session_id ?sid .
            }
            ORDER BY ASC(?created_at)
            """,
    ),
    NamedQuery(
        name="quests.set_session_purpose",
        cypher="MATCH (s:Session {session_id: $sid}) SET s.purpose = $purpose",
        params=("sid", "purpose"),
        mutating=True,
        description="Set Session purpose.",
        sparql="""
            DELETE { ?s campy:purpose ?old_purpose . }
            INSERT { ?s campy:purpose ?purpose . }
            WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                OPTIONAL { ?s campy:purpose ?old_purpose }
            }
            """,
    ),
    NamedQuery(
        name="quests.set_main_quest_purpose",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.purpose = $default OR q.purpose IS NULL
            SET q.purpose = $purpose
            """,
        params=("qid", "default", "purpose"),
        mutating=True,
        description="Set MainQuest purpose if not already set.",
        sparql="""
            DELETE { ?q campy:purpose ?old_purpose . }
            INSERT { ?q campy:purpose ?purpose . }
            WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                OPTIONAL { ?q campy:purpose ?old_purpose }
                FILTER(!BOUND(?old_purpose) || ?old_purpose = ?default)
            }
            """,
    ),
    NamedQuery(
        name="quests.check_session_binding",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id, s.routing_confidence, s.routing_method, s.routing_state
            """,
        params=("sid",),
        mutating=False,
        description="Check existing session binding to a MainQuest.",
        sparql="""
            SELECT ?quest_id ?routing_confidence ?routing_method ?routing_state WHERE {
                ?s a campy:Session ; campy:session_id ?sid ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?quest_id .
                OPTIONAL { ?s campy:routing_confidence ?routing_confidence }
                OPTIONAL { ?s campy:routing_method ?routing_method }
                OPTIONAL { ?s campy:routing_state ?routing_state }
            }
            """,
    ),
    NamedQuery(
        name="quests.find_active_by_git_root",
        cypher="""
            MATCH (q:MainQuest)
            WHERE q.git_repo_root = $root AND q.status = 'active'
            RETURN q.quest_id LIMIT 1
            """,
        params=("root",),
        mutating=False,
        description="Find active MainQuest by git_repo_root.",
        sparql="""
            SELECT ?quest_id WHERE {
                ?q a campy:MainQuest ;
                   campy:git_repo_root ?root ;
                   campy:status "active" ;
                   campy:quest_id ?quest_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="quests.find_active_by_id",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.status = 'active'
            RETURN q.quest_id LIMIT 1
            """,
        params=("qid",),
        mutating=False,
        description="Find active MainQuest by quest_id.",
        sparql="""
            SELECT ?quest_id WHERE {
                ?q a campy:MainQuest ;
                   campy:quest_id ?qid ;
                   campy:status "active" .
                BIND(?qid AS ?quest_id)
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="quests.get_active_with_embeddings",
        cypher="""
            MATCH (q:MainQuest)
            WHERE q.status = 'active' AND q.archived = false
            RETURN q.quest_id, q.purpose_embedding, q.name, q.purpose, q.embedding
            LIMIT $limit
            """,
        params=("limit",),
        mutating=False,
        description="Fetch active MainQuests with embeddings.",
    ),
    NamedQuery(
        name="quests.find_active_by_workspace_path",
        cypher="""
            MATCH (q:MainQuest)-[:ANCHORED_TO]->(w:Workspace {path: $path})
            WHERE q.status = 'active'
            RETURN q.quest_id
            """,
        params=("path",),
        mutating=False,
        description="Find active MainQuests anchored to a workspace path.",
        sparql="""
            SELECT ?quest_id WHERE {
                ?q a campy:MainQuest ;
                   campy:ANCHORED_TO ?w ;
                   campy:status "active" ;
                   campy:quest_id ?quest_id .
                ?w a campy:Workspace ; campy:path ?path .
            }
            """,
    ),
    NamedQuery(
        name="quests.get_quest_name_purpose",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) RETURN q.name, q.purpose",
        params=("qid",),
        mutating=False,
        description="Fetch MainQuest name and purpose.",
        sparql="""
            SELECT ?name ?purpose WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid ; campy:name ?name .
                OPTIONAL { ?q campy:purpose ?purpose }
            }
            """,
    ),
    NamedQuery(
        name="quests.set_git_repo_root",
        cypher="""
            MATCH (q:MainQuest {quest_id: $qid})
            WHERE q.git_repo_root IS NULL OR q.git_repo_root = ''
            SET q.git_repo_root = $root
            """,
        params=("qid", "root"),
        mutating=True,
        description="Set git_repo_root on MainQuest if empty.",
        sparql="""
            DELETE { ?q campy:git_repo_root ?old_root . }
            INSERT { ?q campy:git_repo_root ?root . }
            WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                OPTIONAL { ?q campy:git_repo_root ?old_root }
                FILTER(!BOUND(?old_root) || ?old_root = "")
            }
            """,
    ),
    NamedQuery(
        name="quests.get_session_routing",
        cypher="""
            MATCH (s:Session {session_id: $sid})
            RETURN s.routing_confidence, s.routing_state
            """,
        params=("sid",),
        mutating=False,
        description="Fetch Session routing confidence and state.",
        sparql="""
            SELECT ?routing_confidence ?routing_state WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                OPTIONAL { ?s campy:routing_confidence ?routing_confidence }
                OPTIONAL { ?s campy:routing_state ?routing_state }
            }
            """,
    ),
    NamedQuery(
        name="quests.update_session_routing",
        cypher="""
            MATCH (s:Session {session_id: $sid})
            SET s.routing_confidence = $conf, s.routing_state = $state
            """,
        params=("sid", "conf", "state"),
        mutating=True,
        description="Update Session routing confidence and state.",
        sparql="""
            DELETE {
                ?s campy:routing_confidence ?old_conf .
                ?s campy:routing_state ?old_state .
            }
            INSERT {
                ?s campy:routing_confidence ?conf ;
                   campy:routing_state ?state .
            }
            WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                OPTIONAL { ?s campy:routing_confidence ?old_conf }
                OPTIONAL { ?s campy:routing_state ?old_state }
            }
            """,
    ),
    NamedQuery(
        name="quests.get_session_working_quest_id",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[:WORKING_ON]->(q:MainQuest)
            RETURN q.quest_id
            """,
        params=("sid",),
        mutating=False,
        description="Fetch MainQuest quest_id that Session is working on.",
        sparql="""
            SELECT ?quest_id WHERE {
                ?s a campy:Session ; campy:session_id ?sid ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?quest_id .
            }
            """,
    ),
    NamedQuery(
        name="quests.delete_session_working_on",
        cypher="""
            MATCH (s:Session {session_id: $sid})-[w:WORKING_ON]->(q:MainQuest {quest_id: $qid})
            DELETE w
            """,
        params=("sid", "qid"),
        mutating=True,
        description="Delete WORKING_ON edge between Session and MainQuest.",
        sparql="""
            DELETE { ?s campy:WORKING_ON ?q . }
            WHERE {
                ?s a campy:Session ; campy:session_id ?sid ; campy:WORKING_ON ?q .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
            }
            """,
    ),
    NamedQuery(
        name="quests.create_rerouted_from",
        cypher="""
            MATCH (s:Session {session_id: $sid}), (q:MainQuest {quest_id: $qid})
            CREATE (s)-[:REROUTED_FROM {rerouted_at: timestamp($now), reason: $reason}]->(q)
            """,
        params=("sid", "qid", "now", "reason"),
        mutating=True,
        description="Create REROUTED_FROM audit edge between Session and MainQuest.",
    ),

    NamedQuery(
        name="quests.find_active_main_quest_by_name",
        cypher="MATCH (q:MainQuest) WHERE q.name = $name AND q.status = 'active' RETURN q.quest_id LIMIT 1",
        params=("name",),
        mutating=False,
        description="Find active MainQuest by exact name",
        sparql="""
            SELECT ?quest_id WHERE {
                ?q a campy:MainQuest ; campy:name ?name ; campy:status "active" ; campy:quest_id ?quest_id .
            }
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="quests.complete_main_quest",
        cypher="MATCH (q:MainQuest {quest_id: $qid}) SET q.status = 'completed', q.completed_at = timestamp($now)",
        params=("qid", "now"),
        mutating=True,
        description="Mark MainQuest completed",
        sparql="""
            DELETE {
                ?q campy:status ?old_status .
                ?q campy:completed_at ?old_completed_at .
            }
            INSERT {
                ?q campy:status "completed" ;
                   campy:completed_at ?now .
            }
            WHERE {
                ?q a campy:MainQuest ; campy:quest_id ?qid .
                OPTIONAL { ?q campy:status ?old_status }
                OPTIONAL { ?q campy:completed_at ?old_completed_at }
            }
            """,
    ),
    NamedQuery(
        name="quests.complete_side_quest",
        cypher="MATCH (q:SideQuest {quest_id: $qid}) SET q.status = 'completed', q.completed_at = timestamp($now)",
        params=("qid", "now"),
        mutating=True,
        description="Mark SideQuest completed",
        sparql="""
            DELETE {
                ?q campy:status ?old_status .
                ?q campy:completed_at ?old_completed_at .
            }
            INSERT {
                ?q campy:status "completed" ;
                   campy:completed_at ?now .
            }
            WHERE {
                ?q a campy:SideQuest ; campy:quest_id ?qid .
                OPTIONAL { ?q campy:status ?old_status }
                OPTIONAL { ?q campy:completed_at ?old_completed_at }
            }
            """,
    ),
    NamedQuery(
        name="quests.set_plan_step_outcome",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        WHERE ps.step_number = $step_number
        SET ps.actual_outcome = $outcome,
            ps.valence = $valence,
            ps.status = $status,
            ps.completed_at = timestamp($now)
        """,
        params=("pid", "step_number", "outcome", "valence", "status", "now"),
        mutating=True,
        description="Update PlanStep outcome and status",
        sparql="""
            DELETE {
                ?ps campy:actual_outcome ?old_outcome .
                ?ps campy:valence ?old_valence .
                ?ps campy:status ?old_status .
                ?ps campy:completed_at ?old_completed_at .
            }
            INSERT {
                ?ps campy:actual_outcome ?outcome ;
                    campy:valence ?valence ;
                    campy:status ?status ;
                    campy:completed_at ?now .
            }
            WHERE {
                ?ps a campy:PlanStep ;
                    campy:STEP_OF ?p ;
                    campy:step_number ?step_number .
                ?p a campy:Plan ; campy:plan_id ?pid .
                OPTIONAL { ?ps campy:actual_outcome ?old_outcome }
                OPTIONAL { ?ps campy:valence ?old_valence }
                OPTIONAL { ?ps campy:status ?old_status }
                OPTIONAL { ?ps campy:completed_at ?old_completed_at }
            }
            """,
    ),
    NamedQuery(
        name="quests.link_plan_step_outcome_signal",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        WHERE ps.step_number = $step_number
        MATCH (ps)-[:ACTS_ON]->(c:Concept)
        MERGE (ps)-[o:OUTCOME_SIGNAL]->(c)
        SET o.valence = $valence, o.plan_id = $pid, o.observed_at = timestamp($now)
        """,
        params=("pid", "step_number", "valence", "now"),
        mutating=True,
        description="Merge OUTCOME_SIGNAL from PlanStep to Concept",
    ),
    NamedQuery(
        name="quests.set_plan_valence",
        cypher="""
        MATCH (p:Plan {plan_id: $pid})
        SET p.valence = $valence,
            p.valence_source = $valence_source,
            p.status = 'completed',
            p.completed_at = timestamp($now)
        """,
        params=("pid", "valence", "valence_source", "now"),
        mutating=True,
        description="Update Plan valence and mark completed",
        sparql="""
            DELETE {
                ?p campy:valence ?old_valence .
                ?p campy:valence_source ?old_valence_source .
                ?p campy:status ?old_status .
                ?p campy:completed_at ?old_completed_at .
            }
            INSERT {
                ?p campy:valence ?valence ;
                   campy:valence_source ?valence_source ;
                   campy:status "completed" ;
                   campy:completed_at ?now .
            }
            WHERE {
                ?p a campy:Plan ; campy:plan_id ?pid .
                OPTIONAL { ?p campy:valence ?old_valence }
                OPTIONAL { ?p campy:valence_source ?old_valence_source }
                OPTIONAL { ?p campy:status ?old_status }
                OPTIONAL { ?p campy:completed_at ?old_completed_at }
            }
            """,
    ),
    NamedQuery(
        name="quests.link_plan_applied_procedure",
        cypher="""
        MATCH (p:Plan {plan_id: $pid}), (pr:Procedure {procedure_id: $proc_id})
        MERGE (p)-[r:APPLIED_PROCEDURE]->(pr)
        SET r.success = $success, r.applied_at = timestamp($now)
        """,
        params=("pid", "proc_id", "success", "now"),
        mutating=True,
        description="Link Plan to applied Procedure with APPLIED_PROCEDURE",
    ),
    NamedQuery(
        name="quests.increment_procedure_counts",
        cypher="""
        MATCH (pr:Procedure {procedure_id: $proc_id})
        SET pr.application_count = coalesce(pr.application_count, 0) + 1,
            pr.success_count = coalesce(pr.success_count, 0) + CASE WHEN $success THEN 1 ELSE 0 END,
            pr.last_applied_at = timestamp($now)
        """,
        params=("proc_id", "success", "now"),
        mutating=True,
        description="Increment Procedure application and success counts",
        sparql="""
            DELETE {
                ?pr campy:application_count ?old_application_count .
                ?pr campy:success_count ?old_success_count .
                ?pr campy:last_applied_at ?old_last_applied_at .
            }
            INSERT {
                ?pr campy:application_count ?new_application_count ;
                    campy:success_count ?new_success_count ;
                    campy:last_applied_at ?now .
            }
            WHERE {
                ?pr a campy:Procedure ; campy:procedure_id ?proc_id .
                OPTIONAL { ?pr campy:application_count ?old_application_count }
                OPTIONAL { ?pr campy:success_count ?old_success_count }
                OPTIONAL { ?pr campy:last_applied_at ?old_last_applied_at }
                BIND(STRDT(STR(COALESCE(?old_application_count, 0) + 1), xsd:int) AS ?new_application_count)
                BIND(STRDT(STR(COALESCE(?old_success_count, 0) + IF(?success, 1, 0)), xsd:int) AS ?new_success_count)
            }
            """,
    ),
    NamedQuery(
        name="quests.update_procedure_success_rate",
        cypher="""
        MATCH (pr:Procedure {procedure_id: $proc_id})
        SET pr.success_rate = CASE WHEN coalesce(pr.application_count,0) > 0
        THEN toFloat(coalesce(pr.success_count,0)) / toFloat(pr.application_count) ELSE 0.0 END
        """,
        params=("proc_id",),
        mutating=True,
        description="Recalculate Procedure success rate",
        sparql="""
            DELETE { ?pr campy:success_rate ?old_success_rate . }
            INSERT { ?pr campy:success_rate ?new_success_rate . }
            WHERE {
                ?pr a campy:Procedure ; campy:procedure_id ?proc_id .
                OPTIONAL { ?pr campy:success_rate ?old_success_rate }
                OPTIONAL { ?pr campy:application_count ?app_count }
                OPTIONAL { ?pr campy:success_count ?succ_count }
                BIND(IF(BOUND(?app_count) && ?app_count > 0,
                        STRDT(STR(xsd:double(COALESCE(?succ_count, 0)) / xsd:double(?app_count)), xsd:double),
                        "0.0"^^xsd:double) AS ?new_success_rate)
            }
            """,
    ),
    NamedQuery(
        name="quests.get_plan_steps_by_plan_id",
        cypher="""
        MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid})
        RETURN ps.step_number, ps.description, ps.valence, ps.status
        ORDER BY ps.step_number ASC
        """,
        params=("pid",),
        mutating=False,
        description="Fetch steps for a plan",
        sparql="""
            SELECT ?step_number ?description ?valence ?status WHERE {
                ?ps a campy:PlanStep ;
                    campy:STEP_OF ?p ;
                    campy:step_number ?step_number ;
                    campy:description ?description .
                OPTIONAL { ?ps campy:valence ?valence }
                OPTIONAL { ?ps campy:status ?status }
                ?p a campy:Plan ; campy:plan_id ?pid .
            }
            ORDER BY ASC(?step_number)
            """,
    ),
    NamedQuery(
        name="quests.get_all_plans_summary",
        cypher="""
        MATCH (p:Plan) WHERE p.archived = false
        RETURN p.plan_id, p.goal, p.status, p.valence, p.pathway_strength, p.confidence
        """,
        params=(),
        mutating=False,
        description="Fetch all active plans for lexical scan",
        sparql="""
            SELECT ?plan_id ?goal ?status ?valence ?pathway_strength ?confidence WHERE {
                ?p a campy:Plan ;
                   campy:plan_id ?plan_id ;
                   campy:goal ?goal .
                OPTIONAL { ?p campy:status ?status }
                OPTIONAL { ?p campy:valence ?valence }
                OPTIONAL { ?p campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?p campy:confidence ?confidence }
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            """,
    ),
    NamedQuery(
        name="quests.get_procedures_by_archetype",
        cypher="""
        MATCH (p:Procedure) WHERE p.archived = false AND p.archetype = $arch
        RETURN p.procedure_id, p.name, p.description, p.steps_json, p.success_count, p.success_rate
        ORDER BY p.success_rate DESC, p.success_count DESC LIMIT $lim
        """,
        params=("arch", "lim"),
        mutating=False,
        description="Fetch procedures by archetype ordered by success rate",
        sparql="""
            SELECT ?procedure_id ?name ?description ?steps_json ?success_count ?success_rate WHERE {
                ?p a campy:Procedure ;
                   campy:archetype ?arch ;
                   campy:procedure_id ?procedure_id ;
                   campy:name ?name ;
                   campy:description ?description ;
                   campy:steps_json ?steps_json .
                OPTIONAL { ?p campy:success_count ?success_count }
                OPTIONAL { ?p campy:success_rate ?success_rate }
                OPTIONAL { ?p campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            ORDER BY DESC(?success_rate) DESC(?success_count)
            """,
    ),
    NamedQuery(
        name="quests.get_pending_disambiguation_events",
        cypher="""
        MATCH (e:DisambiguationEvent)
        WHERE e.status = 'pending'
        RETURN e.event_id, e.concept_id_a, e.concept_id_b, e.similarity, e.created_at
        ORDER BY e.created_at DESC LIMIT $lim
        """,
        params=("lim",),
        mutating=False,
        description="Fetch pending disambiguation events",
        sparql="""
            SELECT ?event_id ?concept_id_a ?concept_id_b ?similarity ?created_at WHERE {
                ?e a campy:DisambiguationEvent ;
                   campy:status "pending" ;
                   campy:event_id ?event_id ;
                   campy:concept_id_a ?concept_id_a ;
                   campy:concept_id_b ?concept_id_b ;
                   campy:similarity ?similarity ;
                   campy:created_at ?created_at .
            }
            ORDER BY DESC(?created_at)
            """,
    ),
    NamedQuery(
        name="quests.get_concept_with_alt_labels",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        OPTIONAL MATCH (c)-[:HAS_ALT_LABEL]->(l:Label)
        RETURN c.concept_id, c.text_raw, c.gist_class, c.confidence,
               c.pathway_strength, c.confidence_low, collect(l.text) AS alt_labels
        """,
        params=("cid",),
        mutating=False,
        description="Fetch concept details and alt labels",
        sparql="""
            SELECT (?cid AS ?concept_id) ?text_raw ?gist_class ?confidence ?pathway_strength ?confidence_low (GROUP_CONCAT(?label_text; separator=",") AS ?alt_labels) WHERE {
                ?c a campy:Concept ;
                   campy:concept_id ?cid ;
                   campy:text_raw ?text_raw .
                OPTIONAL { ?c campy:gist_class ?gist_class }
                OPTIONAL { ?c campy:confidence ?confidence }
                OPTIONAL { ?c campy:pathway_strength ?pathway_strength }
                OPTIONAL { ?c campy:confidence_low ?confidence_low }
                OPTIONAL {
                    ?c campy:HAS_ALT_LABEL ?l .
                    ?l a campy:Label ; campy:text ?label_text .
                }
            }
            GROUP BY ?cid ?text_raw ?gist_class ?confidence ?pathway_strength ?confidence_low
            """,
    ),
    NamedQuery(
        name="quests.get_common_neighbors_concepts",
        cypher="""
        MATCH (a:Concept {concept_id: $a})-[]->(n:Concept)<-[]-(b:Concept {concept_id: $b})
        WHERE n.archived = false
        RETURN DISTINCT n.concept_id, n.text_raw LIMIT 10
        """,
        params=("a", "b"),
        mutating=False,
        description="Fetch common neighbors between two concepts",
        sparql="""
            SELECT DISTINCT ?concept_id ?text_raw WHERE {
                ?ca a campy:Concept ; campy:concept_id ?a .
                ?cb a campy:Concept ; campy:concept_id ?b .
                ?ca ?p1 ?n .
                ?cb ?p2 ?n .
                ?n a campy:Concept ;
                   campy:concept_id ?concept_id ;
                   campy:text_raw ?text_raw .
                OPTIONAL { ?n campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            LIMIT 10
            """,
    ),
    NamedQuery(
        name="quests.get_disambiguation_event_by_id",
        cypher="""
        MATCH (e:DisambiguationEvent {event_id: $eid})
        RETURN e.concept_id_a, e.concept_id_b, e.status
        """,
        params=("eid",),
        mutating=False,
        description="Fetch disambiguation event by id",
        sparql="""
            SELECT ?concept_id_a ?concept_id_b ?status WHERE {
                ?e a campy:DisambiguationEvent ;
                   campy:event_id ?eid ;
                   campy:concept_id_a ?concept_id_a ;
                   campy:concept_id_b ?concept_id_b .
                OPTIONAL { ?e campy:status ?status }
            }
            """,
    ),
    NamedQuery(
        name="quests.get_two_concepts_details",
        cypher="""
        MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b})
        RETURN a.concept_id, a.created_at, a.text_raw, b.concept_id, b.created_at, b.text_raw
        """,
        params=("a", "b"),
        mutating=False,
        description="Fetch details for two concepts for disambiguation",
        sparql="""
            SELECT ?a_concept_id ?a_created_at ?a_text_raw ?b_concept_id ?b_created_at ?b_text_raw WHERE {
                ?ca a campy:Concept ; campy:concept_id ?a ; campy:text_raw ?a_text_raw .
                ?cb a campy:Concept ; campy:concept_id ?b ; campy:text_raw ?b_text_raw .
                OPTIONAL { ?ca campy:created_at ?a_created_at }
                OPTIONAL { ?cb campy:created_at ?b_created_at }
                BIND(?a AS ?a_concept_id)
                BIND(?b AS ?b_concept_id)
            }
            """,
    ),
    NamedQuery(
        name="quests.create_alt_label",
        cypher="""
        CREATE (l:Label {
          label_id: $lid, text: $txt, label_type: 'alternative',
          confidence: 0.95, source: 'user', language: 'en', created_at: timestamp($now)
        })
        """,
        params=("lid", "txt", "now"),
        mutating=True,
        description="Create alternative Label node",
        sparql="""
            INSERT {
                ?l a campy:Label ;
                   campy:label_id ?lid ;
                   campy:text ?txt ;
                   campy:label_type "alternative" ;
                   campy:confidence "0.95"^^xsd:double ;
                   campy:source "user" ;
                   campy:language "en" ;
                   campy:created_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT(STR(cid:), "Label/", ENCODE_FOR_URI(?lid))) AS ?l)
            }
            """,
    ),
    NamedQuery(
        name="quests.set_label_embedding",
        cypher="""
        MATCH (l:Label {label_id: $lid}) SET l.embedding = $emb
        """,
        params=("lid", "emb"),
        mutating=True,
        description="Set embedding on Label node",
    ),
    NamedQuery(
        name="quests.link_concept_has_alt_label",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid})
        CREATE (c)-[:HAS_ALT_LABEL {created_at: timestamp($now)}]->(l)
        """,
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to Label via HAS_ALT_LABEL",
        sparql="""
            INSERT { ?c campy:HAS_ALT_LABEL ?l . }
            WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid .
                ?l a campy:Label ; campy:label_id ?lid .
            }
            """,
    ),
    NamedQuery(
        name="quests.archive_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}) SET c.archived = true
        """,
        params=("cid",),
        mutating=True,
        description="Archive Concept node",
        sparql="""
            DELETE { ?c campy:archived ?old_archived . }
            INSERT { ?c campy:archived true . }
            WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid .
                OPTIONAL { ?c campy:archived ?old_archived }
            }
            """,
    ),
    NamedQuery(
        name="quests.boost_canonical_concept",
        cypher="""
        MATCH (c:Concept {concept_id: $cid})
        SET c.pathway_strength = c.pathway_strength + 0.15,
            c.confidence_low = false,
            c.last_accessed_at = timestamp($now)
        """,
        params=("cid", "now"),
        mutating=True,
        description="Boost canonical Concept pathway_strength and touch last_accessed_at",
        sparql="""
            DELETE {
                ?c campy:pathway_strength ?old_pathway_strength .
                ?c campy:confidence_low ?old_confidence_low .
                ?c campy:last_accessed_at ?old_last_accessed_at .
            }
            INSERT {
                ?c campy:pathway_strength ?new_pathway_strength ;
                   campy:confidence_low false ;
                   campy:last_accessed_at ?now .
            }
            WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid ; campy:pathway_strength ?old_pathway_strength .
                OPTIONAL { ?c campy:confidence_low ?old_confidence_low }
                OPTIONAL { ?c campy:last_accessed_at ?old_last_accessed_at }
                BIND(STRDT(STR(?old_pathway_strength + "0.15"^^xsd:double), xsd:double) AS ?new_pathway_strength)
            }
            """,
    ),
    NamedQuery(
        name="quests.link_distinct_from",
        cypher="""
        MATCH (a:Concept {concept_id: $a}), (b:Concept {concept_id: $b})
        SET a.confidence_low = false, b.confidence_low = false
        CREATE (a)-[:DISTINCT_FROM {created_at: timestamp($now), source: 'user'}]->(b)
        """,
        params=("a", "b", "now"),
        mutating=True,
        description="Link concepts via DISTINCT_FROM",
    ),
    NamedQuery(
        name="quests.update_disambiguation_event_status",
        cypher="""
        MATCH (e:DisambiguationEvent {event_id: $eid})
        SET e.status = $status, e.resolved_at = timestamp($now), e.resolved_by = 'user'
        """,
        params=("eid", "status", "now"),
        mutating=True,
        description="Update DisambiguationEvent status and resolution",
        sparql="""
            DELETE {
                ?e campy:status ?old_status .
                ?e campy:resolved_at ?old_resolved_at .
                ?e campy:resolved_by ?old_resolved_by .
            }
            INSERT {
                ?e campy:status ?status ;
                   campy:resolved_at ?now ;
                   campy:resolved_by "user" .
            }
            WHERE {
                ?e a campy:DisambiguationEvent ; campy:event_id ?eid .
                OPTIONAL { ?e campy:status ?old_status }
                OPTIONAL { ?e campy:resolved_at ?old_resolved_at }
                OPTIONAL { ?e campy:resolved_by ?old_resolved_by }
            }
            """,
    ),
    NamedQuery(
        name="quests.get_anomalies_branch_scope",
        cypher="""
        MATCH (q:MainQuest {quest_id: $quest_id})
        MATCH (n:Concept)-[:REIFIED_AS]-(a:Decision)-[:ESTABLISHED_IN]->(s:Session)
        MATCH (s)-[:WORKING_ON]->(q)
        WHERE n.flagged_for_review = true
        MATCH (n)-[r:ANOMALY_DETECTED]->(gc:GlobalConstraint)
        RETURN n, r, gc
        LIMIT $limit
        """,
        params=("quest_id", "limit"),
        mutating=False,
        description="Review anomalies under branch scope",
    ),
    NamedQuery(
        name="quests.get_anomalies_global_scope",
        cypher="""
        MATCH (n)
        WHERE n.flagged_for_review = true AND (n:Concept OR n:Decision OR n:Constraint OR
              n:Requirement OR n:ActionItem OR n:Message OR n:DocumentExtract)
        MATCH (n)-[r:ANOMALY_DETECTED]->(gc:GlobalConstraint)
        RETURN n, r, gc
        LIMIT $limit
        """,
        params=("limit",),
        mutating=False,
        description="Review anomalies under global scope",
    ),
    NamedQuery(
        name="quests.get_session_onboarding_status",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        OPTIONAL MATCH (s)-[:WORKING_ON]->(q:MainQuest)
        RETURN s.onboarded, q.name, q.git_branch
        """,
        params=("sid",),
        mutating=False,
        description="Get Session onboarding status and quest details",
        sparql="""
            SELECT ?onboarded ?name ?git_branch WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                OPTIONAL { ?s campy:onboarded ?onboarded }
                OPTIONAL {
                    ?s campy:WORKING_ON ?q .
                    ?q a campy:MainQuest .
                    OPTIONAL { ?q campy:name ?name }
                    OPTIONAL { ?q campy:git_branch ?git_branch }
                }
            }
            """,
    ),
    NamedQuery(
        name="quests.set_session_onboarded",
        cypher="""
        MATCH (s:Session {session_id: $sid}) SET s.onboarded = true
        """,
        params=("sid",),
        mutating=True,
        description="Set Session onboarded flag to true",
        sparql="""
            DELETE { ?s campy:onboarded ?old_onboarded . }
            INSERT { ?s campy:onboarded true . }
            WHERE {
                ?s a campy:Session ; campy:session_id ?sid .
                OPTIONAL { ?s campy:onboarded ?old_onboarded }
            }
            """,
    ),

    NamedQuery(
        name="quests.redirect_edge_requires",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:REQUIRES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:REQUIRES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect REQUIRES edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:REQUIRES ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:REQUIRES ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_enables",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:ENABLES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:ENABLES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect ENABLES edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:ENABLES ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:ENABLES ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_replaces",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:REPLACES]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:REPLACES]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect REPLACES edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:REPLACES ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:REPLACES ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_contradicts",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CONTRADICTS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CONTRADICTS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CONTRADICTS edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:CONTRADICTS ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:CONTRADICTS ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_part_of",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:PART_OF]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:PART_OF]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect PART_OF edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:PART_OF ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:PART_OF ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_chosen_over",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CHOSEN_OVER]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CHOSEN_OVER]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CHOSEN_OVER edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:CHOSEN_OVER ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:CHOSEN_OVER ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_implements",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:IMPLEMENTS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:IMPLEMENTS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect IMPLEMENTS edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:IMPLEMENTS ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:IMPLEMENTS ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_extends",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:EXTENDS]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:EXTENDS]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect EXTENDS edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:EXTENDS ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:EXTENDS ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_alternative_to",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:ALTERNATIVE_TO]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:ALTERNATIVE_TO]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect ALTERNATIVE_TO edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:ALTERNATIVE_TO ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:ALTERNATIVE_TO ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
    NamedQuery(
        name="quests.redirect_edge_co_occurs_with",
        cypher="""
        MATCH (dup:Concept {concept_id: $dup})-[r:CO_OCCURS_WITH]->(t:Concept)
        WHERE t.concept_id <> $can
        MATCH (can:Concept {concept_id: $can})
        MERGE (can)-[:CO_OCCURS_WITH]->(t)
        """,
        params=("dup", "can"),
        mutating=True,
        description="Redirect CO_OCCURS_WITH edge from duplicate to canonical concept",
        sparql="""
            INSERT { ?canc campy:CO_OCCURS_WITH ?t . }
            WHERE {
                ?dupc a campy:Concept ; campy:concept_id ?dup ; campy:CO_OCCURS_WITH ?t .
                ?t a campy:Concept ; campy:concept_id ?t_concept_id .
                FILTER(?t_concept_id != ?can)
                ?canc a campy:Concept ; campy:concept_id ?can .
            }
            """,
    ),
)
