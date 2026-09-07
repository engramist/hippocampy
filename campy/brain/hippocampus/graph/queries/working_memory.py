"""
campy/brain/hippocampus/graph/queries/working_memory.py — Working memory and context tracking queries.

B393: `sparql=` added per docs/rdf-schema-mapping.md. Highest-risk module in
this batch: `LOADED` is classified **`occurrence`** in `EDGE_REIFICATION`
(oxigraph_client.py) — confirmed via `create_loaded_edge_*` below using a
bare `CREATE` (no MERGE/existence check). Per spec §4.2b, `LOADED`'s
properties (`injected_at`, `load_hits`, `token_estimate`) hang off
occurrence nodes attached to the quoted triple, e.g.:

    << ?s campy:LOADED ?n >> campy:occurrence ?occ .
    ?occ campy:load_hits ?load_hits .

NOT off the quoted triple directly (`<< ?s campy:LOADED ?n >> campy:load_hits
?load_hits` — that's the "star" shape and would silently return zero rows
against occurrence-classified data, per the card's warning). The plain
triple `?s campy:LOADED ?n` always traverses regardless of edge class
(spec §4.2b: "both survive"), so queries that only check LOADED's
existence (`get_loaded_ids_*`, `count_loaded_*`, `get_handoff_*`) use the
plain triple and never need the occurrence hop.

`create_loaded_edge_*` mints a **new** occurrence node (ULID identity, see
`mint_occurrence_uri()`) on every call — that identity cannot be expressed
in static parameterized SPARQL text (no call-site param carries a
pre-generated id today), so these 7 queries are documented Python-handler
exceptions (`OxigraphClient.write_edge`, occurrence class) rather than
`sparql=`. `update_loaded_hit_*` only *updates* an *existing* occurrence's
properties (no new identity minted) and so does get a `sparql=`.

Two conventions shared with the rest of the B393 batch (see capture.py's
module docstring for the full rationale): `LIMIT $param` is dropped from
the SPARQL text (ORDER BY is kept; the limit becomes a post-query slice),
and un-aliased Cypher `RETURN n.prop` columns are named `?prop` in SPARQL
(the bare property name) rather than the dotted `n.prop` key Kùzu returns
today — call-site column-key compatibility across engines is B397's
concern, not this additive card's.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

WORKING_MEMORY_QUERIES = [
    NamedQuery(
        name="working_memory.update_session_loaded_stats",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        SET s.loaded_node_count = $count,
            s.last_injection_at = timestamp($now),
            s.injection_count = coalesce(s.injection_count, 0) + $processed,
            s.dedup_tokens_saved = coalesce(s.dedup_tokens_saved, 0) + $dedup
        """,
        params=("sid", "count", "now", "processed", "dedup"),
        mutating=True,
        description="Update session loaded node counts and token metrics",
        sparql="""
            DELETE {
                ?s campy:loaded_node_count ?old_count .
                ?s campy:last_injection_at ?old_last_injection_at .
                ?s campy:injection_count ?old_injection_count .
                ?s campy:dedup_tokens_saved ?old_dedup_tokens_saved .
            }
            INSERT {
                ?s campy:loaded_node_count ?count .
                ?s campy:last_injection_at ?now .
                ?s campy:injection_count ?new_injection_count .
                ?s campy:dedup_tokens_saved ?new_dedup_tokens_saved .
            }
            WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:loaded_node_count ?old_count }
                OPTIONAL { ?s campy:last_injection_at ?old_last_injection_at }
                OPTIONAL { ?s campy:injection_count ?old_injection_count }
                OPTIONAL { ?s campy:dedup_tokens_saved ?old_dedup_tokens_saved }
                BIND((COALESCE(?old_injection_count, "0"^^xsd:long) + ?processed) AS ?new_injection_count)
                BIND((COALESCE(?old_dedup_tokens_saved, "0"^^xsd:long) + ?dedup) AS ?new_dedup_tokens_saved)
            }
            """,
    ),
    NamedQuery(
        name="working_memory.get_token_estimate",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.token_estimate
        """,
        params=("sid",),
        mutating=False,
        description="Get session cumulative token estimate",
        sparql="""
            SELECT ?token_estimate WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:token_estimate ?token_estimate }
            }
            """,
    ),
    NamedQuery(
        name="working_memory.set_token_estimate",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        SET s.token_estimate = $est
        """,
        params=("sid", "est"),
        mutating=True,
        description="Set session cumulative token estimate",
        sparql="""
            DELETE { ?s campy:token_estimate ?old_est }
            INSERT { ?s campy:token_estimate ?est }
            WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:token_estimate ?old_est }
            }
            """,
    ),
    NamedQuery(
        name="working_memory.get_session_token_state",
        cypher="""
        MATCH (s:Session {session_id: $sid})
        RETURN s.token_estimate, s.token_limit, s.loaded_node_count,
               s.dedup_tokens_saved, s.injection_count
        """,
        params=("sid",),
        mutating=False,
        description="Return current token usage vs limit for session",
        sparql="""
            SELECT ?token_estimate ?token_limit ?loaded_node_count
                   ?dedup_tokens_saved ?injection_count WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                OPTIONAL { ?s campy:token_estimate ?token_estimate }
                OPTIONAL { ?s campy:token_limit ?token_limit }
                OPTIONAL { ?s campy:loaded_node_count ?loaded_node_count }
                OPTIONAL { ?s campy:dedup_tokens_saved ?dedup_tokens_saved }
                OPTIONAL { ?s campy:injection_count ?injection_count }
            }
            """,
    ),
    NamedQuery(
        name="working_memory.count_session_messages",
        cypher="""
        MATCH (m:Message)-[:SENT_IN]->(s:Session {session_id: $sid})
        WHERE m.archived IS NULL OR m.archived = false
        RETURN count(m)
        """,
        params=("sid",),
        mutating=False,
        description="Count active messages sent in session",
        sparql="""
            SELECT (COUNT(?m) AS ?count) WHERE {
                ?s a campy:Session ;
                   campy:session_id ?sid .
                ?m campy:SENT_IN ?s ;
                   a campy:Message .
                OPTIONAL { ?m campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
            }
            """,
    ),
    NamedQuery(
        name="working_memory.find_prior_session_on_quest",
        cypher="""
        MATCH (s:Session)-[:WORKING_ON]->(q:MainQuest {quest_id: $qid})
        WHERE s.session_id <> $new_sid
        RETURN s.session_id
        ORDER BY s.last_active_at DESC
        LIMIT 1
        """,
        params=("qid", "new_sid"),
        mutating=False,
        description="Find most recent prior session working on same quest",
        # WORKING_ON is "plain" in EDGE_REIFICATION.
        sparql="""
            SELECT ?session_id WHERE {
                ?q a campy:MainQuest ;
                   campy:quest_id ?qid .
                ?s campy:WORKING_ON ?q ;
                   a campy:Session ;
                   campy:session_id ?session_id ;
                   campy:last_active_at ?last_active_at .
                FILTER(?session_id != ?new_sid)
            }
            ORDER BY DESC(?last_active_at)
            LIMIT 1
            """,
    ),
]

_NODE_PK_MAP = {
    "Concept":          ("concept_id", "concept"),
    "Decision":         ("decision_id", "decision"),
    "Constraint":       ("constraint_id", "constraint"),
    "Requirement":      ("requirement_id", "requirement"),
    "ActionItem":       ("action_item_id", "actionitem"),
    "GlobalConstraint": ("global_constraint_id", "globalconstraint"),
    "GlobalPreference": ("global_preference_id", "globalpreference"),
}

for node_type, (pk_col, key) in _NODE_PK_MAP.items():
    WORKING_MEMORY_QUERIES.extend([
        NamedQuery(
            name=f"working_memory.check_loaded_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}})
            RETURN l.load_hits
            """,
            params=("sid", "nid"),
            mutating=False,
            description=f"Check if {node_type} is already LOADED in session",
            # occurrence class (spec §4.2b) — load_hits hangs off the
            # occurrence node(s), not the quoted triple directly.
            sparql=f"""
                SELECT ?load_hits WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?n a campy:{node_type} ;
                       campy:{pk_col} ?nid .
                    << ?s campy:LOADED ?n >> campy:occurrence ?occ .
                    ?occ campy:load_hits ?load_hits .
                }}
                """,
        ),
        NamedQuery(
            name=f"working_memory.update_loaded_hit_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type} {{{pk_col}: $nid}})
            SET l.injected_at = timestamp($now),
                l.load_hits = $hits,
                l.token_estimate = $tokens
            """,
            params=("sid", "nid", "now", "hits", "tokens"),
            mutating=True,
            description=f"Update existing LOADED edge on {node_type} hit",
            # Updates an EXISTING occurrence's properties in place (no new
            # identity minted, unlike create_loaded_edge_* below) — this is
            # expressible as a plain DELETE/INSERT scoped to the occurrence
            # node(s) already attached to this quoted triple. Cypher's bare
            # `MATCH ... SET` applies to every matched LOADED edge instance;
            # mirrored here by updating every occurrence found, not just one.
            sparql=f"""
                DELETE {{
                    ?occ campy:injected_at ?old_injected_at .
                    ?occ campy:load_hits ?old_load_hits .
                    ?occ campy:token_estimate ?old_token_estimate .
                }}
                INSERT {{
                    ?occ campy:injected_at ?now .
                    ?occ campy:load_hits ?hits .
                    ?occ campy:token_estimate ?tokens .
                }}
                WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?n a campy:{node_type} ;
                       campy:{pk_col} ?nid .
                    << ?s campy:LOADED ?n >> campy:occurrence ?occ .
                    OPTIONAL {{ ?occ campy:injected_at ?old_injected_at }}
                    OPTIONAL {{ ?occ campy:load_hits ?old_load_hits }}
                    OPTIONAL {{ ?occ campy:token_estimate ?old_token_estimate }}
                }}
                """,
        ),
        NamedQuery(
            name=f"working_memory.create_loaded_edge_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}}), (n:{node_type} {{{pk_col}: $nid}})
            CREATE (s)-[:LOADED {{injected_at: timestamp($now), token_estimate: $tokens, source: $source, load_hits: 1}}]->(n)
            """,
            params=("sid", "nid", "now", "tokens", "source"),
            mutating=True,
            description=f"Create new LOADED edge between Session and {node_type}",
            # No sparql=: this CREATEs a brand-new occurrence node with a
            # freshly minted ULID identity (spec §4.2b) on every call — that
            # identity cannot be expressed in static parameterized SPARQL
            # text (no call-site param carries a pre-generated id). Python
            # handler: OxigraphClient.write_edge(table="LOADED",
            # reification="occurrence"), which calls mint_occurrence_uri()
            # and asserts the plain triple + a fresh occurrence node per
            # spec §4.2b, mirroring the NamedQuery docstring's documented
            # "RDF-Star Edge Reification" handler-dispatch boundary.
        ),
        NamedQuery(
            name=f"working_memory.get_loaded_ids_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            RETURN n.{pk_col}
            """,
            params=("sid",),
            mutating=False,
            description=f"Get loaded {node_type} IDs for session",
            # Existence-only traversal of LOADED — the plain triple always
            # asserts regardless of edge class (spec §4.2b), no occurrence
            # hop needed.
            sparql=f"""
                SELECT ?{pk_col} WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?s campy:LOADED ?n .
                    ?n a campy:{node_type} ;
                       campy:{pk_col} ?{pk_col} .
                }}
                """,
        ),
        NamedQuery(
            name=f"working_memory.count_loaded_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            RETURN count(*)
            """,
            params=("sid",),
            mutating=False,
            description=f"Count loaded {node_type} edges for session",
            sparql=f"""
                SELECT (COUNT(?n) AS ?count) WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?s campy:LOADED ?n .
                    ?n a campy:{node_type} .
                }}
                """,
        ),
        NamedQuery(
            name=f"working_memory.get_handoff_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[:LOADED]->(n:{node_type})
            WHERE n.archived = false
            RETURN n.{pk_col}, n.text_raw, n.pathway_strength
            ORDER BY n.pathway_strength DESC
            LIMIT $limit
            """,
            params=("sid", "limit"),
            mutating=False,
            description=f"Get top {node_type} nodes for cross-session handoff",
            # LIMIT $limit dropped (see module docstring); ORDER BY kept.
            sparql=f"""
                SELECT ?{pk_col} ?text_raw ?pathway_strength WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?s campy:LOADED ?n .
                    ?n a campy:{node_type} ;
                       campy:{pk_col} ?{pk_col} ;
                       campy:text_raw ?text_raw ;
                       campy:pathway_strength ?pathway_strength .
                    OPTIONAL {{ ?n campy:archived ?archived }}
                    FILTER(!BOUND(?archived) || ?archived = false)
                }}
                ORDER BY DESC(?pathway_strength)
                """,
        ),
        NamedQuery(
            name=f"working_memory.get_timeline_{key}",
            cypher=f"""
            MATCH (s:Session {{session_id: $sid}})-[l:LOADED]->(n:{node_type})
            RETURN n.{pk_col}, l.injected_at, l.token_estimate, l.load_hits
            ORDER BY l.injected_at ASC
            """,
            params=("sid",),
            mutating=False,
            description=f"Get chronological timeline of LOADED events for {node_type}",
            # occurrence class — injected_at/token_estimate/load_hits hang
            # off the occurrence node(s), not the quoted triple. Each
            # occurrence yields one result row, matching Cypher's one row
            # per matched LOADED edge instance.
            sparql=f"""
                SELECT ?{pk_col} ?injected_at ?token_estimate ?load_hits WHERE {{
                    ?s a campy:Session ;
                       campy:session_id ?sid .
                    ?n a campy:{node_type} ;
                       campy:{pk_col} ?{pk_col} .
                    << ?s campy:LOADED ?n >> campy:occurrence ?occ .
                    ?occ campy:injected_at ?injected_at ;
                         campy:token_estimate ?token_estimate ;
                         campy:load_hits ?load_hits .
                }}
                ORDER BY ASC(?injected_at)
                """,
        ),
    ])
