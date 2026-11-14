"""
B564 form 2: the roles of an event fact, by closed choice (flag `[observations] roles`, env
`CAMPY_OBSERVATION_ROLES`, default off).

The fact prompt is untouched: with the flag on, the extraction call is the flag-off call. After ALL of a turn's
facts are written (so its MENTIONS and admitted entities are in the graph), the rule builds a closed candidate set
for each did / plans fact, and ONE extra call per turn shows the model each fact's quote with numbered partner and
place options. The model answers with option numbers only (0 = none). The rule accepts only a number that was shown for that
fact and that role; anything else is a counted rejection and writes nothing. The model never writes a name, a span,
a synset or an id (P3). The only writer of the edges, through the NamedQueries in `graph/queries/roles.py`.

Options (every one from the graph or from WordNet, never from the model):
  action   (option B, user ruling 2026-11-13; no model, no sense) ONE word by rule from the fact's `object_text`,
           kept when its lemma occurs in the quote (`action_word`): a noun root with an event sense is its lemma; a
           verb root is its event nominalisation ("adopt" -> adoption), else its own lemma; a light-verb root takes
           the first of its objects that has an event sense ("go to a council meeting" -> meeting). Written as the
           action Concept `action:<word>` (kind_scheme "action", no embedding, no BROADER, one node per word) and
           HAS_ACTION. The only word knowledge is the light-verb list and the event.n.01 test.
  with     the other speakers of the session (`roles.session_speakers`, SPOKEN_BY) and the Concepts the source turn
           MENTIONS with ner_label PERSON / ORG / NORP (`roles.turn_entity_options`), other than the fact's subject.
  place    the Concepts the turn MENTIONS with ner_label GPE / LOC / FAC.

Fallback (no model), only when the model answered 0 or there were no options (or the call failed): a dependency
parse inside the clause of the quote. An object of "with" whose head is under person.n.01 / social_group.n.01 gives
HAS_PARTICIPANT to an ObjectPhrase; an object of "to" / "at" / "in" whose head is under the place roots gives
HAS_PLACE to an ObjectPhrase. A fallback after a failed call is counted under its own reasons.

Every outcome is counted by reason (`RolesStats.counts`, summed into `ObservationWorkerStats.roles`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import evidence_entities as evid
from campy.brain.temporal_lobe.observations import typed_objects as T

_logger = logging.getLogger(__name__)

RULE_VERSION = "b564-3"
_PHRASE_NS = uuid.UUID("b5640000-0000-0000-0000-000000000000")
EVENT_PREDICATES = frozenset({"did", "plans"})
PARTNER_LABELS = frozenset({"PERSON", "ORG", "NORP"})
MAX_WITH = 4
ROLES_CALL_MAX_TOKENS = 256          # a few option numbers per fact, up to MAX_PER_TURN facts
PLACE_PREPS = frozenset({"to", "at", "in"})

_PROMPT = (
    "Pick from the numbered options only; never write a name. Answer 0 when no option fits.\n"
    'Message: """{text}"""\n{facts}\n'
    'Reply with JSON only, one object per fact: [{{"fact": 1, "with": [1], "place": 0}}]\n'
    '"place" is one option number. "with" is a list of option numbers. 0 or [] means none. '
    "Leave out a role that shows no options."
)


# --- the closed candidate sets ---------------------------------------------------------------

@dataclass
class FactIn:
    oid: str
    quote: str
    predicate: str
    object_text: str
    subject_id: str | None
    subject_text: str = ""


@dataclass
class Opt:
    cid: str
    label: str


@dataclass
class Options:
    fact: FactIn
    action: list[wn_mod.ActionOption] = field(default_factory=list)
    partner: list[Opt] = field(default_factory=list)
    place: list[Opt] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.action or self.partner or self.place)


def _lemmas(doc) -> set[str]:
    return {t.lemma_.lower() for t in doc if t.lemma_.isalpha()}


def action_heads(doc) -> list[str]:
    """The head lemmas of an object phrase: its root's lemma, or, when the root is a light verb or not a verb / noun,
    the lemmas of its nouns and of its other non-light verbs in order ("go on a hike" gives hike, "go camping" gives
    camp: spaCy tags the gerund a verb; the spec says nouns, this is the one extension)."""
    root = next((t for t in doc if t.dep_ == "ROOT"), None)
    if root is not None and root.pos_ in ("VERB", "NOUN") and root.lemma_.isalpha() \
            and root.lemma_.lower() not in wn_mod.LIGHT_VERBS:
        return [root.lemma_.lower()]
    return [t.lemma_.lower() for t in doc if t is not root and t.lemma_.isalpha()
            and (t.pos_ in ("NOUN", "PROPN")
                 or (t.pos_ == "VERB" and t.lemma_.lower() not in wn_mod.LIGHT_VERBS))]


_OBJECT_DEPS = frozenset({"dobj", "pobj", "attr", "oprd"})


def _word_of(tok) -> str | None:
    """The action word a head token names: a noun with an event sense is its own lemma; a verb is its event
    nominalisation, else its own lemma; anything else names none."""
    lemma = tok.lemma_.lower()
    if tok.pos_ in ("NOUN", "PROPN"):
        return lemma if wn_mod.has_event_sense(lemma) else None
    if tok.pos_ == "VERB" and lemma not in wn_mod.LIGHT_VERBS:
        return wn_mod.event_nominalisation(lemma) or lemma
    return None


def action_word(nlp, fact: FactIn, counts: Counter) -> str | None:
    """Option B (user ruling 2026-11-13): the ONE word that names what happened in an event fact, by rule; the model
    is not asked and no sense is chosen. From the fact's `object_text`, kept only when its lemma occurs in the quote:
      * root a noun (not light): its lemma, when it has a sense under event.n.01;
      * root a verb (not light): its event nominalisation ("adopt" -> adoption), else the verb's own lemma;
      * root a light verb, or neither: the first noun among the root's objects (direct or prepositional) with an
        event sense ("go to a council meeting for adoption" -> meeting); else the first other head that names one.
    Counted by reason: action_no_head, action_head_not_in_quote, action_no_event_word; a second qualifying word
    is dropped (first wins) and counted as action_second_word_dropped."""
    doc = nlp(fact.object_text or "")
    root = next((t for t in doc if t.dep_ == "ROOT"), None)
    in_quote = _lemmas(nlp(fact.quote))
    if root is not None and root.pos_ in ("VERB", "NOUN") and root.lemma_.isalpha() \
            and root.lemma_.lower() not in wn_mod.LIGHT_VERBS:
        heads = [root]
    else:
        ri = root.i if root is not None else -1          # spaCy makes a new Token per access: compare by index
        objects = [t for t in doc if t.i != ri and t.pos_ in ("NOUN", "PROPN") and t.dep_ in _OBJECT_DEPS
                   and (t.head.i == ri or t.head.head.i == ri)]
        taken = {t.i for t in objects}
        others = [t for t in doc if t.i != ri and t.i not in taken and t.lemma_.isalpha()
                  and (t.pos_ in ("NOUN", "PROPN") or (t.pos_ == "VERB" and t.lemma_.lower() not in wn_mod.LIGHT_VERBS))]
        heads = objects + others
    if not heads:
        counts["action_no_head"] += 1
        return None
    heads = [t for t in heads if t.lemma_.lower() in in_quote]
    if not heads:
        counts["action_head_not_in_quote"] += 1
        return None
    words = list(dict.fromkeys(w for w in (_word_of(t) for t in heads) if w))
    if not words:
        counts["action_no_event_word"] += 1
        return None
    if len(words) > 1:
        counts["action_second_word_dropped"] += 1
    return words[0]


def action_concept_id(word: str) -> str:
    """One action Concept per word, shared by every fact that names it."""
    return "action:" + word.lower().replace(" ", "_")


def action_options_for(nlp, fact: FactIn, counts: Counter) -> list[wn_mod.ActionOption]:
    """The action options of one fact, or [] with the reason counted."""
    heads = action_heads(nlp(fact.object_text or ""))
    if not heads:
        counts["action_no_head"] += 1
        return []
    in_quote = _lemmas(nlp(fact.quote))
    heads = [h for h in dict.fromkeys(heads) if h in in_quote]
    if not heads:
        counts["action_head_not_in_quote"] += 1
        return []
    out: list[wn_mod.ActionOption] = []
    seen: set[str] = set()
    for h in heads:
        for o in wn_mod.action_options(h):
            if o.synset not in seen:
                seen.add(o.synset)
                out.append(o)
    out = out[:wn_mod.MAX_ACTION_OPTIONS]
    if not out:
        counts["action_no_event_sense"] += 1
    return out


def _dedupe(opts: list[Opt]) -> list[Opt]:
    seen: set[str] = set()
    out = []
    for o in opts:
        if o.cid not in seen:
            seen.add(o.cid)
            out.append(o)
    return out


async def build_options(gw: Any, nlp, message_id: str, facts: list[FactIn], counts: Counter) -> list[Options]:
    """The candidate sets of every fact with a subject. Partner and place options come from NamedQueries anchored on
    the turn's message id (SPARQL filters by label and excludes the subject); the two reads are cached by subject."""
    entities: dict[str, list[dict]] = {}
    speakers: dict[str, list[dict]] = {}
    out: list[Options] = []
    for f in facts:
        if not f.subject_id:
            counts["no_subject"] += 1
            continue
        sid = f.subject_id
        if sid not in entities:
            entities[sid] = list(await gw.run("roles.turn_entity_options", mid=message_id, sid=sid))
            speakers[sid] = list(await gw.run("roles.session_speakers", mid=message_id, sid=sid))
        ent = entities[sid]
        partner = _dedupe([Opt(str(r["concept_id"]), str(r["text_raw"])) for r in speakers[sid]]
                          + [Opt(str(r["concept_id"]), str(r["text_raw"])) for r in ent
                             if str(r["ner_label"]) in PARTNER_LABELS])
        place = _dedupe([Opt(str(r["concept_id"]), str(r["text_raw"])) for r in ent
                         if str(r["ner_label"]) in T.PLACE_LABELS])
        out.append(Options(f, [], partner, place))     # option B: the action is chosen by rule (`action_word`)
    return out


# --- the closed call -------------------------------------------------------------------------

def _line(label: str, items: list[str]) -> str:
    return f"  {label}: " + "   ".join(f"{i} {t}" for i, t in enumerate(items, 1)) + "   0 none"


def build_messages(text: str, shown: list[Options], system_prompt: str) -> list[dict]:
    """The call: the turn, then each shown fact's quote with its numbered options per role. `system_prompt` is the
    extraction's own (passed in by extract.py, so this module does not import it back)."""
    blocks = []
    for n, o in enumerate(shown, 1):
        lines = [f'Fact {n}: "{o.fact.quote}"']
        if o.action:
            lines.append(_line("action", [f"{a.lemma}: {a.gloss}" for a in o.action]))
        if o.partner:
            lines.append(_line("with", [p.label for p in o.partner]))
        if o.place:
            lines.append(_line("place", [p.label for p in o.place]))
        blocks.append("\n".join(lines))
    body = " ".join((text or "").split()).replace('"""', "'''")
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": _PROMPT.format(text=body, facts="\n".join(blocks))}]


def parse_answers(raw: str | None) -> dict[int, dict] | None:
    """{fact number: answer object} from the reply, or None when it is not a JSON list of objects."""
    if not raw:
        return None
    s = raw.strip()
    m = re.search(r"\[.*\]", s, re.S)
    try:
        data = json.loads(m.group(0) if m else s)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return None
    out: dict[int, dict] = {}
    for x in data:
        n = _as_int(x.get("fact"))
        if n is not None and n not in out:
            out[n] = x
    return out


def _as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


# --- graph side ------------------------------------------------------------------------------

@dataclass
class RolesStats:
    counts: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in sorted(self.counts.items()) if v}


async def _write_action(gw: Any, oid: str, sense: wn_mod.ActionSense, ensured: set[str]) -> None:
    now = datetime.now(timezone.utc)
    for synset, label in sense.labels:
        cid = wn_mod.concept_id_of(synset)
        if cid not in ensured:
            await gw.run("roles.ensure_action_concept", cid=cid, text=label, now=now)
            ensured.add(cid)
    for child, parent in sense.chain:
        await kinds_mod.link_broader_sourced(gw, wn_mod.concept_id_of(child), wn_mod.concept_id_of(parent),
                                             wn_mod.SOURCE)
    await gw.run("roles.link_action", oid=oid, cid=sense.concept_id)


async def _write_phrase(gw: Any, oid: str, edge: str, surface: str) -> None:
    pid = str(uuid.uuid5(_PHRASE_NS, f"{oid}|{edge}|{surface.lower()}"))
    await gw.run(f"roles.link_{edge}_phrase", oid=oid, pid=pid, text=surface, rv=RULE_VERSION,
                 now=datetime.now(timezone.utc))


def pick(answer: dict | None, key: str, role: str, n_opts: int, counts: Counter) -> tuple[list[int], str]:
    """(valid 1-based picks, outcome) for one role of one fact. Outcomes: 'picked' (write), 'zero' (the model said
    none: fallback allowed), 'no_answer' (the reply left the role out: counted apart, fallback allowed), 'rejected' (a number not shown, or the wrong type: nothing
    written, no fallback). `with` takes one number or a list; action and place take one number."""
    if answer is None or key not in answer:
        counts[f"{role}_no_answer"] += 1
        return [], "no_answer"
    value = answer[key]
    many = isinstance(value, (list, tuple))
    if many and role != "partner":
        counts[f"{role}_pick_out_of_range"] += 1
        return [], "rejected"
    picks: list[int] = []
    bad = 0
    for v in (list(value) if many else [value])[:MAX_WITH * 2]:
        if v is None:
            continue
        n = _as_int(v)
        if n is None or n < 0 or n > n_opts:
            bad += 1
        elif n > 0 and n not in picks:
            picks.append(n)
    if bad:
        counts[f"{role}_pick_out_of_range"] += bad
    if picks:
        return picks[:MAX_WITH], "picked"
    return [], "rejected" if bad else "zero"


def _noun_head(tok) -> str | None:
    if tok.pos_ not in ("NOUN", "PROPN"):
        return None
    return tok.lemma_.lower() if tok.lemma_.isalpha() else tok.text.lower()


def fallback_phrases(doc, quote_span: tuple[int, int], role: str, subject_names: frozenset[str]) -> list[str]:
    """Dependency-parse fallback inside the clause of the quote: surfaces of the objects of "with" (partner, head
    under person.n.01 / social_group.n.01) or of "to" / "at" / "in" (place, head under the place roots)."""
    _toks, owners = evid._quote_clauses(doc, *quote_span)
    roots = wn_mod.PERSON_ROOTS if role == "partner" else wn_mod.PLACE_ROOTS
    out: list[str] = []
    for prep in doc:
        low = prep.lemma_.lower()
        if prep.dep_ != "prep" or evid.clause_owner(prep) not in owners:
            continue
        if (role == "partner" and low != "with") or (role == "place" and low not in PLACE_PREPS):
            continue
        for obj in (c for c in prep.children if c.dep_ == "pobj"):
            for tok in [obj, *obj.conjuncts]:
                head = _noun_head(tok)
                if not head or head in T.PRON or tok.text.lower() in subject_names:
                    continue
                if wn_mod.first_sense_under(head, roots):
                    out.append(doc[tok.left_edge.i: tok.i + 1].text)
    return list(dict.fromkeys(out))


async def _fallback(gw: Any, doc, qspan, f: FactIn, role: str, counts: Counter, after_failure: bool,
                    subject_names: frozenset[str]) -> None:
    suffix = "_after_failure" if after_failure else ""
    found = fallback_phrases(doc, qspan, role, subject_names) if qspan is not None else []
    found = found[:1] if role == "place" else found[:MAX_WITH]
    if not found:
        counts[f"{role}_fallback_none{suffix}"] += 1
        return
    edge = "participant" if role == "partner" else "place"
    for surface in found:
        await _write_phrase(gw, f.oid, edge, surface)
    counts[f"{role}_fallback_phrase{suffix}"] += 1


async def link_turn(gw: Any, tctx: Any, facts: list[FactIn], llm_client: Any, *, system_prompt: str) -> RolesStats:
    """The write-time entry, once per turn after every fact of it is written. `tctx` is the turn's
    `typed_objects.TurnContext` (text, message id, speaker, spaCy); `facts` its did / plans facts; `llm_client` the
    extraction client. At most one call, and none when no fact has a candidate. Never raises for one bad fact."""
    stats = RolesStats()
    counts = stats.counts
    text = tctx.text
    doc = tctx.docs.get(tctx.message_id)
    if doc is None:
        doc = tctx.docs[tctx.message_id] = tctx.nlp(text)
    options = await build_options(gw, tctx.nlp, tctx.message_id, facts, counts)
    now = datetime.now(timezone.utc)
    for o in options:                          # option B: the action word, by rule, no model
        try:
            word = action_word(tctx.nlp, o.fact, counts)
            if word:
                cid = action_concept_id(word)
                await gw.run("roles.ensure_action_concept", cid=cid, text=word, now=now)
                await gw.run("roles.link_action", oid=o.fact.oid, cid=cid)
                counts["action_written"] += 1
        except Exception:
            counts["errors"] += 1
            _logger.warning("[Roles] action failed oid=%s", o.fact.oid[:8], exc_info=True)
    shown = [o for o in options if o.any()]

    answers: dict[int, dict] | None = None
    failure = False
    if shown:
        counts["calls"] += 1
        try:
            raw = await asyncio.to_thread(llm_client.chat, build_messages(text, shown, system_prompt),
                                          max_tokens=ROLES_CALL_MAX_TOKENS)
        except Exception:
            counts["call_failed"] += 1
            failure = True
            _logger.warning("[Roles] call failed msg=%s", tctx.message_id[:8], exc_info=True)
        else:
            answers = parse_answers(raw)
            if answers is None:
                counts["unparseable"] += 1
                failure = True
    number = {id(o): n for n, o in enumerate(shown, 1)}

    ensured: set[str] = set()
    speaker = (tctx.speaker or "").strip().lower()
    for o in options:
        f = o.fact
        try:
            qspan = T.locate_quote(text, f.quote)
            names = frozenset(x for x in (speaker, f.subject_text.strip().lower()) if x)
            ans = (answers or {}).get(number.get(id(o), -1))
            if o.action and not failure:
                picks, outcome = pick(ans, "action", "action", len(o.action), counts)
                if picks:
                    sense = wn_mod.action_sense_of(o.action[picks[0] - 1].synset)
                    if sense is None:
                        counts["errors"] += 1
                    else:
                        await _write_action(gw, f.oid, sense, ensured)
                        counts["action_written"] += 1
                elif outcome == "zero":
                    counts["action_picked_0"] += 1
            for role, opts, key, edge in (("partner", o.partner, "with", "participant"),
                                          ("place", o.place, "place", "place")):
                fallback, after = False, False
                if not opts:
                    counts[f"{role}_no_options"] += 1
                    fallback = True
                elif failure:
                    fallback = after = True
                else:
                    picks, outcome = pick(ans, key, role, len(opts), counts)
                    for p in picks[:1] if role == "place" else picks:
                        await gw.run(f"roles.link_{edge}", oid=f.oid, cid=opts[p - 1].cid)
                        counts[f"{role}_written_concept"] += 1
                    if outcome in ("zero", "no_answer"):
                        counts[f"{role}_picked_0"] += outcome == "zero"
                        fallback = True
                if fallback:
                    await _fallback(gw, doc, qspan, f, role, counts, after, names)
        except Exception:
            counts["errors"] += 1
            _logger.warning("[Roles] failed oid=%s", f.oid[:8], exc_info=True)
    return stats
