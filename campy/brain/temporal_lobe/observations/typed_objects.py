"""
B546: the object of a fact is a typed entity (flag `[observations] typed_objects`, default off).

Per Observation (predicate, object_text, the quote inside its source turn, the parse of the whole turn) a rule
(spaCy, WordNet, the kinds the store already has; no model) yields zero or more items. An item is an object:

  entity object   a Concept that B544 admitted (it has `ner_label`, and `Message -MENTIONS-> Concept`) whose text
                  occurs in the quote as whole words and is the object: inside `object_text`, or a list or
                  apposition member of the object's head noun ("brands like Nike"). The rule creates no entity.
                  Without B544 there are no admitted Concepts, the rule finds no entity object, and only the
                  nameless path below runs.
  nameless object the object noun phrase when no entity is the object (never for has_attribute / is_a, whose
                  object is a value): one `ObjectPhrase` node per Observation ("a book" in two facts is two
                  nodes). It is not a Concept: a Concept would enter the concept index, where the word "book"
                  would resolve to the phrase instead of the kind.

Written (through the existing writers and registered NamedQueries, never raw SPARQL):
  Observation -OBSERVATION_ABOUT-> Concept   every entity item
  Observation -HAS_OBJECT-> Concept          the entity object (at most one, first wins: B522)
  Observation -HAS_OBJECT-> ObjectPhrase     the nameless object (when the Observation has no object edge)
  Concept | ObjectPhrase -INSTANCE_OF-> kind first match of:
      1 stated     the sentence names the kind: "<noun> like/such as/including X", "<noun> called X", "my <noun>,
                   X", "Deb, my friend", "X is a <NP>", or "It is a <NP>" with a thing named in the previous
                   sentence. Guards against the metaphor ("Nature is my haven", "music ... It's my sanctuary"):
                   a sentence-initial common word that is the subject of a copula is not a name, and the
                   referent of "It is ..." must have been written capitalised.
      2 wordnet    a place: the entity is tagged GPE/LOC/FAC and its first WordNet noun sense is an instance of a
                   city, country, state, province, continent or region, and it is not written "a Labrador"
      2b speaker   the entity is a speaker of the conversation: `person`. `ner_label` PERSON alone never is (B549)
      3 head       nameless objects: the head noun of the phrase (head-final suffix of its compound chain) that is
                   a kind of the CLOSED kind set the store has; never a modifier ("video game tournament" is a
                   tournament, not a game)
      4 candidate  nothing is typed. The phrase keeps `kind_candidate` = its head lemma (read by
                   `typed_objects.phrase_kind_candidates`); an entity keeps its `ner_label`.
  The model's own kind never becomes an edge (P3). A kind is created only for a stated / place / speaker cue, by
  `entities.resolve_kind` (which consolidates it against the scheme), and never from a label that a named entity
  already holds (the B544 `can_be_kind` guard, repeated here for stores that predate it).

Evidence span. The offsets stored on an Observation do not always select its quote in the turn text (B552). The
rule never trusts them: it searches the quote in the Message text (exact, then with quotation marks folded, then
case-insensitively) and uses the span it finds; an Observation whose quote cannot be placed is skipped and counted.

Reads of the result are the NamedQueries in `graph/queries/typed_objects.py` (exact role KX, loose K+, the
candidate read). `apply_to_observation` is the write-time entry (the extractor); `backfill_typed_objects` is the
idempotent store-wide entry.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.concept_links import concept_index, norm_key
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod
from campy.brain.temporal_lobe.observations import entities as ent

_logger = logging.getLogger(__name__)

RULE_VERSION = "b546-1"
_PHRASE_NS = uuid.UUID("b5460000-0000-0000-0000-000000000000")

PRON = frozenset({"i", "me", "my", "myself", "we", "us", "our", "you", "your", "he", "him", "his", "she", "her",
                  "they", "them", "their", "it", "its", "this", "that", "these", "those"})
# Words that say nothing about what a thing is.
META = frozenset({"name", "thing", "type", "kind", "sort", "stuff", "one", "item", "example", "part", "way", "lot",
                  "bit", "something", "anything", "everything", "nothing", "someone", "people", "person", "time",
                  "day", "week", "month", "year", "moment", "today", "tomorrow", "yesterday", "tonight", "life",
                  "world", "fact", "idea", "reason", "point", "end", "hand", "back", "side", "place", "mine", "much",
                  "many", "kid", "guy", "man", "woman"})
# WordNet lexicographer files of words that are values or measures, not things an answer lists.
LOW_LEX = frozenset({"noun.tops", "noun.feeling", "noun.attribute", "noun.state", "noun.time", "noun.shape",
                     "noun.quantity", "noun.relation", "noun.motive", "noun.phenomenon", "noun.process",
                     "noun.cognition"})
# What a tagger label names when a sentence refers back to it ("It's a fantasy novel"): things, not people or places.
THING_LABELS = frozenset({"WORK_OF_ART", "PRODUCT", "EVENT", "ORG"})
PLACE_LABELS = frozenset({"GPE", "LOC", "FAC"})
_HEARST_PREP = frozenset({"like", "including", "as"})
_CALLED = frozenset({"called", "named", "titled", "entitled"})
_INDEFINITE = frozenset({"a", "an"})
_COARSE_PLACES = (("city.n.01", "city"), ("country.n.02", "country"), ("state.n.04", "state"),
                  ("province.n.01", "province"), ("continent.n.01", "continent"), ("region.n.03", "region"))
_QUOTE_STRIP = " \"“”'.,;:!?"


# --- WordNet (optional; every question is answered "no" without it) ----------------------

def _first_lexname(word: str) -> str | None:
    wn = wn_mod._wn()
    if wn is None:
        return None
    try:
        s = wn.synsets(word, pos="n")
        return s[0].lexname() if s else None
    except Exception:
        return None


def _noun_count_dominant(word: str) -> bool:
    """True when the noun senses of `word` are at least as frequent in SemCor as its verb senses."""
    wn = wn_mod._wn()
    if wn is None:
        return False
    n = sum(lem.count() for s in wn.synsets(word, pos="n") for lem in s.lemmas() if lem.name().lower() == word)
    v = sum(lem.count() for s in wn.synsets(word, pos="v") for lem in s.lemmas() if lem.name().lower() == word)
    return n >= v and n > 0


def good_kind_word(lemma: str) -> bool:
    """A noun an answer can list: a known WordNet noun outside the abstract lexicographer files."""
    lemma = (lemma or "").lower()
    if len(lemma) < 3 or lemma in META or lemma in PRON or not lemma.isalpha():
        return False
    lx = _first_lexname(lemma)
    return lx is not None and lx.lower() not in LOW_LEX


def is_common_noun_word(word: str) -> bool:
    """WordNet's first noun sense of the lower-case word is a common noun, not a named instance ("nature",
    "music"; not "toronto")."""
    wn = wn_mod._wn()
    if wn is None:
        return False
    try:
        senses = wn.synsets(word.lower(), pos="n")
    except Exception:
        return False
    return bool(senses) and not senses[0].instance_hypernyms()


def wordnet_place_kind(name: str) -> str | None:
    """city / country / state / province / continent / region when the FIRST noun sense of `name` is a place
    that is an instance of one of them (WordNet carries the major places), else None."""
    wn = wn_mod._wn()
    if wn is None:
        return None
    try:
        senses = wn.synsets(name.replace(" ", "_"), pos="n")
        if not senses:
            return None
        s = senses[0]
        ih = s.instance_hypernyms()
        if s.lexname() != "noun.location" or not ih:
            return None
        closure: set[str] = set()
        for h in ih:
            closure |= {x.name() for x in h.closure(lambda x: x.hypernyms())} | {h.name()}
    except Exception:
        return None
    for syn, label in _COARSE_PLACES:
        if syn in closure:
            return label
    return None


def singular(tok) -> str:
    lem = tok.lemma_.lower()
    return lem if lem.isalpha() else tok.text.lower()


# --- the evidence span ------------------------------------------------------------------

def locate_quote(text: str, quote: str, start: int | None = None, end: int | None = None) -> tuple[int, int] | None:
    """(start, end) of `quote` in `text`. The stored offsets are used only when they select the quote exactly
    (B552: they do not always); otherwise the quote is searched, exactly, then with quotation marks folded to
    plain ones (a one-for-one character map, so offsets stay valid), then ignoring case."""
    if not text or not quote:
        return None
    if start is not None and end is not None and 0 <= start < end <= len(text) and text[start:end] == quote:
        return start, end
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    fold = obs._QUOTE_TABLE
    ft, fq = text.translate(fold), quote.translate(fold)
    i = ft.find(fq)
    if i >= 0:
        return i, i + len(quote)
    i = ft.lower().find(fq.lower())
    return (i, i + len(quote)) if i >= 0 else None


# --- the rule (pure given spaCy and WordNet) ---------------------------------------------

@dataclass
class Item:
    obj: str                     # 'entity' | 'phrase'
    cid: str | None              # Concept id (entities)
    surface: str
    kind: str | None             # kind label to type with (None: not typed)
    rule: str | None             # stated | wordnet | speaker | head
    cue: str | None
    role: str                    # 'object' (HAS_OBJECT) | 'about'
    candidate: str | None = None
    kid: str | None = None       # the kind Concept id when the closed set already has it
    extra: dict = field(default_factory=dict)


@dataclass
class RuleContext:
    mentions: list[tuple[str, str, str]]           # (concept_id, text_raw, ner_label) of the turn's admitted entities
    speakers: frozenset[str]                       # lower-cased speakers of the conversation
    kind_by_key: dict[str, str]                    # norm_key(kind label or alt) -> kind Concept id
    subject_ids: frozenset[str] = frozenset()
    subject_names: frozenset[str] = frozenset()    # lower-cased: the speaker and the Observation's subject text
    physical_values: bool = False                  # B564 (flag `roles`): has_attribute / is_a may hold a physical noun


def np_suffixes(tok) -> list[str]:
    """The head-final compound chain of a noun: ['plastic model kit', 'model kit', 'kit'] (lemmas)."""
    run = []
    want = tok.i - 1
    for c in sorted((c for c in tok.lefts if c.dep_ == "compound" and c.pos_ in ("NOUN", "PROPN")),
                    key=lambda t: -t.i):
        if c.i != want:
            break
        run.append(c)
        want -= 1
    run.reverse()
    words = [singular(c) if c.pos_ == "NOUN" else c.text.lower() for c in run] + [singular(tok)]
    return [" ".join(words[i:]) for i in range(len(words))]


def kind_from_noun(tok, kind_by_key: dict[str, str]) -> tuple[str | None, str]:
    """(kind id or None, label): the longest head-final suffix of the noun's chain that is a kind of the closed
    set, else the head lemma (the kind to create or the candidate)."""
    suf = np_suffixes(tok)
    for s in suf:
        k = kind_by_key.get(norm_key(s))
        if k:
            return k, s
    return None, suf[-1]


def _span_tokens(doc, s: int, e: int):
    return [t for t in doc if t.idx >= s and t.idx + len(t.text) <= e]


def _span_root(toks):
    ids = {t.i for t in toks}
    for t in toks:
        if t.head.i not in ids or t.head.i == t.i:
            return t
    return toks[-1]


def mention_spans(doc, mentions, ws: int, we: int) -> list[tuple[int, int, str, str, str]]:
    """(start, end, concept_id, surface, label) occurrences of admitted mentions inside the window as whole
    words, longest first, not overlapping."""
    cand = []
    for cid, text, label in mentions:
        if not text:
            continue
        for m in re.finditer(r"(?<!\w)" + re.escape(text) + r"(?!\w)", doc.text, re.I):
            if m.start() >= ws and m.end() <= we:
                cand.append((m.start(), m.end(), cid, doc.text[m.start():m.end()], label))
    cand.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    kept: list[tuple] = []
    for c in cand:
        if all(c[1] <= k[0] or c[0] >= k[1] for k in kept):
            kept.append(c)
    return sorted(kept)


def governing_noun(doc, toks):
    """(noun token, cue) when the span is introduced by a common noun, else (None, None):
    appositive ("my friend, Josh"), Hearst ("brands like Nike"), or "<noun> called X"."""
    r = _span_root(toks)
    t = r
    seen = 0
    while t.dep_ == "conj" and seen < 8:                       # "Nike and Under Armour": climb to the first member
        t = t.head
        seen += 1
    if t.dep_ == "appos" and t.head.pos_ == "NOUN":
        return t.head, "appos"
    if t.dep_ == "pobj" and t.head.lower_ in _HEARST_PREP:
        g = t.head.head
        if t.head.lower_ == "as" and not (t.head.i > 0 and doc[t.head.i - 1].lower_ == "such"):
            return None, None
        if g.pos_ == "NOUN":
            return g, "hearst"
    for anc in [t, *t.ancestors]:
        if anc.lower_ in _CALLED and anc.head.pos_ == "NOUN":
            return anc.head, "called"
        if anc.dep_ in ("oprd", "attr", "acomp") and anc.head.lower_ in _CALLED and anc.head.head.pos_ == "NOUN":
            return anc.head.head, "called"
    return None, None


def stated_kind(doc, toks, kind_by_key):
    """(kind id|None, label, cue) when the sentence states the span's kind, else None."""
    gov, cue = governing_noun(doc, toks)
    if gov is not None and good_kind_word(singular(gov)):
        kid, lab = kind_from_noun(gov, kind_by_key)
        return kid, lab, cue
    r = _span_root(toks)
    for ch in r.children:                                      # "Deb, my friend" / "Harry Potter, a fantasy novel"
        if ch.dep_ == "appos" and ch.pos_ == "NOUN" and good_kind_word(singular(ch)):
            kid, lab = kind_from_noun(ch, kind_by_key)
            return kid, lab, "appos_child"
    h = r.head
    if r.dep_ in ("nsubj", "nsubjpass") and h.lemma_ == "be":      # "X is a fantasy novel"
        for ch in h.children:
            if ch.dep_ == "attr" and ch.pos_ == "NOUN" and good_kind_word(singular(ch)):
                kid, lab = kind_from_noun(ch, kind_by_key)
                return kid, lab, "copula"
    return None


def copula_ref(doc, ws: int, we: int, mention_all, kind_by_key):
    """'It's a fantasy novel' inside the window; the referent is the nearest admitted mention in the previous
    sentence that was written capitalised and names a thing (a tagger label on a lower-case word is not a name,
    and a person or a place is not what a sentence refers back to). -> [(cid, text, label, kid, kind label, attr)]"""
    out = []
    sents = list(doc.sents)
    for t in doc:
        if t.idx < ws or t.idx + len(t.text) > we:
            continue
        if not (t.lower_ in ("it", "this", "that") and t.dep_ == "nsubj" and t.head.lemma_ == "be"
                and t.head.lower_ in ("is", "'s", "’s", "are")):
            continue
        attr = [c for c in t.head.children if c.dep_ == "attr" and c.pos_ == "NOUN"]
        if not attr or not good_kind_word(singular(attr[0])):
            continue
        sent_start = t.sent.start_char
        before = [x for x in sents if x.end_char <= sent_start]
        if not before:
            continue
        ps_start = before[-1].start_char
        prev = [m for m in mention_all
                if m[1] <= sent_start and m[0] >= ps_start and m[4] in THING_LABELS and m[3][:1].isupper()]
        if not prev:
            continue
        ref = prev[-1]
        kid, lab = kind_from_noun(attr[0], kind_by_key)
        out.append((ref[2], ref[3], ref[4], kid, lab, " ".join(x.text for x in attr[0].subtree)))
    return out


def object_head(od):
    """(head token, cue) of the object phrase parse, or (None, None): a noun; a verb phrase's direct object
    (else attribute, else first prepositional object); an -ing / act word WordNet counts more often as a noun."""
    roots = [t for t in od if t.head.i == t.i]
    if not roots:
        return None, None
    root = roots[0]
    if root.pos_ == "NOUN":
        return root, "np"
    if root.pos_ == "PROPN":
        return root, "propn"
    if root.pos_ in ("VERB", "AUX"):
        args = [t for t in od if t.dep_ in ("dobj", "attr", "oprd") and t.pos_ in ("NOUN", "PROPN")]
        if not args:
            args = [t for t in od if t.dep_ == "pobj" and t.pos_ in ("NOUN", "PROPN")][:1]
        if args:
            return args[0], "verb_np"
        if len(od) == 1 or all(t.pos_ in ("PART", "ADV", "ADP", "DET") or t.i == root.i for t in od):
            w = root.text.lower()
            if _first_lexname(w) in ("noun.act", "noun.event") and _noun_count_dominant(w):
                return root, "gerund"
    return None, None


def _entity_kind(doc, toks, label: str, surface: str, sl: str, st, ctx: RuleContext):
    """Rules 1, 2, 2b for one entity: (kind label, rule, cue, kind id) or Nones."""
    if st is not None:
        kid, lab, cue = st
        return lab, "stated", cue, kid
    if label in PLACE_LABELS and _place_cue_allowed(doc, toks):
        k = wordnet_place_kind(surface)
        if k:
            return k, "wordnet", "wordnet", None
    if sl in ctx.speakers:
        return "person", "speaker", "speaker", None
    return None, None, None, None


def _place_cue_allowed(doc, toks) -> bool:
    """A place kind needs the tagger to call this span a place in this very turn (when it tags it at all) and
    the span not to be written 'a Labrador': an indefinite article marks a member of a class, not a place."""
    s, e = toks[0].idx, toks[-1].idx + len(toks[-1].text)
    for ent_ in doc.ents:
        if ent_.start_char < e and s < ent_.end_char and ent_.label_ not in PLACE_LABELS:
            return False
    first = toks[0]
    return not (first.i > 0 and doc[first.i - 1].lower_ in _INDEFINITE)


def typed_objects(pred: str, object_text: str, ws: int, we: int, doc, ctx: RuleContext, nlp) -> tuple[list[Item], list[str]]:
    """(items, rejection reasons). `doc` is the parse of the whole turn, [ws, we) the quote inside it."""
    items: list[Item] = []
    rej: list[str] = []
    obj_l = (object_text or "").lower()
    kbk = ctx.kind_by_key
    spans = mention_spans(doc, ctx.mentions, ws, we)
    mention_all = mention_spans(doc, ctx.mentions, 0, len(doc.text))
    head_text = object_text
    if ctx.physical_values and pred == "has_attribute" and ":" in (object_text or ""):
        head_text = object_text.split(":", 1)[1].strip()           # B564: "pet: dog" -> the value
    od = nlp(head_text) if head_text else None
    ohead, ocue = object_head(od) if od is not None and len(od) else (None, None)

    for s, e, cid, surface, label in spans:
        sl = surface.strip(_QUOTE_STRIP).lower()
        if not sl or sl in PRON or sl in ctx.subject_names:
            continue
        if not surface[:1].isupper() and not surface[:1].isdigit():
            rej.append("mention_written_lowercase")                 # a tagger label on a lower-case word is not a name (B549)
            continue
        toks = _span_tokens(doc, s, e)
        if not toks:
            continue
        if len(toks) == 1 and toks[0].is_sent_start and toks[0].pos_ != "PROPN":
            continue                                                # "Winning was awesome": a common word, not a name
        if len(toks) == 1 and toks[0].is_sent_start and toks[0].head.lemma_ == "be" and is_common_noun_word(sl):
            rej.append("copula_subject_common_word")                # "Nature is my haven": a word, not a name
            continue
        st = stated_kind(doc, toks, kbk)
        gov, _gcue = governing_noun(doc, toks)
        in_obj = bool(re.search(r"(?<!\w)" + re.escape(sl) + r"(?!\w)", obj_l))
        gov_in_obj = bool(gov) and (gov.lower_ in obj_l or gov.lemma_.lower() in obj_l)
        if not (in_obj or gov_in_obj):
            rej.append("named_not_object")
            continue
        words = set(sl.split())
        head_in = ohead is not None and ohead.text.lower() in words
        is_obj = gov_in_obj or head_in or ohead is None or ocue == "propn"
        kind, rule, cue, kid = _entity_kind(doc, toks, label, surface, sl, st, ctx)
        items.append(Item("entity", cid, surface, kind, rule, cue, "object" if is_obj else "about", None, kid,
                          {"label": label}))

    for cid, text, label, kid, lab, atext in copula_ref(doc, ws, we, mention_all, kbk):       # "It's a fantasy novel"
        if cid in ctx.subject_ids:
            continue
        ov = False
        if od is not None and len(od) and ohead is not None:
            ov = atext.lower() in obj_l or obj_l in atext.lower() or singular(ohead) in atext.lower()
        hit = [i for i in items if i.cid == cid]
        if hit:
            if hit[0].kind is None:
                hit[0].kind, hit[0].rule, hit[0].cue, hit[0].kid = lab, "stated", "copula_ref", kid
            continue
        items.append(Item("entity", cid, text, lab, "stated", "copula_ref", "object" if ov else "about", None, kid,
                          {"label": label}))

    value_pred = pred in ("has_attribute", "is_a")
    if (value_pred and not ctx.physical_values) or not object_text or any(i.role == "object" for i in items):
        return items, rej
    if ohead is None:
        rej.append("object_not_noun_phrase")
        return items, rej
    if ocue == "propn" or (ocue != "gerund" and ohead.text[:1].isupper() and (ohead.i > 0 or len(od) == 1)):
        rej.append("capitalised_head_not_admitted")
        return items, rej
    if value_pred and ocue == "gerund":
        rej.append("value_not_physical")                            # B564: a value is a thing, not an activity
        return items, rej
    if ocue == "gerund":
        wn = wn_mod._wn()
        lemma = (wn.morphy(ohead.text.lower(), "n") if wn is not None else None) or ohead.text.lower()
    else:
        lemma = singular(ohead)
    if not good_kind_word(lemma):
        rej.append("object_head_not_a_kind_word")
        return items, rej
    if value_pred and not wn_mod.first_sense_under(lemma, wn_mod.PHYSICAL_ROOTS):
        rej.append("value_not_physical")                            # B564: "courage", "job" stay text
        return items, rej
    if ocue == "gerund":
        kid, lab = kbk.get(norm_key(lemma)), lemma
    else:
        kid, lab = kind_from_noun(ohead, kbk)
    left = min([t.i for t in ohead.lefts] + [ohead.i]) if ocue != "gerund" else ohead.i
    chunk = " ".join(t.text for t in od[left:ohead.i + 1] if (t.dep_ != "det" and t.pos_ != "PRON") or t.i == ohead.i)
    items.append(Item("phrase", None, chunk, lab if kid else None, "head" if kid else None, ocue, "object",
                      None if kid else lab, kid, {"np": chunk, "head": lemma}))
    return items, rej


# --- reading and writing the graph ------------------------------------------------------

@dataclass
class ObsRow:
    oid: str
    predicate: str
    object_text: str
    subject_text: str
    subject_id: str | None
    quote: str
    message_id: str
    message_text: str
    speaker: str | None
    start: int | None = None
    end: int | None = None
    physical_values: bool = False       # B564: see RuleContext


@dataclass
class TypedObjectStats:
    """Counts of one run (redacted metadata: no content)."""
    observations: int = 0
    skipped_no_span: int = 0
    skipped_no_nlp: int = 0
    entity_objects: int = 0
    phrase_objects: int = 0
    typed: int = 0
    candidates: int = 0
    kinds_created: int = 0
    kinds_blocked: int = 0
    rejected: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "rejected" and v}
        if self.rejected:
            d["rejected"] = dict(self.rejected)
        return d


def _nlp(config: dict | None):
    from campy.brain.temporal_lobe.loop.step1_ner import get_nlp

    return get_nlp(((config or {}).get("nlp") or {}).get("spacy_model", "en_core_web_md"))


async def kind_key_map(gw: Any) -> dict[str, str]:
    """norm_key of every kind label (pref and alt) -> kind Concept id, read fresh from the graph."""
    kbk: dict[str, str] = {}
    for cid, kind in (await kinds_mod.load_kinds(gw)).items():
        for key in kind.keys():
            kbk.setdefault(key, cid)
    return kbk


async def load_turn_context(gw: Any, message_id: str) -> tuple[list[tuple[str, str, str]], frozenset[str]]:
    """(the turn's admitted entities, the conversation's speakers) as read-through views of the graph."""
    mentions = [(str(r["concept_id"]), str(r["text_raw"]), str(r["ner_label"]))
                for r in await gw.run("typed_objects.message_entities", mid=message_id) if r.get("ner_label")]
    speakers = await load_speakers(gw)
    return mentions, speakers


async def load_speakers(gw: Any) -> frozenset[str]:
    return frozenset(str(r["speaker"]).strip().lower() for r in await gw.run("typed_objects.speakers")
                     if r.get("speaker"))


async def named_entity_keys(gw: Any) -> set[str]:
    return {norm_key(str(r["text_raw"])) for r in await gw.run("typed_objects.named_entity_texts")} - {""}


def _plan(row: ObsRow, mentions, speakers, kbk, nlp, doc_cache: dict, stats: TypedObjectStats):
    span = locate_quote(row.message_text, row.quote, row.start, row.end)
    if span is None:
        stats.skipped_no_span += 1
        return None, []
    doc = doc_cache.get(row.message_id)
    if doc is None:
        doc = doc_cache[row.message_id] = nlp(row.message_text)
    ctx = RuleContext(
        mentions=mentions, speakers=speakers, kind_by_key=kbk,
        subject_ids=frozenset({row.subject_id}) if row.subject_id else frozenset(),
        subject_names=frozenset(x.strip().lower() for x in (row.speaker or "", row.subject_text or "") if x.strip()),
        physical_values=row.physical_values)
    items, rej = typed_objects(row.predicate, row.object_text, span[0], span[1], doc, ctx, nlp)
    return items, rej


async def _ensure_kinds(gw: Any, config: dict | None, items: list[Item], kbk: dict[str, str], guard: set[str] | None,
                        stats: TypedObjectStats, ostats: Any, embedding_model: str) -> bool:
    """Create the kinds that a stated, place or speaker cue names and the closed set lacks. True when any
    was created. A label a named entity already holds is not made a kind (the item stays untyped). `guard`
    (the keys of the named entities) is read from the graph on first need when not given."""
    created = False
    index = None
    for it in items:
        if it.rule not in ("stated", "wordnet", "speaker") or not it.kind or it.kid or norm_key(it.kind) in kbk:
            continue
        if guard is None:
            guard = await named_entity_keys(gw)
        if norm_key(it.kind) in guard:
            stats.kinds_blocked += 1
            continue
        if index is None:
            index = await concept_index(gw, alt_labels=True)
        kid = await ent.resolve_kind(
            gw, it.kind, index, ostats, embedding_model=embedding_model,
            closematch=kinds_mod.closematch_threshold(config), hygiene=kinds_mod.kind_hygiene_enabled(config),
            wordnet=kinds_mod.wordnet_kinds_enabled(config))
        if kid:
            created = True
            stats.kinds_created += 1
    return created


async def _write(gw: Any, row: ObsRow, items: list[Item], kbk: dict[str, str], stats: TypedObjectStats) -> None:
    """Write the items through the existing writers and the registered queries."""
    object_set = False
    for it in items:
        kid = it.kid or (kbk.get(norm_key(it.kind)) if it.kind else None)
        if it.obj == "entity":
            await gw.run("observations.link_about_concept", oid=row.oid, cid=it.cid)
            if it.role == "object" and not object_set:
                await gw.run("observations.link_object", oid=row.oid, cid=it.cid)
                await gw.run("observations.set_object_id_from_role", oid=row.oid)
                object_set = True
                stats.entity_objects += 1
            if kid and kid != it.cid:
                await _link_entity_kind(gw, it.cid, kid, kbk)
                stats.typed += 1
            continue
        if object_set:
            continue
        pid = str(uuid.uuid5(_PHRASE_NS, row.oid + "|" + it.surface))
        await gw.run("typed_objects.link_object_phrase", oid=row.oid, pid=pid, text=it.surface,
                     rv=RULE_VERSION, now=datetime.now(timezone.utc))
        object_set = True
        stats.phrase_objects += 1
        if kid:
            await gw.run("typed_objects.link_phrase_kind", pid=pid, kid=kid)
            stats.typed += 1
        elif it.candidate:
            await gw.run("typed_objects.set_phrase_candidate", pid=pid, cand=it.candidate)
            stats.candidates += 1


async def _link_entity_kind(gw: Any, cid: str, kid: str, kbk: dict[str, str]) -> None:
    if cid in set(kbk.values()):                                   # an entity that is itself a kind gets no INSTANCE_OF
        return
    await kinds_mod.link_instance_of(gw, cid, kid)


async def process_observation(gw: Any, config: dict | None, row: ObsRow, mentions, speakers, nlp, doc_cache: dict,
                              stats: TypedObjectStats, ostats: Any, *, guard: set[str] | None = None,
                              embedding_model: str = obs.EMBEDDING_MODEL) -> None:
    """Plan, create the kinds the cues name, plan again against the closed set that now exists, write."""
    stats.observations += 1
    kbk = await kind_key_map(gw)
    items, rej = _plan(row, mentions, speakers, kbk, nlp, doc_cache, stats)
    if items is None:
        return
    if await _ensure_kinds(gw, config, items, kbk, guard, stats, ostats, embedding_model):
        kbk = await kind_key_map(gw)
        items, rej = _plan(row, mentions, speakers, kbk, nlp, doc_cache, stats)
        if items is None:
            return
    stats.rejected.update(x for x in rej)
    if items:
        await _write(gw, row, items, kbk, stats)


# --- write-time entry (the extractor) ----------------------------------------------------

@dataclass
class TurnContext:
    """What one turn's Observations share: its admitted entities, the conversation's speakers, the parse."""
    message_id: str
    text: str
    speaker: str | None
    mentions: list[tuple[str, str, str]]
    speakers: frozenset[str]
    nlp: Any
    docs: dict = field(default_factory=dict)
    stats: TypedObjectStats = field(default_factory=TypedObjectStats)


async def turn_context(gw: Any, config: dict | None, message_id: str, text: str, speaker: str | None) -> TurnContext | None:
    """The shared context of a turn, or None when spaCy is not available (the rule does not run)."""
    try:
        nlp = _nlp(config)
    except Exception:
        _logger.warning("[TypedObjects] spaCy unavailable; typed objects skipped", exc_info=True)
        return None
    mentions, speakers = await load_turn_context(gw, message_id)
    return TurnContext(message_id, text, speaker, mentions, speakers, nlp)


async def apply_to_observation(gw: Any, config: dict | None, tctx: TurnContext, observation_id: str, *,
                               predicate: str, object_text: str, subject_text: str, subject_id: str | None,
                               quote: str, ostats: Any, embedding_model: str = obs.EMBEDDING_MODEL) -> None:
    """Type the object of one just-written Observation of the turn `tctx` describes."""
    row = ObsRow(observation_id, predicate, object_text, subject_text, subject_id, quote, tctx.message_id, tctx.text,
                 tctx.speaker, physical_values=obs.capture_roles_enabled(config))
    await process_observation(gw, config, row, tctx.mentions, tctx.speakers, tctx.nlp, tctx.docs, tctx.stats, ostats,
                              embedding_model=embedding_model)


# --- the store-wide entry ----------------------------------------------------------------

async def backfill_typed_objects(db: Any, config: dict | None = None, *, embedding_model: str = obs.EMBEDDING_MODEL,
                                 limit: int | None = None, log_every: int = 0) -> TypedObjectStats:
    """Run the rule over every live Observation of a store. Idempotent: an Observation that already has an
    object edge gets no second one, an edge or a kind already written is a set-semantics no-op, and a second run
    finds the kinds the first created. Two passes, so that the closed kind set is complete when edges are
    written: pass 1 creates the kinds the stated / place / speaker cues name, pass 2 writes."""
    from campy.brain.hippocampus.graph.gateway import get_gateway

    gw = get_gateway(db)
    stats = TypedObjectStats()
    ostats = _CreatedCounter()
    nlp = _nlp(config)
    rows = []
    for r in await gw.run("typed_objects.live_observations"):
        rows.append(ObsRow(
            str(r["observation_id"]), str(r["predicate"]), str(r["object_text"]), str(r["subject_text"]),
            str(r["subject_id"]) if r.get("subject_id") else None, str(r["evidence_text"]), str(r["message_id"]),
            str(r["message_text"]), str(r["speaker"]) if r.get("speaker") else None,
            int(r["evidence_start"]), int(r["evidence_end"]), obs.capture_roles_enabled(config)))
    rows.sort(key=lambda x: x.oid)
    if limit:
        rows = rows[:limit]
    speakers = await load_speakers(gw)
    mentions_by_msg: dict[str, list] = {}
    for mid in {r.message_id for r in rows}:
        mentions_by_msg[mid] = [(str(x["concept_id"]), str(x["text_raw"]), str(x["ner_label"]))
                                for x in await gw.run("typed_objects.message_entities", mid=mid) if x.get("ner_label")]
    guard = await named_entity_keys(gw)
    docs: dict = {}
    # pass 1: kinds
    pass1 = TypedObjectStats()
    kbk0 = await kind_key_map(gw)
    for n, row in enumerate(rows):
        items, _rej = _plan(row, mentions_by_msg.get(row.message_id, []), speakers, kbk0, nlp, docs, pass1)
        if items:
            await _ensure_kinds(gw, config, items, kbk0, guard, stats, ostats, embedding_model)
        if log_every and n % log_every == 0:
            _logger.info("[TypedObjects] pass 1: %d / %d", n, len(rows))
    stats.skipped_no_span = pass1.skipped_no_span
    # pass 2: edges, against the closed set as pass 1 left it
    kbk = await kind_key_map(gw)
    for n, row in enumerate(rows):
        stats.observations += 1
        items, rej = _plan(row, mentions_by_msg.get(row.message_id, []), speakers, kbk, nlp, docs,
                           TypedObjectStats())
        if items is None:
            continue
        stats.rejected.update(rej)
        if items:
            await _write(gw, row, items, kbk, stats)
        if log_every and n % log_every == 0:
            _logger.info("[TypedObjects] pass 2: %d / %d", n, len(rows))
    return stats


class _CreatedCounter:
    """Counters `entities.resolve_kind` bumps (it only touches attributes that exist)."""

    def __init__(self) -> None:
        self.kinds_created = 0
        self.kinds_reused = 0
        self.kinds_broader = 0
        self.kind_alt_labels = 0
        self.kinds_close_match = 0
        self.kinds_dropped_meta = 0
        self.kinds_wordnet = 0
        self.entity_concepts_created = 0
