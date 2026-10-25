"""B524: count and list questions answered by a graph query anchored on the subject.

"How many pets does Andrew have?" is not answered by counting every pet in the store (B505 did, and
said 11). It is a question about one subject, one relation and one kind of object, and the graph holds
all three: the speaker Concept (`HAS_SUBJECT`), an `owns` Observation, and the object Concept
(`HAS_OBJECT`) that is `INSTANCE_OF` the kind (B522, B523). The answer is two named queries over those
edges (`observations.count_objects_of_subject`, `observations.objects_of_subject_kind`); this module
only decides WHETHER and WITH WHAT the question calls them, and formats the rows.

Wording routes, it never answers (campy-graph rule 4). Three things are resolved from the question, all
against what the graph already holds, nothing is ever created:

  * the FORM: a small documented set of count/list shapes (`COUNT_FORMS`). A question for a time or a
    quantity of time (`TIME_QUESTIONS`: when, which year, how long, how many months ...) declines;
  * the SUBJECT: the one non-kind Concept the question names (`concept_links.candidate_spans` then
    `extract.find_existing_concept`, the closed-set lookup the bundle compiler uses). Zero or several
    (two speakers named) decline;
  * the KIND: the one kind Concept whose label or altLabel the question names (`kinds.load_kinds`,
    plural folded by `concept_links.norm_key`). The query then follows `INSTANCE_OF` and `BROADER*`;
  * the RELATION: a verb in the question mapped to a predicate of the closed set (`RELATION_BY_VERB`).
    A verb not in the map is not guessed, and
    have/has/had count only as the main verb (an auxiliary, "which cities has Jon visited", does not).

Any one missing means no section and the normal pipeline answers. An "as of <date>" or "by <date>" in the
question bounds the evidence turns' dates (parsed by `timeparse.normalize_time`); a time phrase that does
not parse declines rather than answering a different question.

Python formats the query's rows. It does not count, dedupe or filter them. Behind `[retrieval]
graph_count` (env `CAMPY_GRAPH_COUNT`, default off).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_logger = logging.getLogger(__name__)

SECTION_TYPE = "graph_count"

# The question shapes that ROUTE a question here. Routing only: nothing below reads these to decide an answer.
COUNT_FORMS: dict[str, str] = {
    "how many": r"\bhow many\b",
    "how much": r"\bhow much\b",
    "number of": r"\bnumber of\b",
    "list": r"\blist\b",
    "what-does-have": r"^\s*(?:what|which)\b.*\b(?:does|do|did|has|have|had|will)\b",
}

# Verb -> predicate of the closed set (observations.PREDICATES). A verb not listed here is unmapped:
# no section, the normal pipeline answers.
RELATION_BY_VERB: dict[str, str] = {
    "have": "owns", "has": "owns", "had": "owns", "having": "owns",
    "own": "owns", "owns": "owns", "owned": "owns", "owning": "owns",
    "adopt": "owns", "adopts": "owns", "adopted": "owns", "adopting": "owns",
    "get": "owns", "gets": "owns", "got": "owns", "getting": "owns",
    "keep": "owns", "keeps": "owns", "kept": "owns", "keeping": "owns",
}

# Questions that ask WHEN or HOW LONG (a time, or a quantity of time) are not counts of things, whatever
# verb they carry ("Which year did X adopt ...", "How many months passed ..."): they decline here.
TIME_QUESTIONS = (
    r"\bwhen\b|\b(?:what|which)\s+(?:year|month|date|day|week|time)\b|\bhow long\b|\bhow often\b"
    r"|\bhow many\s+(?:days?|weeks?|months?|years?|times?|hours?|minutes?|seconds?)\b|\bhow much time\b"
)
# "have/has/had" is the possession verb only as the MAIN verb; as an auxiliary ("which cities has Jon
# visited", "what books have the kids read") the parser tags it aux and it maps to nothing.
_AUXILIARY_DEPS = frozenset({"aux", "auxpass"})
_HAVE_FORMS = frozenset({"have", "has", "had", "having"})

_AS_OF_RE = re.compile(r"\b(?:as of|by)\s+(?!the end of\b)([^?!]*?)\s*[?.!]*\s*$", re.IGNORECASE)
_QUOTE_CHARS = 120


def graph_count_enabled(config: dict | None) -> bool:
    """`[retrieval] graph_count` (default false; env `CAMPY_GRAPH_COUNT=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("graph_count", False))


@dataclass(frozen=True)
class Route:
    form: str
    predicate: str
    before: Optional[datetime] = None     # exclusive upper bound on the evidence turn's date
    as_of_text: Optional[str] = None


@dataclass(frozen=True)
class Resolved:
    subject_id: str
    subject_label: str
    kind_id: str
    kind_label: str


_NLP = None


def _default_nlp():
    global _NLP
    if _NLP is None:
        try:
            from campy.brain.temporal_lobe.loop.step1_ner import get_nlp
            _NLP = get_nlp()
        except Exception:
            _logger.debug("spaCy model unavailable; 'have' cannot be told from an auxiliary", exc_info=True)
            _NLP = False
    return _NLP or None


def _mapped_predicates(question: str, nlp) -> set[str]:
    """Predicates of the closed set the question's verbs map to. `have` forms count only as a main verb
    (not tagged aux by the parser); with no parser they do not count."""
    if nlp is None:
        return {RELATION_BY_VERB[w] for w in re.findall(r"[a-z]+", question)
                if w in RELATION_BY_VERB and w not in _HAVE_FORMS}
    return {RELATION_BY_VERB[t.text.lower()] for t in nlp(question)
            if t.text.lower() in RELATION_BY_VERB and not _is_auxiliary_have(t)}


def _is_auxiliary_have(token) -> bool:
    """A have-form the parser tags aux, or that governs a past participle of another verb ("what songs
    have the band recorded": the parser can take `have` for the root). A participle that is itself a mapped
    verb ("has Audrey got") leaves it a main verb: the mapped verb answers the relation either way."""
    if token.text.lower() not in _HAVE_FORMS:
        return False
    if token.dep_ in _AUXILIARY_DEPS:
        return True
    return any(c.tag_ == "VBN" and c.text.lower() not in RELATION_BY_VERB for c in token.children)


def route_question(question: str, nlp=None) -> Optional[Route]:
    """The form, relation and time bound the question carries, or None when it is not a count/list
    question, asks for a time or a quantity of time, names no mapped verb (a `have` that is an
    auxiliary does not count), or carries a time phrase that does not parse. `nlp`: a spaCy pipeline
    (default: the NER step's)."""
    q = " ".join(str(question or "").lower().replace("\u2019", "'").split())
    if not q or re.search(TIME_QUESTIONS, q):
        return None
    form = next((name for name, pattern in COUNT_FORMS.items() if re.search(pattern, q)), None)
    if form is None:
        return None
    predicates = _mapped_predicates(" ".join(str(question).split()), nlp or _default_nlp())
    if len(predicates) != 1:
        return None
    before = None
    as_of_text = None
    m = _AS_OF_RE.search(q)
    if m:
        from campy.brain.temporal_lobe.observations.timeparse import normalize_time

        as_of_text = m.group(1).strip()
        resolved = normalize_time(as_of_text, None)
        if resolved is None:
            return None
        before = resolved.end + timedelta(days=1)
    return Route(form=form, predicate=next(iter(predicates)), before=before, as_of_text=as_of_text)


async def resolve_question(gw, question: str) -> Optional[Resolved]:
    """The subject Concept and the kind Concept the question names, from the graph's closed set. None when
    either is missing or ambiguous. Never creates a Concept."""
    from campy.brain.hippocampus.concept_links import candidate_spans, norm_key
    from campy.brain.hippocampus.kinds import load_kinds
    from campy.brain.temporal_lobe.observations.extract import find_existing_concept

    kinds = await load_kinds(gw)
    if not kinds:
        return None
    by_key: dict[str, set[str]] = {}
    for k in kinds.values():
        for key in k.keys():
            by_key.setdefault(key, set()).add(k.concept_id)

    text = re.sub(r"(?:'s|’s)\b", "", str(question or ""))
    spans = candidate_spans(text)
    kind_ids: list[str] = []
    for span in spans:
        for cid in by_key.get(norm_key(span), ()):
            if cid not in kind_ids:
                kind_ids.append(cid)
    if len(kind_ids) != 1:
        return None

    subject_ids: list[str] = []
    subject_label = ""
    for span in spans[:40]:
        if norm_key(span) in by_key:
            continue
        cid = await find_existing_concept(gw, span)
        if cid and cid not in kinds and cid not in subject_ids:
            subject_ids.append(cid)
            subject_label = span
    if len(subject_ids) != 1:
        return None

    return Resolved(subject_id=subject_ids[0], subject_label=subject_label, kind_id=kind_ids[0],
                    kind_label=kinds[kind_ids[0]].pref)


def _day(value) -> str:
    return str(value)[:10] if value else ""


def _item(r: dict) -> str:
    quote = " ".join(str(r.get("quote") or "").split())[:_QUOTE_CHARS]
    cite = f"{_day(r.get('occurred_at'))}, {r.get('evidence_message_id')}"
    return f'- {r.get("object_label")} ({cite}' + (f', "{quote}"' if quote else "") + ")"


def render_graph_count(resolved: Resolved, route: Route, count: int, rows: list[dict],
                       unkinded: list[dict] | None = None) -> str:
    """The section text: the query's count for the asked kind, its rows (object, date, source turn,
    quote), then, separately, the subject's other recorded objects with no kind recorded."""
    pred = route.predicate.replace("_", " ")
    bound = f", evidence dated before {_day(route.before)}" if route.before else ""
    lines = [f"[graph count] {resolved.subject_label} {pred} {count} of kind {resolved.kind_label}"
             f" (counted in the graph over {resolved.subject_label}'s recorded {pred} claims{bound}):"]
    lines += [_item(r) for r in rows]
    if unkinded:
        lines.append(f"Also recorded as {pred}, kind not recorded (not in the count above):")
        lines += [_item(r) for r in unkinded]
    return "\n".join(lines)


async def build_graph_count_section(db, query: str, config: dict):
    """The `graph_count` BundleSection for a count/list question, or None (flag off, question not routed,
    subject/kind unresolved, nothing recorded, or any failure). The normal pipeline then answers."""
    if not graph_count_enabled(config):
        return None
    route = route_question(query)
    if route is None:
        return None
    try:
        from campy.brain.hippocampus.graph.gateway import get_gateway
        from campy.brain.thalamus.bundle_compiler import BundleSection

        gw = get_gateway(db)
        resolved = await resolve_question(gw, query)
        if resolved is None:
            return None
        params = dict(sid=resolved.subject_id, kind_id=resolved.kind_id, predicate=route.predicate,
                      before=route.before.isoformat() if route.before else None)
        counted = await gw.run("observations.count_objects_of_subject", **params)
        count = int((counted[0].get("n") if counted else 0) or 0)
        if count <= 0:
            return None
        rows = await gw.run("observations.objects_of_subject_kind", **params)
        unkinded = await gw.run("observations.objects_of_subject_no_kind",
                                **{k: v for k, v in params.items() if k != "kind_id"})
        text = render_graph_count(resolved, route, count, rows, unkinded)
        return BundleSection(
            section_type=SECTION_TYPE,
            content=[{"text": text, "type": "GraphCount", "confidence": 0.9, "pathway_strength": 0.9}],
            source_node_ids=[str(r.get("observation_id")) for r in [*rows, *unkinded] if r.get("observation_id")],
            token_estimate=max(1, len(text) // 4),
        )
    except Exception as e:
        _logger.warning("Error in build_graph_count_section: %s", e)
        return None
