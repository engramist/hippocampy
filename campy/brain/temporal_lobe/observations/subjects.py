"""
Item 3 of the 2026-11-10 plan (user ruling 2026-11-14, option A): who a fact may be about. Flag
`[observations] group_subjects` (env `CAMPY_OBSERVATION_GROUP_SUBJECTS`), default off, in no profile.

The extraction prompt (only with the flag on) also asks for facts about a group the speaker is part of ("we",
"my sister and I") and about a person the speaker names by relation ("my kids"). The model proposes; this rule
decides what the subject is, and nothing is guessed:

  group     the model's subject is "we" / "us" / "our" (and contractions) with a first-person plural in the quote, or
            a coordination with first person ("Anna and I", "I and my partner") found in the quote. Subject: the
            speaker's Concept (HAS_SUBJECT, as for "I"); the Observation is marked `group_subject = true`.
            Partners (HAS_PARTICIPANT) only when named: a Concept the turn MENTIONS as PERSON / ORG / NORP whose label
            is in the quote (`subjects.turn_named_people`), and the relation Concept of a coordinated "my partner".
            Nobody named: the speaker alone, still marked as a group subject.
  relation  the model's subject is "my" / "our" + a phrase whose head noun has its first WordNet sense under
            person.n.01 or social_group.n.01, and the phrase is in the quote. Subject: the Concept
            `rel:<speaker concept id>:<head lemma>` (kind_scheme "relation", relation_label the lemma, RELATION_OF the
            speaker). One node per speaker and relation; never merged with a named person ("my son Kyle" keeps the
            relation node and Kyle apart). "her kids" / "your kids" are not handled: they stay unanchored.

Without a resolved speaker Concept neither rule applies (there is no one to anchor on).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

GROUP_WORDS = frozenset({"we", "us", "our", "ourselves", "we're", "we've", "we'll", "we'd"})
_PLURAL_RE = re.compile(r"(?<![\w'])(we|us|our|ours|ourselves)(?![\w])|(?<![\w'])we['’](re|ve|ll|d)(?!\w)", re.I)
_FIRST = r"(?:i|me)"
_COORD_RE = re.compile(rf"^(?P<x>.+?)\s+and\s+{_FIRST}$|^{_FIRST}\s+and\s+(?P<y>.+)$", re.I)
_POSS_RE = re.compile(r"^(?:my|our)\s+(?P<phrase>.+)$", re.I)


@dataclass
class Anchor:
    kind: str                                   # "group" | "relation"
    relation: tuple[str, str] | None = None     # (head lemma, phrase as written after "my"): the relation subject
    partners: list[tuple[str, str]] = field(default_factory=list)   # relation partners of a group: (lemma, phrase)


def _in_quote(phrase: str, quote: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(" ".join(phrase.split())) + r"(?!\w)", quote, re.I) is not None


def relation_head(phrase: str) -> str | None:
    """The head lemma of a relation phrase ("kids" -> "kid", "best friend" -> "friend"), or None when no word of it
    has its first noun sense under the person roots. Words are tried from the last one back."""
    wn = wn_mod._wn()
    for word in reversed(re.findall(r"[A-Za-z]+", phrase)):
        lemma = (wn.morphy(word.lower(), "n") if wn is not None else None) or word.lower()
        if wn_mod.first_sense_under(lemma, wn_mod.PERSON_ROOTS):
            return lemma
    return None


def _relation_of(text: str, quote: str) -> tuple[str, str] | None:
    m = _POSS_RE.match(" ".join(text.split()))
    if not m or not _in_quote(text, quote):
        return None
    head = relation_head(m.group("phrase"))
    return (head, m.group("phrase")) if head else None


def classify(subject: str, quote: str) -> Anchor | None:
    """The anchor of a proposed subject, or None (the subject is handled as before)."""
    s = " ".join((subject or "").split())
    low = s.lower().replace("’", "'")
    if low in GROUP_WORDS:
        return Anchor("group") if _PLURAL_RE.search(quote) else None
    m = _COORD_RE.match(s)
    if m:
        if not _in_quote(s, quote):
            return None
        other = (m.group("x") or m.group("y") or "").strip()
        rel = _relation_of(other, quote)
        return Anchor("group", partners=[rel] if rel else [])
    rel = _relation_of(s, quote)
    return Anchor("relation", relation=rel) if rel else None


def relation_concept_id(speaker_id: str, lemma: str) -> str:
    return f"rel:{speaker_id}:{lemma}"


async def ensure_relation(gw: Any, speaker_id: str, speaker: str, lemma: str, phrase: str) -> str:
    """The speaker's relation Concept for `lemma`, created with its RELATION_OF edge when missing. Its text is
    "<speaker>'s <phrase>", so a text lookup of another speaker's "my kids" never finds it."""
    cid = relation_concept_id(speaker_id, lemma)
    await gw.run("subjects.ensure_relation_concept", cid=cid, text=f"{speaker.strip()}'s {phrase}", label=lemma,
                 now=datetime.now(timezone.utc))
    await gw.run("subjects.link_relation_of", cid=cid, sid=speaker_id)
    return cid


async def after_write(gw: Any, oid: str, anchor: Anchor, *, message_id: str, speaker_id: str, speaker: str,
                      quote: str) -> int:
    """For a written group-subject fact: mark it and link its named partners. Returns the partners linked."""
    if anchor.kind != "group":
        return 0
    await gw.run("subjects.mark_group_subject", oid=oid)
    partners = [r["concept_id"] for r in await gw.run("subjects.turn_named_people", mid=message_id, sid=speaker_id,
                                                         quote=quote)]
    for lemma, phrase in anchor.partners:
        partners.append(await ensure_relation(gw, speaker_id, speaker, lemma, phrase))
    for cid in dict.fromkeys(partners):
        await gw.run("roles.link_participant", oid=oid, cid=cid)
    return len(set(partners))
