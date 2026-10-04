"""
Step 1b — Relation Extraction: Fast Path (Universal Verb Patterns)

Zero LLM cost. Reuses spaCy doc from Step 1 — no double parse.
Extracts nsubj → verb → dobj triples, matches verb lemma to named relation types.
"""

VALID_RELATION_TYPES = {
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
}

VERB_PATTERNS: dict[str, str] = {
    "require":     "REQUIRES",
    "need":        "REQUIRES",
    "depend":      "REQUIRES",
    "necessitate": "REQUIRES",
    "enable":      "ENABLES",
    "allow":       "ENABLES",
    "support":     "ENABLES",
    "facilitate":  "ENABLES",
    "permit":      "ENABLES",
    "replace":     "REPLACES",
    "supersede":   "REPLACES",
    "deprecate":   "REPLACES",
    "override":    "REPLACES",
    "contradict":  "CONTRADICTS",
    "conflict":    "CONTRADICTS",
    "violate":     "CONTRADICTS",
    "negate":      "CONTRADICTS",
    "undermine":   "CONTRADICTS",
    "contain":     "PART_OF",
    "include":     "PART_OF",
}


# B460: "We migrated from X to Y" names the retired value first. A move verb
# with both a "from" and a "to" object means Y REPLACES X.
MOVE_VERBS = {"migrate", "switch", "move", "transition", "upgrade", "change"}

# B466: "replace X with Y" / "swap X for Y" name the retired value as the
# object and the new one after the preposition, whoever does the replacing.
# Per verb, the prepositions that introduce the new value; "substitute X for Y"
# is the reverse (X takes Y's place), so its "for" introduces the old value.
SWAP_VERBS: dict[str, dict[str, str]] = {
    "replace":    {"with": "new"},
    "swap":       {"with": "new", "for": "new"},
    "substitute": {"with": "new", "for": "old"},
    "exchange":   {"for": "new"},
    "trade":      {"for": "new"},
}
# "replace X with Y" means Y in X's place however the parser attaches "with Y"
# (it hangs it on X in "Replace Memcached with Redis cluster on port 6379");
# "swap X with Y" does not ("swapped seats with the other team").
_PREP_ON_OBJECT = {"replace", "substitute"}


_NAME_PARTS = {"compound", "nummod", "amod", "appos", "flat", "nmod", "quantmod"}
_NAME_PUNCT = {"-", "/", "."}
_BREAK = set(":;,()")


def _span_text(tok, doc) -> str:
    """The name a token stands for: the token plus the adjacent modifiers that
    are part of the name ("Vue 2", "PostgreSQL 14", "us-west-2"), then widened
    to whole written words -- tokens with no space between them, since
    "eu-central-1" parses as three tokens. Noun chunks alone drop the version
    ("PostgreSQL" for "PostgreSQL 14"), and the version is the part that tells
    two values apart."""
    parts, stack = {tok.i}, [tok]
    while stack:
        for c in stack.pop().children:
            if c.dep_ in _NAME_PARTS or (c.dep_ == "punct" and c.text in _NAME_PUNCT):
                parts.add(c.i)
                stack.append(c)
    lo = hi = tok.i  # the contiguous run of name parts around the token
    while lo - 1 in parts:
        lo -= 1
    while hi + 1 in parts:
        hi += 1
    while lo > 0 and not doc[lo - 1].whitespace_ and doc[lo - 1].text not in _BREAK:
        lo -= 1
    while hi + 1 < len(doc) and not doc[hi].whitespace_ and doc[hi + 1].text not in _BREAK | {"."}:
        hi += 1
    return doc[lo:hi + 1].text


def _prep_object(verb, prep_word: str):
    for c in verb.children:
        if c.dep_ == "prep" and c.lower_ == prep_word:
            return next((g for g in c.children if g.dep_ == "pobj"), None)
    return None


def _relation(head_tok, relation_type: str, tail_tok, doc) -> dict:
    return {
        "head":          _span_text(head_tok, doc),
        "relation_type": relation_type,
        "tail":          _span_text(tail_tok, doc),
        "confidence":    0.85,
        "inferred_by":   "system",
    }


def _swap(verb, doc) -> list[dict] | None:
    """B466: the replacement in "replace X with Y", "swap X for Y", and their
    passives ("X was replaced with Y"). X is the object -- or the passive
    subject -- and the subject, if any, only did the replacing: "We replaced
    Memcached with Redis" used to give "We REPLACES Memcached", and the
    imperative "Replace Memcached with Redis" gave nothing.
    None when the verb has no such frame; [] when it is negated ("we did not
    replace X with Y" states no replacement, by Y or by "we")."""
    if any(c.dep_ == "agent" for c in verb.children):
        return None  # "X was replaced by Y with Z": the passive reading's Y
    patient = next((c for c in verb.children if c.dep_ in ("dobj", "nsubjpass")), None)
    if patient is None:
        return None
    lemma = verb.lemma_.lower()
    for prep_word, role in SWAP_VERBS[lemma].items():
        other = _prep_object(verb, prep_word)
        if other is None and lemma in _PREP_ON_OBJECT and patient.dep_ == "dobj":
            other = _prep_object(patient, prep_word)
        if other is not None:
            if any(c.dep_ == "neg" for c in verb.children):
                return []
            new, old = (other, patient) if role == "new" else (patient, other)
            return [_relation(new, "REPLACES", old, doc)]
    return None


def extract_relations(doc, entities: list[dict]) -> list[dict]:
    """
    Walk the dep tree for verb patterns:
      - active:   nsubj -> VERB -> dobj/attr/pobj    ("A replaced B": A REPLACES B)
      - passive:  nsubjpass <- VERB -> agent "by" X  ("B was replaced by A": A REPLACES B)
      - move:     VERB from X to Y                   ("migrated from B to A": A REPLACES B)
      - swap:     VERB X with/for Y                  ("replaced B with A": A REPLACES B)
    Returns list of {head, relation_type, tail, confidence, inferred_by}.
    Empty list = Step 3b eligibility check will fire.

    B460: the passive subject is the relation's TAIL. It used to be taken as
    the head, and passive and move sentences -- the usual way a supersession
    is stated ("Zipkin has been replaced by OpenTelemetry", "migrated from
    PostgreSQL 14 to PostgreSQL 16") -- produced nothing here, so Step 3b's
    LLM guessed, and it named the retired value the winner.
    """
    relations = []

    for token in doc:
        if token.pos_ != "VERB":
            continue
        lemma = token.lemma_.lower()

        if lemma in MOVE_VERBS:
            old_tok, new_tok = _prep_object(token, "from"), _prep_object(token, "to")
            if old_tok is not None and new_tok is not None:
                relations.append(_relation(new_tok, "REPLACES", old_tok, doc))
            continue

        if lemma in SWAP_VERBS:
            swap = _swap(token, doc)
            if swap is not None:
                relations.extend(swap)
                continue

        relation_type = VERB_PATTERNS.get(lemma)
        if not relation_type:
            continue

        # The subject nearest the verb: "Final decision: X has been replaced
        # by Y" parses both "decision" and X as passive subjects.
        subjects = [c for c in token.children if c.dep_ in ("nsubj", "nsubjpass")]
        if not subjects:
            continue
        subj = min(subjects, key=lambda c: abs(token.i - c.i))
        if subj.dep_ == "nsubjpass":
            agent = next((c for c in token.children if c.dep_ == "agent"), None)
            actor = next((g for g in agent.children if g.dep_ == "pobj"), None) if agent is not None else None
            if actor is not None:
                relations.append(_relation(actor, relation_type, subj, doc))
            continue

        obj = next((c for c in token.children if c.dep_ in ("dobj", "attr", "pobj")), None)
        if obj is not None:
            relations.append(_relation(subj, relation_type, obj, doc))

    return relations
