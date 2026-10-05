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

# B466: "replace X with Y" names the retired value as the OBJECT and the new
# one after a preposition; the subject ("We replaced ...") is neither. verb ->
# prepositions that introduce the new value.
WITH_VERBS = {"replace": ("with", "by"), "swap": ("for", "with"), "exchange": ("for",)}
# "substitute Y for X": the object is the NEW value.
SUBSTITUTE_VERBS = {"substitute": "for"}
# B466: "X is deprecated ... migrate to Y" -- retired value as the subject of
# one of these, the new one as a move verb's "to" object.
RETIRE_VERBS = {"deprecate", "retire", "sunset", "decommission", "discontinue"}


_NAME_PARTS = {"compound", "nummod", "amod", "appos", "flat", "nmod", "quantmod"}
_NAME_PUNCT = {"-", "/", "."}
_BREAK = set(":;,()")


def _span(tok, doc):
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
    return doc[lo:hi + 1]


def _is_name(span) -> bool:
    """B464: the span names something -- a proper noun, a noun capitalized
    mid-sentence ("Graphite", "REST", "gRPC"), a version or other numbered name
    ("Python 3.12", "eu-central-1", "Route53"), or a word the model's
    vocabulary does not know ("pytest", "yapf"). Common nouns ("the new
    version", "the old one", "the team") are not names."""
    has_vectors = span.vocab.vectors.shape[0] > 0  # no vectors (sm models): OOV says nothing
    return any(
        t.pos_ == "PROPN"
        or (t.pos_ == "NOUN" and not t.is_sent_start and any(c.isupper() for c in t.text))
        or any(c.isdigit() for c in t.text)
        or (has_vectors and t.is_alpha and not t.has_vector)
        for t in span if not (t.is_punct or t.is_space)
    )


def _prep_object(verb, prep_word: str):
    for c in verb.children:
        if c.dep_ == "prep" and c.lower_ == prep_word:
            return next((g for g in c.children if g.dep_ == "pobj"), None)
    return None


def _prep_objects_under(verb, prep_word: str) -> list:
    """`prep_word` objects anywhere under `verb`: the parser often hangs "to
    Y" off the verb's object ("migrate serialization to MessagePack")."""
    return [g for t in verb.subtree if t.dep_ == "prep" and t.lower_ == prep_word
            for g in t.children if g.dep_ == "pobj"]


def _deprecated_then_moved(doc) -> list[dict]:
    """B466: "X is deprecated; migrate serialization to Y" (one sentence or
    two) -> Y REPLACES X, but only when the message names exactly one retired
    value and exactly one move target, both named values. A move verb with
    its own "from" is the move pattern's, not this one's."""
    retired, targets = [], []
    for tok in doc:
        lemma = tok.lemma_.lower()
        if lemma in RETIRE_VERBS:
            subjects = [c for c in tok.children if c.dep_ in ("nsubj", "nsubjpass")]
            if not subjects and tok.dep_ == "acomp":  # "X is deprecated" parsed as copula + ADJ
                subjects = [c for c in tok.head.children if c.dep_ in ("nsubj", "nsubjpass")]
            if subjects:
                retired.append(min(subjects, key=lambda c: abs(tok.i - c.i)))
        elif lemma in MOVE_VERBS and _prep_object(tok, "from") is None:
            # any part of speech: "migrate serialization to Y" after a
            # semicolon parses "migrate" as a compound noun modifying
            # "serialization", with "to Y" hanging off that noun
            found = _prep_objects_under(tok, "to")
            if not found and tok.dep_ == "compound":
                found = _prep_objects_under(tok.head, "to")
            targets.extend(found)
    if len(retired) != 1 or len(targets) != 1:
        return []
    old, new = retired[0], targets[0]
    if not (_is_name(_span(old, doc)) and _is_name(_span(new, doc))):  # not "the new wiki"
        return []
    rel = _relation(new, "REPLACES", old, doc)
    return [rel] if rel["head"].lower() != rel["tail"].lower() else []


def _relation(head_tok, relation_type: str, tail_tok, doc) -> dict:
    head, tail = _span(head_tok, doc), _span(tail_tok, doc)
    return {
        "head":          head.text,
        "relation_type": relation_type,
        "tail":          tail.text,
        "confidence":    0.85,
        "inferred_by":   "system",
        # B464: both endpoints are names, so the relation can stand on its own
        # (the orchestrator keeps such a REPLACES even when Step 2 drops its entities).
        "names":         _is_name(head) and _is_name(tail),
    }


def extract_relations(doc, entities: list[dict]) -> list[dict]:
    """
    Walk the dep tree for verb patterns:
      - active:   nsubj -> VERB -> dobj/attr/pobj    ("A replaced B": A REPLACES B)
      - passive:  nsubjpass <- VERB -> agent "by" X  ("B was replaced by A": A REPLACES B)
      - move:     VERB from X to Y                   ("migrated from B to A": A REPLACES B)
      - with:     replace X with Y / swap X for Y    ("we replaced B with A": A REPLACES B)
      - retire + move, one message: "B is deprecated; migrate ... to A"   (A REPLACES B)
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

        # B466: "replace X with Y" (active, imperative or passive): the new
        # value follows the preposition; the subject plays no part. Before,
        # "We replaced Memcached with Redis" gave "We REPLACES Memcached".
        # A passive "by" agent is the new value and "with Y" then describes it
        # ("replaced by gRPC with Protobuf v3"): that is the passive rule's.
        has_agent = any(c.dep_ == "agent" for c in token.children)
        if (lemma in WITH_VERBS or lemma in SUBSTITUTE_VERBS) and not has_agent:
            olds = [c for c in token.children if c.dep_ in ("dobj", "nsubjpass")]
            old = min(olds, key=lambda c: abs(token.i - c.i)) if olds else None
            preps = WITH_VERBS.get(lemma) or (SUBSTITUTE_VERBS[lemma],)
            new = next((o for p in preps if (o := _prep_object(token, p)) is not None), None)
            if lemma in SUBSTITUTE_VERBS:
                old, new = new, next((c for c in token.children if c.dep_ == "dobj"), None)
            if old is not None and new is not None:
                relations.append(_relation(new, "REPLACES", old, doc))
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

    if not any(r["relation_type"] == "REPLACES" for r in relations):
        relations.extend(_deprecated_then_moved(doc))
    return relations
