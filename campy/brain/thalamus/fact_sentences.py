"""Fact sentences (placement A): the asked person's matched facts rendered by rule as plain sentences, each on the line
right after the conversation-section turn the fact came from. No model renders anything, nothing is written.

Behind `[retrieval] fact_sentences` (env `CAMPY_FACT_SENTENCES`, default off, in no profile). Flag off, or on with
nothing matching, leaves the prompt byte-identical.

What fires, and what is grouped and counted, is decided by the graph:
  * the SUBJECT and the object CONCEPTS come from `query_hits.subject` and `query_hits.objects` (exact labels, as the
    killed graph_facts section resolved them; that section and object-text matching are not used here);
  * `query_hits.facts_count` is the as-built "too broad" rule: 1..MAX_MATCHED matched facts (over ALL turns);
  * `fact_sentences.rows` returns, in one read, the groups of live facts whose source turn is SHOWN: the shown-turn join,
    the liveness, the grouping by predicate / polarity / object kind, the list cap and the duplicate-Observation flag
    are all in that query. An over-cap group has no row, so those facts are not rendered at all.
Python only fills templates. The caps (PER_TURN, PER_PROMPT) are a declared presentation exception: a slice over the
query's own newest-turn-first order of an already small result, counted in the record, never an answer computation.

The record returned per call (`bundle.fact_sentences`, `meta["fact_sentences"]`) lists every sentence with its fact ids,
its source message and whether the same fact is already shown as an Observation line (the semantic section).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from campy.brain.hippocampus.graph.queries.fact_sentences import FIELD_SEP, FIELDS, LIST_CAP, TOKEN_SEP

_logger = logging.getLogger(__name__)

MAX_MATCHED = 25        # the as-built graph_facts MAX_FACTS: more matched facts than this is too broad
PER_TURN = 2            # sentences kept per source turn
PER_PROMPT = 6          # sentences kept per prompt
MAX_PARTNERS = 3
LINE_PREFIX = "→ fact: "

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def fact_sentences_enabled(config: dict | None) -> bool:
    """`[retrieval] fact_sentences` (default false; env `CAMPY_FACT_SENTENCES=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("fact_sentences", False))


# ---------------------------------------------------------------- templates: predicate x polarity -> "{S} ... {X}"
# None is the approved "no sentence" cell. hypothetical and planned share a column.
_TEMPLATES: dict[str, tuple[str | None, str | None, str | None]] = {
    #                  asserted                    negated                          hypothetical / planned
    "did":           ("{S} did: {X}",           "{S} did not: {X}",              "{S} planned: {X}"),
    "plans":         ("{S} planned: {X}",       "{S} decided against: {X}",      "{S} planned: {X}"),
    "has_attribute": ("{S}: {X}",               "{S}: not {X}",                  "{S} might be: {X}"),
    "is_a":          ("{S} is {X}",             "{S} is not {X}",                "{S} might be {X}"),
    "located_in":    ("{S} was in {X}",         "{S} was not in {X}",            "{S} planned to be in {X}"),
    "owns":          ("{S} has {X}",            "{S} does not have {X}",         "{S} plans to get {X}"),
    "relates_to":    ("{S} is connected with {X}", "{S} is not connected with {X}", None),
    "prefers":       ("{S} likes {X}",          "{S} does not like {X}",         None),
    "changed_to":    ("{S} changed to {X}",     None,                            "{S} plans to change to {X}"),
}


def template_for(predicate: str, polarity: str | None) -> str | None:
    row = _TEMPLATES.get(str(predicate or ""))
    if row is None:
        return None
    pol = str(polarity or "asserted")
    if pol == "negated":
        return row[1]
    if pol in ("hypothetical", "planned"):
        return row[2]
    return row[0]


# ---------------------------------------------------------------- first person -> the subject
_CONTRACTIONS = ("m", "ve", "d", "ll", "re")


def _words(text: str) -> list[tuple[bool, str]]:
    """Split into (is_word, piece): a word is a run of ASCII letters, with a trailing contraction (apostrophe + m / ve / d /
    ll / re) kept on it; everything else is passed through. No regex: this is a rendering rule over the fact's own
    words, not a read of the question."""
    out: list[tuple[bool, str]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isascii() and text[i].isalpha():
            j = i
            while j < n and text[j].isascii() and text[j].isalpha():
                j += 1
            for c in _CONTRACTIONS:
                k = j + 1 + len(c)
                if j < n and text[j] in "'’" and text[j + 1:k] == c and not (k < n and text[k].isascii() and text[k].isalpha()):
                    j = k
                    break
            out.append((True, text[i:j]))
            i = j
        else:
            j = i
            while j < n and not (text[j].isascii() and text[j].isalpha()):
                j += 1
            out.append((False, text[i:j]))
            i = j
    return out


def _starts_clause(text: str) -> bool:
    words = text.split(None, 1)
    first = words[0] if words else ""
    for c in ("I", "We", "we"):
        if first == c or (first.startswith(c) and not first[len(c)].isalpha() and not first[len(c)].isdigit()):
            return True
    return False


def _group_possessive(group: str) -> str:
    return group + ("'" if group.endswith("s") else "'s")


def rewrite_first_person(text: str, subject: str, partners: list[str] | None = None) -> tuple[str, bool]:
    """Rewrite first-person words of a fact's own words to the subject: "my" -> "S's", "I" / "me" -> "S", and "we" /
    "us" / "our" to "S and P" (P the rule-written partner(s)) or "S and others". Word-boundary rules; the case of
    the pronoun is checked so "US", "i" and "ME" are left alone. Returns the text and whether a group word was
    rewritten with a named partner (the ", with <partner>" tail is then dropped)."""
    partners = list(partners or [])
    group = f"{subject} and " + (_join_names(partners) if partners else "others")
    used_partner = False

    def repl(tok: str) -> str:
        nonlocal used_partner
        low = tok.lower().replace("’", "'")
        base, _, suffix = low.partition("'")
        suffix = ("'" + suffix) if suffix else ""
        verbs = {"'m": " is", "'ve": " has", "'d": " would", "'ll": " will", "'re": " are"}
        if base == "i" and tok[0] == "I":
            return subject + (verbs.get(suffix, "") if suffix in ("'m", "'ve", "'d", "'ll") else "")
        if base == "we" and tok[0] in "wW":
            used_partner = used_partner or bool(partners)
            if suffix in ("'re", "'ve", "'d", "'ll"):
                the_verb = {"'re": " are", "'ve": " have", "'d": " would", "'ll": " will"}[suffix]
                return group + the_verb
            return group
        if suffix:
            return tok
        if base == "us" and tok == "us":
            used_partner = used_partner or bool(partners)
            return group
        if base in ("our", "ours") and tok in ("our", "ours", "Our", "Ours"):
            used_partner = used_partner or bool(partners)
            return _group_possessive(group)
        if base in ("my", "mine") and (tok == base or tok == base.capitalize()):
            return f"{subject}'s"
        if base == "me" and tok in ("me", "Me"):
            return subject
        if base == "myself" and tok in ("myself", "Myself"):
            return subject
        return tok

    return "".join(repl(piece) if is_word else piece for is_word, piece in _words(text)), used_partner


def _join_names(names: list[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------- dates
def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dmy(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def resolved_when(time_text: str, start: Any, end: Any, precision: str | None, anchor: Any) -> tuple[str, str] | None:
    """The date the fact's time phrase resolves to, as (short, long): ("14 July 2023", "on 14 July 2023"). The stored
    range is used; a fact written before time normalisation is resolved from its phrase against `anchor` (the
    timeparse rule). None when nothing resolves."""
    s, e, prec = _to_date(start), _to_date(end), precision or None
    if s is None and time_text:
        try:
            from campy.brain.temporal_lobe.observations.timeparse import normalize_time

            a = anchor if isinstance(anchor, datetime) else _anchor_datetime(anchor)
            r = normalize_time(time_text, a) if a else None
        except Exception:
            r = None
        if r is not None:
            s, e, prec = _to_date(r.start), _to_date(r.end), r.precision
    if s is None:
        return None
    e = e or s
    if prec == "week":
        return f"week of {_dmy(s)}", f"in the week of {_dmy(s)}"
    if prec == "month":
        return f"{_MONTHS[s.month - 1]} {s.year}", f"in {_MONTHS[s.month - 1]} {s.year}"
    if prec == "year":
        return f"{s.year}", f"in {s.year}"
    if e != s:
        return f"{_dmy(s)} to {_dmy(e)}", f"from {_dmy(s)} to {_dmy(e)}"
    return _dmy(s), f"on {_dmy(s)}"


def _anchor_datetime(value: Any) -> datetime | None:
    d = _to_date(value)
    return datetime(d.year, d.month, d.day) if d else None


# ---------------------------------------------------------------- one fact
def parse_members(members: str) -> list[dict]:
    """The query's member tokens as dicts (the FIELDS, in order). Splitting a delimited string only."""
    out = []
    for tok in str(members or "").split(TOKEN_SEP):
        if not tok:
            continue
        parts = tok.split(FIELD_SEP)
        parts += [""] * (len(FIELDS) - len(parts))
        m = dict(zip(FIELDS, parts))
        key = m["key"].split("|", 2) + ["", ""]
        m["turn_date"], m["message_iri"], m["message_id"] = key[0][:10], key[1], key[2]
        m["partner_list"] = sorted({p for p in m["partners"].split("|") if p})[:MAX_PARTNERS]
        out.append(m)
    return out


def _said_on(m: dict, inner: str = "") -> str:
    on = f"said on {m['turn_date']}" if m["turn_date"] else "said"
    return f"({inner}, {on})" if inner else f"({on})"


def _object_words(m: dict, subject: str) -> tuple[str, bool, bool]:
    """(the object phrase with first-person words rewritten, whether the partner is already in it, whether the phrase
    was a whole clause that begins with a first-person subject)."""
    raw = " ".join(str(m["text"]).split()).rstrip(" .")
    clause = _starts_clause(raw)
    text, used = rewrite_first_person(raw, subject, m["partner_list"])
    return text, used, clause


def render_single(m: dict, predicate: str, polarity: str, subject: str) -> str | None:
    """One fact as a sentence, or None (an approved "no sentence" cell, an unknown predicate, no object words)."""
    tpl = template_for(predicate, polarity)
    text, used_partner, clause = _object_words(m, subject)
    if tpl is None or not text:
        return None
    sentence = text if clause else tpl.format(S=subject, X=text)
    if m["place"]:
        sentence += f", in {m['place']}"
    if m["partner_list"] and not used_partner:
        sentence += f", with {_join_names(m['partner_list'])}"
    when = resolved_when(m["time_text"], m["time_start"], m["time_end"], m["time_precision"], m["observed_at"] or m["turn_date"])
    if when:
        sentence += f", {when[1]}"
    else:
        sentence += " " + _said_on(m, m["time_text"].strip() if m["time_text"] else "")
    return sentence + "."


def render_list(members: list[dict], predicate: str, polarity: str, subject: str) -> str | None:
    """A group of 2..LIST_CAP facts as one sentence: "S did: X (date), Y (date) and Z (date)." Members come oldest turn
    first. None when the cell is "no sentence", a member has no words, or a member is a whole clause."""
    tpl = template_for(predicate, polarity)
    if tpl is None or not (2 <= len(members) <= LIST_CAP):
        return None
    items = []
    for m in members:
        text, _used, clause = _object_words(m, subject)
        if not text or clause:
            return None
        when = resolved_when(m["time_text"], m["time_start"], m["time_end"], m["time_precision"],
                             m["observed_at"] or m["turn_date"])
        items.append(f"{text} ({when[0]})" if when else
                     f"{text} {_said_on(m, m['time_text'].strip() if m['time_text'] else '')}")
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return tpl.format(S=subject, X=joined) + "."


def sentences_from_rows(rows: list[dict], subject: str) -> tuple[list[dict], dict]:
    """Rows of `fact_sentences.rows` -> the kept sentences (newest source turn first, at most PER_TURN per turn and
    PER_PROMPT overall) and the counts. Pure."""
    kept: list[dict] = []
    per_turn: dict[str, int] = {}
    dropped_turn = dropped_prompt = 0
    for row in rows:
        members = parse_members(row.get("members"))
        if not members:
            continue
        predicate, polarity = str(row.get("predicate") or ""), str(row.get("polarity") or "asserted")
        if len(members) == 1:
            text = render_single(members[0], predicate, polarity, subject)
        else:
            text = render_list(members, predicate, polarity, subject)
        if not text:
            continue
        attach = str(row.get("attach_key") or "").split("|", 2) + ["", ""]
        iri, mid = attach[1], attach[2]
        if per_turn.get(iri, 0) >= PER_TURN:
            dropped_turn += 1
            continue
        if len(kept) >= PER_PROMPT:
            dropped_prompt += 1
            continue
        per_turn[iri] = per_turn.get(iri, 0) + 1
        kept.append({
            "text": text, "kind": "single" if len(members) == 1 else "list",
            "fact_ids": [m["oid"] for m in members], "message_id": mid, "message_iri": iri,
            "as_observation": any(m["as_observation"] for m in members),
            "n_members_as_observation": sum(1 for m in members if m["as_observation"]),
            "predicate": predicate, "polarity": polarity,
        })
    return kept, {"dropped_turn_cap": dropped_turn, "dropped_prompt_cap": dropped_prompt}


# ---------------------------------------------------------------- the built path
def _empty_record(n_matched: int = 0, subject: str = "") -> dict:
    return {"fired": False, "subject": subject, "n_matched": n_matched, "sentences": [], "n_sentences": 0,
            "n_dup_observation": 0, "dropped_turn_cap": 0, "dropped_prompt_cap": 0}


async def fact_sentences_for(db, query: str, shown_message_iris, shown_observation_ids=(), config: dict | None = None,
                             lists: str = "shown") -> dict:
    """The sentences the built path would add for `query` when `shown_message_iris` are the conversation turns in view and
    `shown_observation_ids` the Observations already shown as lines. Pure of the prompt: nothing is attached or written.
    `lists="all"` groups over every matched fact (offline measurement of that form only); the bundle compiler never
    passes it. Returns the record described in the module docstring."""
    from campy.brain.hippocampus.graph.gateway import get_gateway
    from campy.brain.hippocampus.graph.queries.query_hits import question_terms

    gw = get_gateway(db)
    pairs = question_terms(query)
    subj = await gw.run("query_hits.subject", pairs=pairs)
    if not subj:
        return _empty_record()
    sid, subject = subj[0]["sid"], str(subj[0].get("label") or "")
    kids = [r["kid"] for r in await gw.run("query_hits.objects", terms=[t for t, _ in pairs], sid=sid)]
    if not kids:
        return _empty_record(0, subject)
    counted = await gw.run("query_hits.facts_count", sid=sid, kids=kids, texts=[])
    n = int((counted[0].get("facts") if counted else 0) or 0)
    if n == 0 or n > MAX_MATCHED:
        return _empty_record(n, subject)
    shown = [str(i) for i in shown_message_iris if str(i).startswith("https://")]
    if not shown:
        return _empty_record(n, subject)
    rows = await gw.run("fact_sentences.rows_all" if lists == "all" else "fact_sentences.rows", sids=[sid], kids=kids,
                        shown_messages=shown, shown_observations=[str(o) for o in shown_observation_ids if o])
    sentences, counts = sentences_from_rows(rows or [], subject)
    return {"fired": bool(sentences), "subject": subject, "n_matched": n, "sentences": sentences,
            "n_sentences": len(sentences), "n_dup_observation": sum(1 for s in sentences if s["as_observation"]),
            **counts}


async def attach_fact_sentences(db, query: str, config: dict, conversation_section, semantic_section=None) -> dict | None:
    """Add `→ fact: <sentence>` to the end of the conversation item of each fact's source turn (the same item, so the line
    sits inside its turn's block). Returns the record, or None on any failure (the prompt is then untouched)."""
    try:
        iris = list(conversation_section.source_node_ids)
        shown_obs = []
        if semantic_section is not None and getattr(semantic_section, "variant", "") == "observations":
            shown_obs = [c.get("observation_id") for c in semantic_section.content if isinstance(c, dict)]
        record = await fact_sentences_for(db, query, iris, shown_obs, config)
        if not record["sentences"]:
            return record
        by_iri: dict[str, list[dict]] = {}
        for s in record["sentences"]:
            by_iri.setdefault(s["message_iri"], []).append(s)
        done: set[str] = set()
        for i, iri in enumerate(iris):
            if iri in done:
                continue
            done.add(iri)
            for s in by_iri.get(iri, []):
                item = conversation_section.content[i]
                item["text"] = f"{item['text']}\n{LINE_PREFIX}{s['text']}"
                item.setdefault("fact_sentences", []).append({"fact_ids": s["fact_ids"], "message_id": s["message_id"]})
        conversation_section.token_estimate = sum(max(1, len(c["text"]) // 4) for c in conversation_section.content)
        return record
    except Exception as e:
        _logger.warning("Error in attach_fact_sentences: %s", e)
        return None
