"""B547: the question is analysed once.

Each retrieval stage used to resolve the question's Concepts by itself, B524 had its own subject/kind/shape
parsing, and the L3 screen a third. This module is the one analysis: a pure, rule-based function (syntax and
closed-class words, no model call, no content word fitted to a dataset) over a read-through snapshot of the
graph's closed sets. `compile_bundle` runs it once when `[retrieval] question_analysis` is on (env
`CAMPY_QUESTION_ANALYSIS`, default off), puts the result on the bundle, and the stages read it.

What it says about a question:

  * `shape`: count, list, latest, when, before_after, yes_no, open (and the rule that fired);
  * `subjects`: the person (or coordinated people, `tie`) the question is about, found by lookup in the
    graph's person set; `subject_unresolved` names a person-like name that is not in the graph;
  * the KIND asked for (`kind_id`) in the closed kind set, with `kind_match` full or head;
  * `concepts`: every existing Concept the question names, longest span first, never overlapping.

Persons. A Concept is a person when the graph says so (`schema_org_type` Person), or when B544 stored
`ner_label` PERSON AND spaCy tags the same span PERSON in the question (two independent taggers agree). The
raw tagger label alone is not trusted (B549: it labels Yoga, Art, Jasper, Aerosmith ... PERSON). The module
works whether or not B544 has admitted entities: without `ner_label` there are simply no weak persons.

The text analysed is the question up to its first "?": the harness appends an instruction sentence to
category-2 questions, which is not part of the question (B551).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

from campy.brain.hippocampus.concept_links import norm_key
from campy.brain.hippocampus.kinds import META_NOUNS

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------
# Closed-class word sets (function-word-like; none fitted to a benchmark question). One block, a test
# per member (tests/test_b547_question_analysis.py).
# ---------------------------------------------------------------------------------------------------
AUX = frozenset("do does did is are was were am has have had will would can could should might may shall must".split())
MODAL_INFER = frozenset("would might could may should".split())
WH = frozenset("what which who whom whose when where why how".split())
TYPE_NOUNS = frozenset("kind type sort form variety category kinds types sorts forms varieties categories".split())
TIME_UNITS = frozenset("second minute hour day week month year decade season semester".split())
TIME_HEADS = frozenset("date day year month week time season".split())
NOT_KIND = META_NOUNS | frozenset({"time", "thing", "number", "reason", "idea", "advice", "amount", "ones", "people_in_general"})
RECENCY = frozenset("current currently latest newest now nowadays presently".split())
BEFORE_AFTER = frozenset("before after since until".split())
IRREG = {"people": "person", "children": "child", "men": "man", "women": "woman", "feet": "foot", "mice": "mouse"}
CONNECT = frozenset("of the and in a an for to at on de la von van & '".split())
STOP_AFTER = frozenset("in at on to from with for by about during into over under as than while when".split())
# Words ending in "s" that are not plurals.
NONPL = frozenset(
    "series species news means does was has is this his its us yes as always perhaps across besides towards thus less "
    "unless status business class glass focus bonus genius famous various previous serious delicious nervous curious "
    "anxious jealous religious mass kiss dress stress success process progress loss boss address press chess guess "
    "witness".split())

NE_LABELS = {"WORK_OF_ART", "GPE", "ORG", "PRODUCT", "LOC", "FAC", "EVENT", "NORP"}
VALUE_LABELS = {"DATE", "TIME", "CARDINAL", "ORDINAL", "QUANTITY", "MONEY", "PERCENT"}
NP_TAGS = {"JJ", "JJR", "JJS", "NN", "NNS", "NNP", "NNPS", "CD", "HYPH", "VBG", "VBN"}

SHAPES = ("count", "list", "latest", "when", "before_after", "yes_no", "open")


def question_analysis_enabled(config: dict | None) -> bool:
    """`[retrieval] question_analysis` (default false; env `CAMPY_QUESTION_ANALYSIS=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("question_analysis", False))


@dataclass(frozen=True)
class QuestionLexicon:
    """A read-through snapshot of the graph's closed sets, never kept across bundles."""
    index: dict[str, tuple[str, ...]] = field(default_factory=dict)   # norm_key -> Concept ids (labels, altLabels, prefLabels)
    labels: dict[str, str] = field(default_factory=dict)              # Concept id -> text_raw
    kinds: dict[str, tuple[str, ...]] = field(default_factory=dict)   # norm_key -> kind Concept ids
    kind_labels: dict[str, str] = field(default_factory=dict)         # kind id -> prefLabel
    persons: dict[str, str] = field(default_factory=dict)             # lower name -> Concept id
    weak_person_ids: frozenset = frozenset()                          # persons whose only evidence is ner_label PERSON

    @property
    def person_ids(self) -> frozenset:
        return frozenset(self.persons.values())


@dataclass(frozen=True)
class QuestionAnalysis:
    question: str
    text: str                                    # the analysed sentence: the question up to its first "?"
    shape: str = "open"
    shape_rule: str = ""
    wh: str | None = None
    modifiers: tuple = ()                        # inferential, choice, recency, duration, frequency
    subject_id: str | None = None
    subject: str | None = None
    subjects: tuple = ()                         # ({"id","label"}, ...) resolved people, anchors first, then by role
    anchor_ids: tuple = ()                       # the Concept ids that anchor: the coordinated group (tie) or [subject_id]
    tie: bool = False
    subject_unresolved: tuple = ()               # person-like names not in the graph that outrank the subject
    kind_text: str | None = None
    kind_id: str | None = None
    kind_label: str | None = None
    kind_match: str = ""                         # "full" (the whole phrase is a kind) | "head" (a leading modifier was dropped)
    concepts: tuple = ()                         # ({"id","label","span","source","role"}, ...) longest span first
    bound: dict | None = None
    dates: tuple = ()

    @property
    def concept_ids(self) -> list[str]:
        return [c["id"] for c in self.concepts]

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("modifiers", "subjects", "anchor_ids", "subject_unresolved", "concepts", "dates"):
            d[k] = list(d[k])
        return d

    def log_fields(self) -> dict:
        """What the daemon log may carry: no question text."""
        return {"shape": self.shape, "shape_rule": self.shape_rule, "has_subject": self.subject_id is not None,
                "tie": self.tie, "unresolved": len(self.subject_unresolved), "kind_id": self.kind_id,
                "kind_match": self.kind_match, "n_concepts": len(self.concepts)}


# ---------------------------------------------------------------------------------------------------
# The lexicon (graph reads only, through NamedQueries)
# ---------------------------------------------------------------------------------------------------

async def load_lexicon(gw) -> QuestionLexicon:
    """The Concept index (labels, prefLabels, altLabels of every live Concept), the kind set and the person
    set, read fresh from the graph. Registered NamedQueries only (campy-graph rule 7)."""
    from campy.brain.hippocampus.kinds import load_kinds

    rows = await gw.run("question_analysis.concept_lexicon")
    rows = sorted(rows, key=lambda r: str(r.get("concept_id")))
    labels: dict[str, str] = {}
    index: dict[str, list[str]] = {}
    strong: dict[str, str] = {}
    weak: dict[str, str] = {}
    for r in rows:
        cid, text = str(r["concept_id"]), str(r.get("text_raw") or "")
        labels[cid] = text
        key = norm_key(text)
        if key and cid not in index.setdefault(key, []):
            index[key].append(cid)
        if str(r.get("schema_org_type") or "").endswith("Person"):
            strong.setdefault(text.lower(), cid)
        elif str(r.get("ner_label") or "") == "PERSON":
            weak.setdefault(text.lower(), cid)
    for r in sorted(await gw.run("question_analysis.concept_surfaces"),
                    key=lambda r: (str(r.get("concept_id")), str(r.get("surface")))):
        key = norm_key(str(r.get("surface") or ""))
        cid = str(r["concept_id"])
        if key and cid in labels and cid not in index.setdefault(key, []):
            index[key].append(cid)
    persons = {**weak, **strong}
    weak_ids = frozenset(set(weak.values()) - set(strong.values()))
    kinds = await load_kinds(gw)
    kind_keys: dict[str, list[str]] = {}
    kind_labels: dict[str, str] = {}
    for k in kinds.values():
        kind_labels[k.concept_id] = k.pref
        for key in sorted(k.keys()):
            kind_keys.setdefault(key, []).append(k.concept_id)
    return QuestionLexicon(
        index={k: tuple(v) for k, v in index.items()}, labels=labels,
        kinds={k: tuple(sorted(v)) for k, v in kind_keys.items()}, kind_labels=kind_labels,
        persons=persons, weak_person_ids=weak_ids)


# ---------------------------------------------------------------------------------------------------
# The analysis (pure)
# ---------------------------------------------------------------------------------------------------

_NLP = None


def _default_nlp():
    global _NLP
    if _NLP is None:
        from campy.brain.temporal_lobe.loop.step1_ner import get_nlp
        _NLP = get_nlp()
    return _NLP


def first_sentence(q: str) -> str:
    """The question up to its first "?" (backtick and curly apostrophes normalised)."""
    q = " ".join(str(q or "").replace("`", "'").replace("’", "'").split())
    i = q.find("?")
    return q[:i + 1] if i >= 0 else q


def _lem(tok):
    w = tok.text.lower()
    if w in IRREG:
        return IRREG[w]
    return tok.lemma_.lower() if tok.tag_ in ("NNS", "NNPS") else w


def _plural(t):
    if t.tag_ in ("NNS", "NNPS"):
        return True
    w = t.lower_
    return (t.tag_ in ("VBZ", "VBP", "FW", "NN") and len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is"))
            and w not in NONPL and t.dep_ in ("dobj", "pobj", "nsubj", "dative", "pcomp"))


def _np_run(doc, start, person_idx, allow_of=True, force_first=False):
    """Tokens from `start` forming the wh noun phrase: adjectives/nouns/numbers, passing through "kind of".
    Returns (tokens, head) or ([], None)."""
    out = []
    i = start
    # fronted wh-NP ("What LGBTQ+ events has Caroline ..."): an auxiliary follows, so every token up to it is
    # part of the phrase whatever the tagger says
    aux_follows = any(doc[m].lower_ in AUX for m in range(start + 1, len(doc)))
    while i < len(doc):
        t = doc[i]
        if i in person_idx:
            break
        if aux_follows and t.lower_ == "of" and out:
            if allow_of and out[-1].lower_ in TYPE_NOUNS:
                out = []
                i += 1
                continue
            break
        if aux_follows and not t.is_punct and t.lower_ not in AUX and t.lower_ not in STOP_AFTER and t.lower_ != "of" \
                and t.tag_ not in ("PRP", "PRP$", "CC", "DT", "IN", "RB", "WDT", "WP", "WRB", "TO", "MD"):
            out.append(t)
            i += 1
            continue
        if t.is_punct and t.text in ("+", "-", "/", "&") and out and not doc[i - 1].whitespace_ and i + 1 < len(doc):
            i += 1
            continue
        if (t.tag_ in NP_TAGS or (force_first and i == start and t.lower_ not in AUX)) and not t.is_punct:
            out.append(t)
            i += 1
            continue
        if allow_of and t.lower_ == "of" and out and out[-1].lower_ in TYPE_NOUNS:
            i += 1
            out = []                      # the type-noun is dropped: the kind is what follows "of"
            continue
        break
    while len(out) > 1 and out[-1].tag_ not in ("NN", "NNS", "NNP", "NNPS") and not _plural(out[-1]):
        out.pop()
    if not out:
        return [], None
    return out, out[-1]


def _kind_candidates(toks):
    """Longest-first phrases from a run: drop leftmost modifiers one by one."""
    words = [_lem(t) if t is toks[-1] else t.text.lower() for t in toks]
    return [" ".join(words[i:]) for i in range(len(words))]


def _fts_terms(text: str):
    from campy.brain.hippocampus.graph.vector_store import fts_content_terms
    return fts_content_terms(text)


def analyse_question(question: str, lex: QuestionLexicon, nlp=None) -> QuestionAnalysis:
    """The one analysis of a question. Pure: no I/O, no model; `nlp` is a spaCy pipeline (default: the NER step's)."""
    nlp = nlp or _default_nlp()
    text = first_sentence(question)
    doc = nlp(text)
    toks = list(doc)
    low = [t.lower_ for t in toks]
    modifiers: list[str] = []

    # --- people (closed set) ------------------------------------------------
    person_idx: set[int] = set()
    mentions: list[tuple] = []     # (start, end, id, name)
    ner_person: set[int] = set()
    for e in doc.ents:
        if e.label_ == "PERSON":
            ner_person.update(range(e.start, e.end))
    i = 0
    while i < len(toks):
        hit = None
        for n in (3, 2, 1):
            if i + n <= len(toks):
                name = re.sub(r"'s$", "", " ".join(low[i:i + n]))
                cid = lex.persons.get(name)
                if cid and toks[i].tag_ in ("NNP", "NNPS", "NN", "JJ", "VB") and (
                        cid not in lex.weak_person_ids or any(x in ner_person for x in range(i, i + n))):
                    hit = (i, i + n, cid, name)
                    break
        if hit:
            mentions.append(hit)
            person_idx.update(range(hit[0], hit[1]))
            i = hit[1]
        else:
            i += 1

    # --- wh word and the wh noun phrase ---------------------------------------
    wh_i = next((k for k, w in enumerate(low) if w in WH), None)
    # a leading adjunct ("Based on the conversation, did X ...", "Considering Y, what ...") is skipped
    lead = 0
    if low and low[0] not in AUX and low[0] not in WH:
        for k, w in enumerate(low):
            if w == "," and k + 1 < len(low) and (low[k + 1] in AUX or low[k + 1] in WH):
                lead = k + 1
                break
    if lead:
        wh_i = next((k for k in range(lead, len(low)) if low[k] in WH), None)
    wh = low[wh_i] if wh_i is not None else None
    first_aux = bool(low) and low[lead] in AUX
    run, head = [], None
    shape, rule = None, ""

    if first_aux:
        shape, rule = "yes_no", "aux_initial"
        if low[lead] in MODAL_INFER:
            modifiers.append("inferential")
        if "or" in low:
            shape, rule = "open", "aux_initial_or_choice"
            modifiers.append("choice")
    elif wh == "how":
        nxt = low[wh_i + 1] if wh_i + 1 < len(low) else ""
        if nxt in ("many", "much"):
            run, head = _np_run(doc, wh_i + 2, person_idx, allow_of=False)
            if head is not None and any(_lem(t) in TIME_UNITS or t.lower_ in ("months", "years", "days", "weeks") for t in run):
                shape, rule = "when", "how_many_time_unit"
                modifiers.append("duration")
                run, head = [], None
            else:
                shape, rule = "count", "how_many"
        elif nxt == "long":
            shape, rule = "when", "how_long"
            modifiers.append("duration")
        elif nxt == "often":
            shape, rule = "when", "how_often"
            modifiers.append("frequency")
    elif wh == "when":
        shape, rule = "when", "when"
    elif wh in ("what", "which"):
        j = wh_i + 1
        nxt = low[j] if j < len(low) else ""
        m0 = j
        while m0 < len(low) and low[m0] in AUX | {"be", "being", "been"}:
            m0 += 1
        if m0 < len(low) and low[m0] in ("a", "an") and m0 > j:
            r, h = _np_run(doc, m0 + 1, person_idx, allow_of=False)
            if h is not None and not _plural(h):
                run, head = r, h
                shape, rule = "open", "predicate_nominal_indefinite"
        elif nxt in AUX or nxt in ("is", "are"):
            # copular "What are X's N": the noun after the be-verb is the asked-for set when plural
            if nxt in ("are", "were", "is", "was"):
                m = j + 1
                while m < len(toks) and (toks[m].tag_ in ("DT", "PRP$", "POS") or m in person_idx or toks[m].lower_ == "'s"):
                    m += 1
                r, h = _np_run(doc, m, person_idx, allow_of=False)
                if h is not None and _lem(h) in META_NOUNS and h.i + 1 < len(toks) and toks[h.i + 1].lower_ == "of":
                    m = h.i + 2
                    while m < len(toks) and (toks[m].tag_ in ("DT", "PRP$", "POS") or m in person_idx or toks[m].lower_ == "'s"):
                        m += 1
                    r2, h2 = _np_run(doc, m, person_idx, allow_of=False)
                    if h2 is not None:
                        r, h = r2, h2
                if h is not None and _plural(h):
                    run, head = r, h
                    shape, rule = "list", "copular_plural_head"
        else:
            run, head = _np_run(doc, j, person_idx, force_first=(toks[wh_i].dep_ == "det" and toks[wh_i].head.i == j))
            if head is not None:
                if head.tag_ == "NN" and _lem(head) in TIME_HEADS and len(run) == 1:
                    shape, rule = "when", "wh_time_noun"
                    run, head = [], None
                elif _plural(head):
                    shape, rule = "list", "wh_plural_head"
    if shape is None:
        shape, rule = "open", "default"

    # before/after marker, recency (modifiers; the shape only when nothing stronger applies)
    bound = None
    for k, t in enumerate(toks):
        if t.lower_ in BEFORE_AFTER and t.tag_ == "IN" and k > 0:
            bound = {"rel": t.lower_, "text": " ".join(x.text for x in toks[k + 1:] if not x.is_punct)}
            break
    if any(w in RECENCY for w in low):
        modifiers.append("recency")
    if shape == "open" and bound:
        shape, rule = "before_after", "bound_marker"
    elif shape == "open" and "recency" in modifiers:
        shape, rule = "latest", "recency_marker"

    # --- kind ---------------------------------------------------------------
    kind_text = kind_id = kind_label = None
    kind_match = ""
    if run and head is not None and shape not in ("when", "yes_no"):
        hl = _lem(head)
        if hl not in NOT_KIND and hl not in TIME_UNITS and head.tag_ not in ("CD",):
            cands = _kind_candidates(run)
            kind_text = " ".join([t.text.lower() for t in run[:-1]] + [_lem(head)])
            for ci, c in enumerate(cands):
                ids = lex.kinds.get(norm_key(c))
                if ids:
                    kind_match = "full" if ci == 0 else "head"
                    kind_id = ids[0]
                    kind_label = lex.kind_labels.get(ids[0])
                    break

    # --- people -> subject --------------------------------------------------
    def rank(m):
        s, e, _cid, _name = m
        cur, hops = toks[e - 1], 0
        while cur.dep_ in ("conj", "compound", "appos") and cur.head is not cur and hops < 4:
            cur = cur.head
            hops += 1
        d = cur.dep_
        if d == "poss":
            r = 0 if cur.head.dep_ in ("nsubj", "nsubjpass") else 1
        elif d in ("nsubj", "nsubjpass"):
            r = 0
        elif d in ("dobj", "pobj", "dative", "attr"):
            r = 2
        else:
            r = 3
        depth = sum(1 for a in cur.ancestors if a.pos_ in ("VERB", "AUX"))
        return (r, depth, s)

    def label_of(cid, name):
        return lex.labels.get(cid) or (name.title() if name.islower() else name)

    def distinct(ms):
        seen, ids = [], set()
        for m in ms:
            if m[2] not in ids:
                ids.add(m[2])
                seen.append({"id": m[2], "label": label_of(m[2], m[3])})
        return seen

    ms = sorted(mentions, key=rank)
    subjects = distinct(ms)
    anchor_ids: list[str] = []
    tie = False
    if ms:
        # "A and B" (two people joined by 'and' / a comma): the whole group anchors
        groups: list[list] = []
        for m in sorted(mentions, key=lambda m: m[0]):
            prev = groups[-1][-1] if groups else None
            if prev and prev[1] < m[0] and all(w in ("and", ",", "or", "&") for w in low[prev[1]:m[0]]) and m[0] - prev[1] <= 2:
                groups[-1].append(m)
            else:
                groups.append([m])
        top = next(g for g in groups if ms[0] in g)
        if len(top) > 1:
            ms = top + [m for m in ms if m not in top]
            subjects = distinct(ms)
            tie = True
            anchor_ids = [s["id"] for s in distinct(top)]
        else:
            anchor_ids = [ms[0][2]]
    subject_id = ms[0][2] if ms else None
    subject = subjects[0]["label"] if subjects else None

    # unresolved person-like names that outrank the subject
    unresolved: list[str] = []
    for e in doc.ents:
        if e.label_ == "PERSON" and not any(s <= e.start < en for s, en, _, _ in mentions):
            if e.text.lower() in lex.persons or norm_key(e.text) in lex.index:
                continue
            if not mentions or e.start < ms[0][0]:
                unresolved.append(e.text)

    dates = tuple(e.text for e in doc.ents if e.label_ in ("DATE", "TIME"))

    # --- concepts (closed set; never creates) --------------------------------
    value_idx: set[int] = set()
    for e in doc.ents:
        if e.label_ in VALUE_LABELS:
            value_idx.update(range(e.start, e.end))
    cand = []   # (start, end, text, source)
    for s_, e_, _cid, _nm in mentions:
        cand.append((s_, e_, " ".join(x.text for x in toks[s_:e_]), "person"))
    for e in doc.ents:
        if e.label_ in NE_LABELS:
            cand.append((e.start, e.end, e.text, "ner"))
    for q in re.finditer(r'"([^"]{2,80})"', text):
        cand.append((None, None, q.group(1), "quoted"))
    # title-case runs, interior connectors allowed, up to 10 tokens
    k = 0
    while k < len(toks):
        t = toks[k]
        if t.text[:1].isupper() and k > 0 and k not in person_idx and k not in value_idx and t.lower_ not in WH:
            e_ = k + 1
            while e_ < min(len(toks), k + 10):
                nt = toks[e_]
                if nt.text[:1].isupper() and e_ not in person_idx:
                    e_ += 1
                elif nt.lower_ in CONNECT and e_ + 1 < len(toks) and toks[e_ + 1].text[:1].isupper():
                    e_ += 2
                else:
                    break
            if e_ - k >= 2:
                cand.append((k, e_, " ".join(x.text for x in toks[k:e_]), "titlecase"))
            k = e_
        else:
            k += 1
    for nc in doc.noun_chunks:
        s, e_ = nc.start, nc.end
        while s < e_ and (toks[s].tag_ in ("DT", "PRP$", "PRP", "WDT", "WP", "CD", "POS") or toks[s].lower_ in WH):
            s += 1
        if e_ - s >= 1:
            cand.append((s, e_, " ".join(x.text for x in toks[s:e_]), "chunk"))
    for n in (3, 2, 1):
        for s in range(0, len(toks) - n + 1):
            seg = toks[s:s + n]
            if _fts_terms(seg[0].text) and _fts_terms(seg[-1].text) and not any(x.is_punct for x in seg) \
                    and seg[-1].tag_ in ("NN", "NNS", "NNP", "NNPS") and _lem(seg[-1]) not in NOT_KIND \
                    and seg[-1].lower_ not in AUX and seg[0].tag_ != "POS" and not (n == 1 and seg[0].lower_ in WH):
                cand.append((s, s + n, " ".join(x.text for x in seg), "ngram"))
    prio = {"person": 0, "quoted": 0, "ner": 1, "titlecase": 1, "chunk": 2, "ngram": 3}

    def length(c):
        return (c[1] - c[0]) if c[0] is not None else len(c[2].split())
    cand.sort(key=lambda c: (0 if c[3] == "person" else 1, -length(c), prio[c[3]]))
    mention_ids = {m[2] for m in mentions}
    used: set[int] = set()
    concepts, seen_ids = [], set()
    for s, e_, span, src in cand:
        rng = set(range(s, e_)) if s is not None else set()
        if rng & used or (rng & value_idx):
            continue
        key = norm_key(span)
        ids = lex.index.get(key) if key else None
        if not ids:
            continue
        if all(w in WH or w in AUX for w in span.lower().split()):
            continue
        cid = ids[0]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        used |= rng
        if cid in lex.person_ids and (cid not in lex.weak_person_ids or cid in mention_ids):
            role = "person"
        else:
            role = "kind" if cid in lex.kind_labels else "entity"
        concepts.append({"id": cid, "label": lex.labels.get(cid, span), "span": span, "source": src, "role": role})

    return QuestionAnalysis(
        question=question, text=text, shape=shape, shape_rule=rule, wh=wh, modifiers=tuple(modifiers),
        subject_id=subject_id, subject=subject, subjects=tuple(subjects), anchor_ids=tuple(anchor_ids), tie=tie,
        subject_unresolved=tuple(unresolved), kind_text=kind_text, kind_id=kind_id, kind_label=kind_label,
        kind_match=kind_match, concepts=tuple(concepts), bound=bound, dates=dates)


async def analyse_for_bundle(db, query: str) -> QuestionAnalysis | None:
    """Load the lexicon and analyse `query`; None (and a warning) when anything fails, so the stages fall
    back to their own parsing exactly as with the flag off."""
    try:
        from campy.brain.hippocampus.graph.gateway import get_gateway

        analysis = analyse_question(query, await load_lexicon(get_gateway(db)))
        _logger.info("question_analysis %s", analysis.log_fields())
        return analysis
    except Exception as e:
        _logger.warning("Error in question analysis; stages parse the question themselves: %s", e)
        return None
