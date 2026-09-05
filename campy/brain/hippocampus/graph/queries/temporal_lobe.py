from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery
from campy.brain.hippocampus.table_registry import tables_with

NODE_PK_MAP = {table.name: table.pk for table in tables_with("warmable")}
rels_to_follow = ["REIFIED_AS", "REQUIRES", "ENABLES", "PART_OF", "IMPLEMENTS", "CO_OCCURS_WITH"]

TEMPORAL_LOBE_QUERIES: list[NamedQuery] = [
    # dictionary.py
    NamedQuery(
        name="temporal_lobe.dict_find_concept",
        cypher="MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) "
               "AND c.archived = false "
               "RETURN c.concept_id LIMIT 1",
        params=("t",),
        mutating=False,
        description="Find concept by lowercase text_raw in dictionary",
    ),
    NamedQuery(
        name="temporal_lobe.dict_create_concept",
        cypher="CREATE (c:Concept {"
               "  concept_id: $cid, text_raw: $text, embedding: $emb,"
               "  embedding_model: 'sentence-transformers/all-MiniLM-L6-v2',"
               "  embedding_dim: 384,"
               "  gist_class: $gist, schema_org_type: $stype,"
               "  confidence: 0.95, confidence_low: false,"
               "  pathway_strength: 0.80, archived: false,"
               "  anomaly_type: null, flagged_for_review: false,"
               "  created_at: $now, last_accessed_at: $now"
               "})",
        params=("cid", "text", "emb", "gist", "stype", "now"),
        mutating=True,
        description="Create Concept node for dictionary term",
    ),
    NamedQuery(
        name="temporal_lobe.dict_create_pref_label",
        cypher="CREATE (l:Label {"
               "  label_id: $lid, text: $txt, embedding: $emb,"
               "  language: 'en', label_type: 'preferred',"
               "  confidence: 0.95, source: 'domain_dictionary',"
               "  created_at: $now"
               "})",
        params=("lid", "txt", "emb", "now"),
        mutating=True,
        description="Create preferred Label node for dictionary term",
    ),
    NamedQuery(
        name="temporal_lobe.dict_link_pref_label",
        cypher="MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
               "CREATE (c)-[:HAS_PREF_LABEL {created_at: $now}]->(l)",
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to preferred Label",
    ),
    NamedQuery(
        name="temporal_lobe.dict_find_alt_label",
        cypher="MATCH (c:Concept {concept_id: $cid})-[:HAS_ALT_LABEL]->(l:Label) "
               "WHERE toLower(l.text) = toLower($txt) "
               "RETURN l.label_id LIMIT 1",
        params=("cid", "txt"),
        mutating=False,
        description="Find alternative Label for concept",
    ),
    NamedQuery(
        name="temporal_lobe.dict_create_alt_label",
        cypher="CREATE (l:Label {"
               "  label_id: $lid, text: $txt, embedding: $emb,"
               "  language: 'en', label_type: 'alternative',"
               "  confidence: 0.90, source: 'domain_dictionary',"
               "  created_at: $now"
               "})",
        params=("lid", "txt", "emb", "now"),
        mutating=True,
        description="Create alternative Label node",
    ),
    NamedQuery(
        name="temporal_lobe.dict_link_alt_label",
        cypher="MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
               "CREATE (c)-[:HAS_ALT_LABEL {created_at: $now}]->(l)",
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to alternative Label",
    ),

    # warm_frontier.py
    NamedQuery(
        name="temporal_lobe.warm_clear_session",
        cypher="MATCH (s:Session {session_id: $sid})-[w:WARM_NODE]->() DELETE w",
        params=("sid",),
        mutating=True,
        description="Clear old warm frontier for session",
    ),
    NamedQuery(
        name="temporal_lobe.warm_set_session_time",
        cypher="MATCH (s:Session {session_id: $sid}) SET s.last_warm_frontier_at = timestamp($now)",
        params=("sid", "now"),
        mutating=True,
        description="Update Session.last_warm_frontier_at",
    ),

    # brain_daemon.py
    NamedQuery(
        name="temporal_lobe.daemon_session_set_loop_summary",
        cypher="MATCH (s:Session {session_id: $sid}) "
               "SET s.last_loop_summary = $summary",
        params=("sid", "summary"),
        mutating=True,
        description="Persist loop summary to Session node",
    ),
]

# Per-table warm link and get queries
for _table, _pk in NODE_PK_MAP.items():
    _tbl_lower = _table.lower()
    TEMPORAL_LOBE_QUERIES.extend([
        NamedQuery(
            name=f"temporal_lobe.warm_link_{_tbl_lower}",
            cypher=f"MATCH (s:Session {{session_id: $sid}}), (n:{_table} {{{_pk}: $nid}}) "
                   "CREATE (s)-[:WARM_NODE {activation_score: $score, activated_at: timestamp($now)}]->(n)",
            params=("sid", "nid", "score", "now"),
            mutating=True,
            description=f"Create WARM_NODE link to {_table}",
        ),
        NamedQuery(
            name=f"temporal_lobe.warm_get_{_tbl_lower}",
            cypher=f"MATCH (s:Session {{session_id: $sid}})-[w:WARM_NODE]->(n:{_table}) "
                   f"RETURN n.{_pk}, w.activation_score",
            params=("sid",),
            mutating=False,
            description=f"Retrieve warm nodes of type {_table}",
        ),
    ])

# Neighbor queries for spread activation
for _table, _pk in NODE_PK_MAP.items():
    for _rel in rels_to_follow:
        for _target_table, _target_pk in NODE_PK_MAP.items():
            TEMPORAL_LOBE_QUERIES.extend([
                NamedQuery(
                    name=f"temporal_lobe.warm_neighbor_out_{_table.lower()}_{_rel.lower()}_{_target_table.lower()}",
                    cypher=f"MATCH (a:{_table} {{{_pk}: $id}})-[:{_rel}]->(b:{_target_table}) RETURN b.{_target_pk}",
                    params=("id",),
                    mutating=False,
                    description=f"Warm neighbor out {_table} {_rel} {_target_table}",
                ),
                NamedQuery(
                    name=f"temporal_lobe.warm_neighbor_in_{_table.lower()}_{_rel.lower()}_{_target_table.lower()}",
                    cypher=f"MATCH (a:{_table} {{{_pk}: $id}})<-[:{_rel}]-(b:{_target_table}) RETURN b.{_target_pk}",
                    params=("id",),
                    mutating=False,
                    description=f"Warm neighbor in {_table} {_rel} {_target_table}",
                ),
            ])
