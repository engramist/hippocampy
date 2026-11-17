"""
campy/brain/hippocampus/graph/queries/fact_sentences.py -- the read behind rule-rendered fact sentences.

Behind `[retrieval] fact_sentences` (env `CAMPY_FACT_SENTENCES`, default off, in no profile). Reads only; nothing is
written. One construction: the subject's live facts whose object is an exact-label hit (the `query_hits` anchor), each
with its roles, grouped by the query into one row per (predicate, polarity, object kind):

  fact_sentences.rows       the groups over the facts whose EVIDENCED_BY turn is one of the SHOWN messages (the join is
                            the `VALUES ?shown_message` block). A group of 1 is a single fact; 2..LIST_CAP members is a
                            list; more than LIST_CAP members yields no row, so those facts are never rendered at all.
                            A fact with no object kind is its own group (kindless free text is never merged).
  fact_sentences.rows_all   the same grouping over ALL matched facts, a group kept when at least one member has a shown
                            source turn (for the offline measurement of the all-matched form only; never used by the
                            bundle compiler)

Edges read: HAS_SUBJECT (or the literal subject_id), HAS_OBJECT, INSTANCE_OF, BROADER, EVIDENCED_BY, HAS_PLACE,
HAS_PARTICIPANT; literals predicate, polarity, object_text, time_text, time_start, time_end, time_precision, observed_at,
group_subject; Message message_id and occurred_at. Live: not archived, no DEPRECATED_BY.

Each row: predicate, polarity, gn (members), attach_key (the newest shown member's "<turn date>|<Message IRI>|<message id>")
and members: one token per fact, fields joined by FIELD_SEP, tokens by TOKEN_SEP, oldest turn first (an ordered
sub-select feeds the GROUP_CONCAT). Rows come newest attach turn first.

List params are filled into empty `VALUES ?x { }` blocks by the list param named x + "s": `sids` (one subject id),
`kids`, `shown_messages`, `shown_observations`. Each is used once in the text (the binder fills a name only once).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

FIELD_SEP = "\x1f"
TOKEN_SEP = "\x1e"
LIST_CAP = 6          # more members than this: the group is not rendered at all

FIELDS = ("oid", "text", "time_text", "time_start", "time_end", "time_precision", "observed_at", "place",
          "partners", "group_subject", "as_observation", "key")


def _query(shown_only: bool) -> str:
    shown = ("?o campy:EVIDENCED_BY ?shown_message . VALUES ?shown_message { }" if shown_only else
             "OPTIONAL { ?o campy:EVIDENCED_BY ?shown_message . VALUES ?shown_message { } }")
    sep = FIELD_SEP
    return f"""
        SELECT ?predicate ?polarity ?gk (COUNT(DISTINCT ?o) AS ?gn) (MAX(?src_key) AS ?attach_key)
               (GROUP_CONCAT(?tok; separator="{TOKEN_SEP}") AS ?members)
        WHERE {{
          {{ SELECT ?o ?predicate ?polarity ?gk ?src_key ?tok WHERE {{
              {{ SELECT ?o ?oid ?predicate
                        (MIN(COALESCE(?_pol, "asserted")) AS ?polarity)
                        (MIN(?_kind_label) AS ?kind)
                        (MIN(?_key) AS ?src_key)
                        (MIN(?_otext) AS ?otext) (MIN(?_olabel) AS ?olabel)
                        (MIN(?_time_text) AS ?time_text) (MIN(?_ts) AS ?ts) (MIN(?_te) AS ?te)
                        (MIN(?_tp) AS ?tp) (MIN(?_obs_at) AS ?obs_at) (MIN(?_place) AS ?place)
                        (GROUP_CONCAT(DISTINCT ?_partner; separator="|") AS ?partners)
                        (MIN(?_grp) AS ?grp) (COUNT(?_dup) AS ?dups)
                 WHERE {{
                   VALUES ?sid {{ }}
                   {{ VALUES ?kid {{ }} ?k a campy:Concept ; campy:concept_id ?kid .
                      ?x (campy:INSTANCE_OF|campy:BROADER)* ?k . ?o campy:HAS_OBJECT ?x . }}
                   ?o a campy:Observation ; campy:observation_id ?oid ; campy:predicate ?predicate .
                   {{ ?o campy:HAS_SUBJECT ?_s . ?_s campy:concept_id ?sid }} UNION {{ ?o campy:subject_id ?sid }}
                   FILTER NOT EXISTS {{ ?o campy:archived true }}
                   FILTER NOT EXISTS {{ ?o campy:DEPRECATED_BY ?_newer }}
                   {shown}
                   OPTIONAL {{ ?shown_message campy:message_id ?_mid }}
                   OPTIONAL {{ ?shown_message campy:occurred_at ?_at }}
                   BIND(IF(BOUND(?shown_message), CONCAT(COALESCE(STR(?_at), ""), "|", STR(?shown_message), "|",
                                                         COALESCE(STR(?_mid), "")), ?unbound) AS ?_key)
                   OPTIONAL {{ ?o campy:polarity ?_pol }}
                   OPTIONAL {{ ?x campy:text_raw ?_olabel }}
                   OPTIONAL {{ ?x campy:INSTANCE_OF ?_kk . ?_kk campy:text_raw ?_kind_label }}
                   OPTIONAL {{ ?o campy:object_text ?_otext }}
                   OPTIONAL {{ ?o campy:time_text ?_time_text }}
                   OPTIONAL {{ ?o campy:time_start ?_ts }}
                   OPTIONAL {{ ?o campy:time_end ?_te }}
                   OPTIONAL {{ ?o campy:time_precision ?_tp }}
                   OPTIONAL {{ ?o campy:observed_at ?_obs_at }}
                   OPTIONAL {{ ?o campy:HAS_PLACE ?_pl . ?_pl campy:text_raw ?_place }}
                   OPTIONAL {{ ?o campy:HAS_PARTICIPANT ?_pp . ?_pp campy:text_raw ?_partner }}
                   OPTIONAL {{ ?o campy:group_subject ?_grp }}
                   OPTIONAL {{ VALUES ?shown_observation {{ }} FILTER(?shown_observation = ?oid) BIND(1 AS ?_dup) }}
                 }}
                 GROUP BY ?o ?oid ?predicate
              }}
              BIND(IF(BOUND(?kind), ?kind, CONCAT("~", ?oid)) AS ?gk)
              BIND(CONCAT(STR(?oid), "{sep}", COALESCE(?otext, ?olabel, ""), "{sep}", COALESCE(?time_text, ""), "{sep}",
                          COALESCE(STR(?ts), ""), "{sep}", COALESCE(STR(?te), ""), "{sep}", COALESCE(?tp, ""), "{sep}",
                          COALESCE(STR(?obs_at), ""), "{sep}", COALESCE(?place, ""), "{sep}", COALESCE(?partners, ""),
                          "{sep}", IF(BOUND(?grp), "1", ""), "{sep}", IF(?dups > 0, "1", ""), "{sep}",
                          COALESCE(?src_key, "")) AS ?tok)
            }} ORDER BY ?predicate ?polarity ?gk ?src_key ?oid
          }}
        }}
        GROUP BY ?predicate ?polarity ?gk
        HAVING (COUNT(DISTINCT ?o) <= {LIST_CAP} && COUNT(?src_key) > 0)
        ORDER BY DESC(?attach_key) ?predicate ?gk
        """


_CYPHER = ("MATCH (o:Observation {subject_id: $sid})-[:HAS_OBJECT]->(x)-[:INSTANCE_OF|BROADER*0..]->(k:Concept) "
           "WHERE k.concept_id IN $kids AND o.archived = false "
           "MATCH (o)-[:EVIDENCED_BY]->(m:Message) RETURN o.observation_id AS observation_id")

FACT_SENTENCE_QUERIES = [
    NamedQuery(
        name="fact_sentences.rows",
        cypher=_CYPHER,
        params=("sids", "kids", "shown_messages", "shown_observations"),
        mutating=False,
        description=("The subject's live exact-label-object facts whose EVIDENCED_BY turn is one of the shown "
                     "messages, grouped by predicate, polarity and object kind; one row per group of at most "
                     f"{LIST_CAP} facts, each with its roles and its source turn (fact sentences)"),
        sparql=_query(shown_only=True),
    ),
    NamedQuery(
        name="fact_sentences.rows_all",
        cypher=_CYPHER,
        params=("sids", "kids", "shown_messages", "shown_observations"),
        mutating=False,
        description=("fact_sentences.rows with the grouping over ALL matched live facts (a group is kept when a "
                     "member has a shown source turn); the offline measurement of the all-matched list form only"),
        sparql=_query(shown_only=False),
    ),
]
