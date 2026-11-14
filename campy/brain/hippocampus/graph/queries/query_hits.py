"""
campy/brain/hippocampus/graph/queries/query_hits.py -- step Q: the subject-anchored query whose hits are the measure.

Step Q of the e2e plan (learnings/e2e-improvement-plan.md) judges capture by "query hits": of the benchmark
questions, how many does a subject-anchored named query answer with rows whose EVIDENCED_BY turn is a gold turn.
These are those queries. No answering path calls them yet.

The question's words are resolved to existing Concepts only (a closed set, nothing is created), by exact label match
in SPARQL. Python only splits the question into terms (`question_terms`); it never selects, filters or joins rows.

Reads:
  query_hits.subject                 the question's subject: a speaker (SPOKEN_BY) or a mentioned PERSON Concept whose
  query_hits.subject_in_sessions     label is a term of the question; the earliest term wins, ties go to the longer
                                     label (the `_in_sessions` form keeps to the given Sessions)
  query_hits.objects                 the other Concepts named by a term (label or altLabel), not action kinds, that a
  query_hits.objects_in_sessions     turn MENTIONS or a fact's object reaches by INSTANCE_OF / BROADER*
  query_hits.facts                   the subject's live facts whose HAS_OBJECT is K, an instance of K, or narrower,
                                     each with its EVIDENCED_BY turn and date (oldest first), its predicate, quote,
                                     time phrase and the object's kinds (step 3 renders these)
  query_hits.facts_count             the same facts counted: distinct objects and distinct facts (graph count, folded in)
  query_hits.facts_latest            the newest of the same facts
  query_hits.facts_exist             whether any such fact exists (false is the answer "not recorded")

Edges read by the facts queries: HAS_SUBJECT (or the literal subject_id), HAS_OBJECT, EVIDENCED_BY, INSTANCE_OF,
BROADER. Resolution also reads SPOKEN_BY, MENTIONS, SENT_IN, text_raw and HAS_ALT_LABEL.
"""

from __future__ import annotations

import string

from campy.brain.hippocampus.graph.gateway import NamedQuery

_PUNCT = string.punctuation + "‘’“”"
_MAX_NGRAM = 3


def _words(question: str) -> list[str]:
    out = []
    for raw in question.split():
        w = raw.strip(_PUNCT)
        for tail in ("'s", "’s"):
            if w.endswith(tail):
                w = w[: -len(tail)]
        if w:
            out.append(w)
    return out


def question_terms(question: str) -> list[tuple[str, int]]:
    """The question's 1- to 3-word n-grams as (term, position of the first word), each as written, lower-cased and
    title-cased, plus the same with a final "s" dropped from the last word, so an exact label match in SPARQL finds
    "Melanie", "pottery" or "pet" (from "pets"). Labels are matched by the store's own index, not scanned."""
    words = _words(question)
    seen: dict[str, int] = {}
    for i in range(len(words)):
        for n in range(1, _MAX_NGRAM + 1):
            if i + n > len(words):
                break
            gram = words[i:i + n]
            forms = [gram]
            if len(gram[-1]) > 3 and gram[-1].lower().endswith("s") and not gram[-1].lower().endswith("ss"):
                forms.append(gram[:-1] + [gram[-1][:-1]])
            for f in forms:
                text = " ".join(f)
                for variant in (text, text.lower(), " ".join(x[:1].upper() + x[1:].lower() for x in f)):
                    seen.setdefault(variant, i)
    return list(seen.items())


_LIVE_FACT = """
              FILTER NOT EXISTS { ?o campy:archived true }
              FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?_newer }
"""

_IN_SESSIONS = """
                VALUES ?session { }
                ?m campy:SENT_IN ?session .
"""


def _subject_sparql(scoped: bool) -> str:
    scope = _IN_SESSIONS if scoped else ""
    return f"""
            SELECT ?sid ?label ?pos WHERE {{
              VALUES (?term ?pos) {{ }}
              ?c campy:text_raw ?term ; a campy:Concept ; campy:concept_id ?sid .
              FILTER NOT EXISTS {{ ?c campy:archived true }}
              FILTER EXISTS {{
                {scope}
                {{ ?m campy:SPOKEN_BY ?c }} UNION {{ ?m campy:MENTIONS ?c . ?c campy:ner_label "PERSON" }}
              }}
              BIND(?term AS ?label)
            }}
            ORDER BY ?pos DESC(STRLEN(?label)) ?sid
            LIMIT 1
            """


def _objects_sparql(scoped: bool) -> str:
    scope = _IN_SESSIONS if scoped else ""
    return f"""
            SELECT DISTINCT ?kid WHERE {{
              VALUES ?term {{ }}
              {{ ?k campy:text_raw ?term }} UNION {{ ?k campy:HAS_ALT_LABEL ?_l . ?_l campy:text ?term }}
              ?k a campy:Concept ; campy:concept_id ?kid .
              FILTER(?kid != ?sid && STRLEN(?term) > 2)
              FILTER NOT EXISTS {{ ?k campy:kind_scheme "action" }}
              FILTER NOT EXISTS {{ ?k campy:archived true }}
              FILTER EXISTS {{
                {scope}
                {{ ?m campy:MENTIONS ?k }}
                UNION
                {{ ?_o campy:EVIDENCED_BY ?m ; campy:HAS_OBJECT ?_x . ?_x (campy:INSTANCE_OF|campy:BROADER)* ?k }}
              }}
            }}
            ORDER BY ?kid
            """


# The subject's live facts whose object ?x is K, an instance of K, or an instance of a kind narrower than K.
_FACTS_BODY = """
              VALUES ?kid { }
              ?k a campy:Concept ; campy:concept_id ?kid .
              ?x (campy:INSTANCE_OF|campy:BROADER)* ?k .
              ?o campy:HAS_OBJECT ?x ; a campy:Observation ; campy:observation_id ?observation_id ;
                 campy:EVIDENCED_BY ?message .
              { ?o campy:HAS_SUBJECT ?_s . ?_s campy:concept_id ?sid } UNION { ?o campy:subject_id ?sid }
              ?message campy:message_id ?evidence_message_id .
              OPTIONAL { ?message campy:occurred_at ?occurred_at }
""" + _LIVE_FACT

_FACTS_CYPHER = ("MATCH (o:Observation {subject_id: $sid})-[:HAS_OBJECT]->(x)-[:INSTANCE_OF|BROADER*0..]->"
                 "(k:Concept) WHERE k.concept_id IN $kids AND o.archived = false "
                 "MATCH (o)-[:EVIDENCED_BY]->(m:Message) ")

QUERY_HIT_QUERIES = [
    NamedQuery(
        name="query_hits.subject",
        cypher=("MATCH (m:Message)-[:SPOKEN_BY|MENTIONS]->(c:Concept) WHERE c.text_raw IN $pairs "
                "RETURN c.concept_id AS sid LIMIT 1"),
        params=("pairs",),
        mutating=False,
        description=("The question's subject Concept: a speaker or a mentioned PERSON whose label is one of the "
                     "(term, position) pairs; the earliest position wins, then the longer label. Empty: unresolved"),
        sparql=_subject_sparql(scoped=False),
    ),
    NamedQuery(
        name="query_hits.subject_in_sessions",
        cypher=("MATCH (m:Message)-[:SENT_IN]->(s:Session), (m)-[:SPOKEN_BY|MENTIONS]->(c:Concept) "
                "WHERE s IN $sessions AND c.text_raw IN $pairs RETURN c.concept_id AS sid LIMIT 1"),
        params=("pairs", "sessions"),
        mutating=False,
        description="query_hits.subject kept to the turns SENT_IN the given Session IRIs",
        sparql=_subject_sparql(scoped=True),
    ),
    NamedQuery(
        name="query_hits.objects",
        cypher=("MATCH (k:Concept) WHERE k.text_raw IN $terms AND k.concept_id <> $sid "
                "RETURN DISTINCT k.concept_id AS kid"),
        params=("terms", "sid"),
        mutating=False,
        description=("The Concepts other than the subject that the question's terms name (label or altLabel), not "
                     "action kinds, that a turn MENTIONS or a fact's object reaches by INSTANCE_OF / BROADER*"),
        sparql=_objects_sparql(scoped=False),
    ),
    NamedQuery(
        name="query_hits.objects_in_sessions",
        cypher=("MATCH (m:Message)-[:SENT_IN]->(s:Session), (m)-[:MENTIONS]->(k:Concept) "
                "WHERE s IN $sessions AND k.text_raw IN $terms AND k.concept_id <> $sid "
                "RETURN DISTINCT k.concept_id AS kid"),
        params=("terms", "sid", "sessions"),
        mutating=False,
        description="query_hits.objects kept to the turns SENT_IN the given Session IRIs",
        sparql=_objects_sparql(scoped=True),
    ),
    NamedQuery(
        name="query_hits.facts",
        cypher=_FACTS_CYPHER + ("RETURN DISTINCT o.observation_id AS observation_id, x.concept_id AS object_id, "
                                "m.message_id AS evidence_message_id"),
        params=("sid", "kids"),
        mutating=False,
        description=("The subject's live facts whose HAS_OBJECT is one of the Concepts K, an instance of K or of a "
                     "kind BROADER* below K, each with its EVIDENCED_BY turn and date, oldest first. Empty is "
                     "'not recorded'"),
        sparql=f"""
            SELECT ?observation_id ?object_id ?object_text ?message ?evidence_message_id ?occurred_at
                   ?predicate ?quote ?time_text (GROUP_CONCAT(DISTINCT ?kind_label; separator="|") AS ?kinds)
            WHERE {{
              {_FACTS_BODY}
              OPTIONAL {{ ?x campy:concept_id ?object_id }}
              OPTIONAL {{ ?x campy:text_raw ?object_text }}
              OPTIONAL {{ ?o campy:predicate ?predicate }}
              OPTIONAL {{ ?o campy:evidence_text ?quote }}
              OPTIONAL {{ ?o campy:time_text ?time_text }}
              OPTIONAL {{ ?x campy:INSTANCE_OF ?_kind . ?_kind campy:text_raw ?kind_label }}
            }}
            GROUP BY ?observation_id ?object_id ?object_text ?message ?evidence_message_id ?occurred_at
                     ?predicate ?quote ?time_text
            ORDER BY ?occurred_at ?observation_id ?evidence_message_id
            """,
    ),
    NamedQuery(
        name="query_hits.facts_count",
        cypher=_FACTS_CYPHER + "RETURN count(DISTINCT x) AS objects, count(DISTINCT o) AS facts",
        params=("sid", "kids"),
        mutating=False,
        description="How many distinct objects and distinct live facts query_hits.facts finds for the subject",
        sparql=f"""
            SELECT (COUNT(DISTINCT ?x) AS ?objects) (COUNT(DISTINCT ?o) AS ?facts) WHERE {{
              {_FACTS_BODY}
            }}
            """,
    ),
    NamedQuery(
        name="query_hits.facts_latest",
        cypher=_FACTS_CYPHER + ("RETURN o.observation_id AS observation_id, m.message_id AS evidence_message_id "
                                "ORDER BY m.occurred_at DESC LIMIT 1"),
        params=("sid", "kids"),
        mutating=False,
        description="The newest of query_hits.facts' rows (by its turn's date), with its object and turn",
        sparql=f"""
            SELECT ?observation_id ?object_id ?object_text ?message ?evidence_message_id ?occurred_at ?predicate
                   ?quote ?time_text (GROUP_CONCAT(DISTINCT ?kind_label; separator="|") AS ?kinds) WHERE {{
              {_FACTS_BODY}
              OPTIONAL {{ ?x campy:concept_id ?object_id }}
              OPTIONAL {{ ?x campy:text_raw ?object_text }}
              OPTIONAL {{ ?o campy:predicate ?predicate }}
              OPTIONAL {{ ?o campy:evidence_text ?quote }}
              OPTIONAL {{ ?o campy:time_text ?time_text }}
              OPTIONAL {{ ?x campy:INSTANCE_OF ?_kind . ?_kind campy:text_raw ?kind_label }}
            }}
            GROUP BY ?observation_id ?object_id ?object_text ?message ?evidence_message_id ?occurred_at
                     ?predicate ?quote ?time_text
            ORDER BY DESC(?occurred_at) DESC(?observation_id)
            LIMIT 1
            """,
    ),
    NamedQuery(
        name="query_hits.facts_exist",
        cypher=_FACTS_CYPHER + "RETURN count(o) > 0 AS exists",
        params=("sid", "kids"),
        mutating=False,
        description="Whether the subject has any live fact query_hits.facts would return (false: 'not recorded')",
        sparql=f"""
            SELECT ((COUNT(?o) > 0) AS ?exists) WHERE {{
              {_FACTS_BODY}
            }}
            """,
    ),
]
