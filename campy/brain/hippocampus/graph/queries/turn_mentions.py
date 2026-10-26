"""
campy/brain/hippocampus/graph/queries/turn_mentions.py -- B538 turn dates.

Named queries behind `campy.brain.hippocampus.turn_mentions`. A relative time
expression in a user turn ("yesterday", "last week") is a `TimeMention` node,
resolved by rule (`temporal_lobe.observations.turn_dates`) against the turn's
date and hung off its Message by the plain edge `HAS_TIME_MENTION`. The resolved
range is the same typed literals an Observation carries (`time_start`,
`time_end`, `time_precision`, B484).

`turn_mentions.for_messages` is the read: the bundle renderer calls it for the
turns it is about to show and writes the resolved date after each phrase.
`turn_mentions.upsert` replaces a mention's values in place, so re-running the
rule (or the backfill) never leaves two values on one node.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

_NODE_BASE = "https://campy.dev/id/TimeMention/"

TURN_MENTION_QUERIES = [
    NamedQuery(
        name="turn_mentions.upsert",
        cypher="""
        MATCH (m:Message {message_id: $mid})
        MERGE (t:TimeMention {mention_id: $mention_id})
        SET t.time_text = $time_text, t.span_start = $span_start, t.span_end = $span_end,
            t.time_start = $time_start, t.time_end = $time_end, t.time_precision = $time_precision,
            t.archived = false, t.created_at = $now, t.source = 'rule:turn-dates', t.authority = 'earned'
        MERGE (m)-[:HAS_TIME_MENTION]->(t)
        """,
        params=("mid", "mention_id", "time_text", "span_start", "span_end",
                "time_start", "time_end", "time_precision", "now"),
        mutating=True,
        description="Write (or rewrite in place) one resolved relative time expression of a user Message",
        sparql=f"""
            DELETE {{
              ?t campy:time_text ?ot ; campy:span_start ?oa ; campy:span_end ?ob ;
                 campy:time_start ?os ; campy:time_end ?oe ; campy:time_precision ?op ;
                 campy:archived ?oarch ; campy:created_at ?ocr
            }}
            INSERT {{
              ?t a campy:TimeMention ;
                 campy:mention_id ?mention_id ;
                 campy:time_text ?time_text ;
                 campy:span_start ?span_start ;
                 campy:span_end ?span_end ;
                 campy:time_start ?time_start ;
                 campy:time_end ?time_end ;
                 campy:time_precision ?time_precision ;
                 campy:archived false ;
                 campy:created_at ?now ;
                 campy:source "rule:turn-dates" ;
                 campy:authority "earned" .
              ?m campy:HAS_TIME_MENTION ?t .
            }}
            WHERE {{
              ?m a campy:Message ; campy:message_id ?mid .
              BIND(IRI(CONCAT("{_NODE_BASE}", ENCODE_FOR_URI(STR(?mention_id)))) AS ?t)
              OPTIONAL {{ ?t campy:time_text ?ot }}
              OPTIONAL {{ ?t campy:span_start ?oa }}
              OPTIONAL {{ ?t campy:span_end ?ob }}
              OPTIONAL {{ ?t campy:time_start ?os }}
              OPTIONAL {{ ?t campy:time_end ?oe }}
              OPTIONAL {{ ?t campy:time_precision ?op }}
              OPTIONAL {{ ?t campy:archived ?oarch }}
              OPTIONAL {{ ?t campy:created_at ?ocr }}
            }}
            """,
    ),
    NamedQuery(
        name="turn_mentions.for_messages",
        cypher="""
        MATCH (m:Message)-[:HAS_TIME_MENTION]->(t:TimeMention)
        WHERE t.archived = false AND m.message_id IN $ms
        RETURN m.message_id AS m, t.mention_id AS mention_id, t.time_text AS time_text, t.span_start AS span_start,
               t.span_end AS span_end, t.time_start AS time_start, t.time_end AS time_end,
               t.time_precision AS time_precision
        ORDER BY m.message_id, t.span_start
        """,
        params=("ms",),
        mutating=False,
        description=("The resolved time expressions of the given Messages (instance URIs), in reading order: "
                     "what the bundle shows after each phrase"),
        sparql="""
            SELECT ?m ?mention_id ?time_text ?span_start ?span_end ?time_start ?time_end ?time_precision WHERE {
              VALUES ?m { }
              ?m campy:HAS_TIME_MENTION ?t .
              ?t a campy:TimeMention ; campy:mention_id ?mention_id ; campy:time_text ?time_text ;
                 campy:span_start ?span_start ; campy:span_end ?span_end ;
                 campy:time_start ?time_start ; campy:time_end ?time_end ;
                 campy:time_precision ?time_precision ; campy:archived false .
            }
            ORDER BY ?m ?span_start
            """,
    ),
    NamedQuery(
        name="turn_mentions.list_user_turns",
        cypher="""
        MATCH (m:Message) WHERE m.role = 'user' AND m.archived = false
        RETURN m.message_id AS message_id, m.text_raw AS text_raw,
               m.occurred_at AS occurred_at, m.created_at AS created_at
        """,
        params=(),
        mutating=False,
        description="Live user Messages with the date each was said (backfill candidates for TimeMention)",
        sparql="""
            SELECT ?message_id ?text_raw ?occurred_at ?created_at WHERE {
              ?m a campy:Message ; campy:message_id ?message_id ;
                 campy:text_raw ?text_raw ; campy:role "user" .
              OPTIONAL { ?m campy:occurred_at ?occurred_at }
              OPTIONAL { ?m campy:created_at ?created_at }
              FILTER NOT EXISTS { ?m campy:archived true }
            }
            """,
    ),
]
