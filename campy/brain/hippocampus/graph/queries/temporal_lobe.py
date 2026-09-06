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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?concept_id
            WHERE {
              ?c a campy:Concept ;
                 campy:concept_id ?concept_id ;
                 campy:text_raw ?text_raw .
              OPTIONAL { ?c campy:archived ?archived }
              FILTER((!BOUND(?archived) || ?archived = false) && LCASE(STR(?text_raw)) = LCASE(STR(?t)))
            }
            LIMIT 1
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?c a campy:Concept ;
                 campy:concept_id ?cid ;
                 campy:text_raw ?text ;
                 campy:embedding ?emb ;
                 campy:embedding_model "sentence-transformers/all-MiniLM-L6-v2" ;
                 campy:embedding_dim 384 ;
                 campy:gist_class ?gist ;
                 campy:schema_org_type ?stype ;
                 campy:confidence 0.95 ;
                 campy:confidence_low false ;
                 campy:pathway_strength 0.80 ;
                 campy:archived false ;
                 campy:flagged_for_review false ;
                 campy:created_at ?now ;
                 campy:last_accessed_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Concept/", ENCODE_FOR_URI(STR(?cid)))) AS ?c)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?l a campy:Label ;
                 campy:label_id ?lid ;
                 campy:text ?txt ;
                 campy:embedding ?emb ;
                 campy:language "en" ;
                 campy:label_type "preferred" ;
                 campy:confidence 0.95 ;
                 campy:source "domain_dictionary" ;
                 campy:created_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Label/", ENCODE_FOR_URI(STR(?lid)))) AS ?l)
            }
        """,
    ),
    NamedQuery(
        name="temporal_lobe.dict_link_pref_label",
        cypher="MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
               "CREATE (c)-[:HAS_PREF_LABEL {created_at: $now}]->(l)",
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to preferred Label",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?c campy:HAS_PREF_LABEL ?l .
            }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?l a campy:Label ; campy:label_id ?lid .
            }
        """,
    ),
    NamedQuery(
        name="temporal_lobe.dict_find_alt_label",
        cypher="MATCH (c:Concept {concept_id: $cid})-[:HAS_ALT_LABEL]->(l:Label) "
               "WHERE toLower(l.text) = toLower($txt) "
               "RETURN l.label_id LIMIT 1",
        params=("cid", "txt"),
        mutating=False,
        description="Find alternative Label for concept",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?label_id
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?c campy:HAS_ALT_LABEL ?l .
              ?l a campy:Label ; campy:label_id ?label_id ; campy:text ?text .
              FILTER(LCASE(STR(?text)) = LCASE(STR(?txt)))
            }
            LIMIT 1
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?l a campy:Label ;
                 campy:label_id ?lid ;
                 campy:text ?txt ;
                 campy:embedding ?emb ;
                 campy:language "en" ;
                 campy:label_type "alternative" ;
                 campy:confidence 0.90 ;
                 campy:source "domain_dictionary" ;
                 campy:created_at ?now .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/Label/", ENCODE_FOR_URI(STR(?lid)))) AS ?l)
            }
        """,
    ),
    NamedQuery(
        name="temporal_lobe.dict_link_alt_label",
        cypher="MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
               "CREATE (c)-[:HAS_ALT_LABEL {created_at: $now}]->(l)",
        params=("cid", "lid", "now"),
        mutating=True,
        description="Link Concept to alternative Label",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?c campy:HAS_ALT_LABEL ?l .
            }
            WHERE {
              ?c a campy:Concept ; campy:concept_id ?cid .
              ?l a campy:Label ; campy:label_id ?lid .
            }
        """,
    ),

    # warm_frontier.py
    NamedQuery(
        name="temporal_lobe.warm_clear_session",
        cypher="MATCH (s:Session {session_id: $sid})-[w:WARM_NODE]->() DELETE w",
        params=("sid",),
        mutating=True,
        description="Clear old warm frontier for session",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?s campy:WARM_NODE ?n .
            }
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              ?s campy:WARM_NODE ?n .
            }
        """,
    ),
    NamedQuery(
        name="temporal_lobe.warm_set_session_time",
        cypher="MATCH (s:Session {session_id: $sid}) SET s.last_warm_frontier_at = timestamp($now)",
        params=("sid", "now"),
        mutating=True,
        description="Update Session.last_warm_frontier_at",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?s campy:last_warm_frontier_at ?old .
            }
            INSERT {
              ?s campy:last_warm_frontier_at ?now .
            }
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              OPTIONAL { ?s campy:last_warm_frontier_at ?old }
            }
        """,
    ),

    # brain_daemon.py
    NamedQuery(
        name="temporal_lobe.daemon_session_set_loop_summary",
        cypher="MATCH (s:Session {session_id: $sid}) "
               "SET s.last_loop_summary = $summary",
        params=("sid", "summary"),
        mutating=True,
        description="Persist loop summary to Session node",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
              ?s campy:last_loop_summary ?old .
            }
            INSERT {
              ?s campy:last_loop_summary ?summary .
            }
            WHERE {
              ?s a campy:Session ; campy:session_id ?sid .
              OPTIONAL { ?s campy:last_loop_summary ?old }
            }
        """,
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
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                INSERT {{
                  ?s campy:WARM_NODE ?n .
                  << ?s campy:WARM_NODE ?n >> campy:occurrence ?occ .
                  ?occ a campy:Occurrence ;
                       campy:activation_score ?score ;
                       campy:activated_at ?now .
                }}
                WHERE {{
                  ?s a campy:Session ; campy:session_id ?sid .
                  ?n a campy:{_table} ; campy:{_pk} ?nid .
                  BIND(IRI(CONCAT("https://campy.dev/data/occurrence/", ENCODE_FOR_URI(STR(?sid)), "_warm_", ENCODE_FOR_URI(STR(?nid)), "_", ENCODE_FOR_URI(STR(?now)))) AS ?occ)
                }}
            """,
        ),
        NamedQuery(
            name=f"temporal_lobe.warm_get_{_tbl_lower}",
            cypher=f"MATCH (s:Session {{session_id: $sid}})-[w:WARM_NODE]->(n:{_table}) "
                   f"RETURN n.{_pk}, w.activation_score",
            params=("sid",),
            mutating=False,
            description=f"Retrieve warm nodes of type {_table}",
            sparql=f"""
                PREFIX campy: <https://campy.dev/ns#>

                SELECT ?{_pk} (COALESCE(?occ_score, ?star_score) AS ?activation_score)
                WHERE {{
                  ?s a campy:Session ; campy:session_id ?sid .
                  ?s campy:WARM_NODE ?n .
                  ?n a campy:{_table} ; campy:{_pk} ?{_pk} .
                  OPTIONAL {{
                    << ?s campy:WARM_NODE ?n >> campy:occurrence ?occ .
                    ?occ campy:activation_score ?occ_score .
                  }}
                  OPTIONAL {{
                    << ?s campy:WARM_NODE ?n >> campy:activation_score ?star_score .
                  }}
                }}
            """,
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
                    sparql=f"""
                        PREFIX campy: <https://campy.dev/ns#>

                        SELECT ?{_target_pk}
                        WHERE {{
                          ?a a campy:{_table} ; campy:{_pk} ?id .
                          ?a campy:{_rel} ?b .
                          ?b a campy:{_target_table} ; campy:{_target_pk} ?{_target_pk} .
                        }}
                    """,
                ),
                NamedQuery(
                    name=f"temporal_lobe.warm_neighbor_in_{_table.lower()}_{_rel.lower()}_{_target_table.lower()}",
                    cypher=f"MATCH (a:{_table} {{{_pk}: $id}})<-[:{_rel}]-(b:{_target_table}) RETURN b.{_target_pk}",
                    params=("id",),
                    mutating=False,
                    description=f"Warm neighbor in {_table} {_rel} {_target_table}",
                    sparql=f"""
                        PREFIX campy: <https://campy.dev/ns#>

                        SELECT ?{_target_pk}
                        WHERE {{
                          ?a a campy:{_table} ; campy:{_pk} ?id .
                          ?b campy:{_rel} ?a .
                          ?b a campy:{_target_table} ; campy:{_target_pk} ?{_target_pk} .
                        }}
                    """,
                ),
            ])
