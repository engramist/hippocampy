"""
Shallow parse — engine-neutral tokenization + candidate-phrase chunking (B387).

Replaces the spaCy `Doc` interface between step1_ner.py and step1b_relations.py.
spaCy gave two things beyond raw NER that this module deliberately does NOT
try to replace with a general-purpose model:

  1. `doc.noun_chunks` (constituency-derived noun phrases)
  2. `token.dep_` / `token.pos_` (full dependency parse)

Gate 0 (backlog/B387.md) found no ONNX dependency parser that is both
Apache-2.0/MIT-licensed and cheaply portable to onnxruntime (biaffine parsers
need graph-based MST decoding outside the ONNX graph itself — out of scope
for this card). Instead this module implements the two things the rest of
the Loop actually consumes, without any ML model:

  - `shallow_chunks()`: a RAKE-style (Rose et al., 2010) candidate-phrase
    extractor. Maximal runs of tokens that are neither closed-class function
    words (determiners/prepositions/conjunctions/pronouns/auxiliaries) nor
    known governance-verb forms are treated as noun-chunk-equivalent spans.
    This is a real, if approximate, substitute for `doc.noun_chunks` — it is
    NOT a POS tagger, it only needs to know which words are *not* plausible
    content words, which is a much smaller and more stable set.

  - Governance-verb surface-form tagging: `VERB_PATTERNS` (relation-bearing
    verb lemmas -- REQUIRES/ENABLES/REPLACES/CONTRADICTS/PART_OF) is a small,
    fixed, closed set of ~19 regular verbs. step1b_relations.py never needed
    a general POS tagger either -- it only ever asked "is this token one of
    my governance verbs" (via `token.pos_ == "VERB"` + a lemma dict lookup).
    A hardcoded lexicon of each verb's regular inflections (base/-s/-es/-ed/
    -ing) answers that exact question deterministically, with zero model
    weights and zero RSS cost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Engine-neutral parse result (replaces the spaCy `Doc` interface)
# ---------------------------------------------------------------------------


@dataclass
class Token:
    text: str
    start: int          # char offset into ParsedText.text
    end: int
    is_verb: bool = False
    lemma: str | None = None   # populated only when is_verb is True


@dataclass
class ParsedText:
    """Engine-neutral replacement for a spaCy `Doc`. Carries just what
    step1b_relations.extract_relations() needs: the source text and a
    token stream with governance-verb tagging."""
    text: str
    tokens: list[Token] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Word tokens: alnum runs that may contain internal . + # - _ (so "PostgreSQL",
# "C++", "en-US", "v2.0" stay single tokens); everything else (punctuation,
# whitespace) is either a single-char punctuation token or dropped.
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+#-]*(?:\.[A-Za-z0-9_+#-]+)*")
_TOKEN_RE = re.compile(rf"{_WORD_RE.pattern}|[^\sA-Za-z0-9]")


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Whitespace/punctuation tokenizer with char offsets.
    Trailing sentence punctuation is naturally its own token (a period after
    a word is only absorbed into _WORD_RE when followed by another alnum
    run, e.g. "v2.0", not at a word/sentence boundary)."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Closed-class function words (chunk boundaries) — NOT a POS tagger, just
# the much smaller job of recognizing words that are never plausible
# content-word heads.
# ---------------------------------------------------------------------------

_DETERMINERS = {
    "a", "an", "the", "this", "that", "these", "those", "all", "some",
    "any", "no", "every", "each", "both", "either", "neither",
}
_PREPOSITIONS = {
    "in", "on", "at", "by", "for", "with", "from", "to", "of", "about",
    "across", "after", "against", "along", "among", "around", "as",
    "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "during", "except", "inside", "into", "near", "off", "over", "since",
    "through", "throughout", "toward", "towards", "under", "until", "up",
    "upon", "within", "without", "per", "via",
}
_CONJUNCTIONS = {
    "and", "or", "but", "nor", "so", "yet", "because", "although",
    "though", "while", "if", "unless", "whether",
}
_PRONOUNS = {
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "who", "whom", "whose", "which", "what",
}
_AUX = {
    "is", "are", "was", "were", "be", "been", "being", "am", "has", "have",
    "had", "do", "does", "did", "will", "would", "shall", "should", "can",
    "could", "may", "might", "must",
}

FUNCTION_WORDS = _DETERMINERS | _PREPOSITIONS | _CONJUNCTIONS | _PRONOUNS | _AUX

# Pronouns/stopwords to filter from the chunk fallback (moved here verbatim
# from step1_ner.py — still used there, kept in one place).
SKIP_CHUNKS = {"we", "i", "you", "they", "he", "she", "it", "us", "them",
               "this", "that", "these", "those", "one", "ones"}


# ---------------------------------------------------------------------------
# Governance-verb lexicon
#
# The relation-bearing verb *lemmas* live here (single source of truth).
# step1b_relations.py imports VERB_PATTERNS/VALID_RELATION_TYPES from this
# module so the surface-form lexicon below can never drift out of sync with
# the lemmas step1b actually looks for.
# ---------------------------------------------------------------------------

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


def _regular_inflections(lemma: str) -> set[str]:
    """Regular English verb conjugations for a base form. 17 of the 19
    VERB_PATTERNS lemmas are fully regular (-s/-es/-ed/-ing); the two
    exceptions (consonant-doubling "permit", irregular-past "override")
    are patched in via _IRREGULAR_FORMS below."""
    forms = {lemma}
    if lemma.endswith("e"):
        forms.add(lemma + "s")
        forms.add(lemma + "d")          # replace -> replaced
        forms.add(lemma[:-1] + "ing")   # replace -> replacing
    elif lemma.endswith(("s", "x", "z", "ch", "sh")):
        forms.add(lemma + "es")
        forms.add(lemma + "ed")
        forms.add(lemma + "ing")
    else:
        forms.add(lemma + "s")
        forms.add(lemma + "ed")
        forms.add(lemma + "ing")
    return forms


# Irregular forms the regular-suffix generator above gets wrong:
#   permit   -> doubles the final consonant (permitted/permitting, not
#               "permited"/"permiting")
#   override -> irregular past tense/participle, inherited from "ride"
#               (overrode/overridden, not "overrided")
_IRREGULAR_FORMS: dict[str, set[str]] = {
    "permit":   {"permitted", "permitting"},
    "override": {"overrode", "overridden", "overriding"},
}

# surface form (lowercase) -> lemma
_VERB_SURFACE_TO_LEMMA: dict[str, str] = {}
for _lemma in VERB_PATTERNS:
    for _form in _regular_inflections(_lemma) | _IRREGULAR_FORMS.get(_lemma, set()):
        _VERB_SURFACE_TO_LEMMA[_form] = _lemma


# ---------------------------------------------------------------------------
# Common (non-governance) verb forms — chunk-boundary use only.
#
# Without any POS tagger, a generic verb like "decided" or "extends" has no
# way to be told apart from a content word, so shallow_chunks() would
# otherwise glue it onto an adjacent noun ("React extends" as one bogus
# chunk instead of "React" as the entity). This list exists ONLY to fix
# that specific chunk-boundary problem for a curated set of high-frequency
# verbs seen in decision/dev-narration text (see backlog/B387.md Gate 0
# notes) — it is deliberately NOT exhaustive and does NOT feed
# VERB_PATTERNS/relation extraction (VALID_RELATION_TYPES stays scoped to
# the governance-verb lemmas above). Known trade-off: a handful of these
# are homographs that are sometimes used as nouns too ("release", "use",
# "talk", "search", "plan") -- in that rarer case this list will
# incorrectly treat the word as a chunk boundary rather than content. This
# is a heuristic, not a substitute for real POS tagging.
# ---------------------------------------------------------------------------

_COMMON_VERB_SURFACE_FORMS: set[str] = {
    # decide/use/choose family (directly motivated by B387 Gate 0 samples)
    "decide", "decides", "decided", "deciding",
    "use", "uses", "used", "using",
    "choose", "chooses", "chose", "chosen", "choosing",
    "base", "bases", "based", "basing",
    "release", "releases", "released", "releasing",
    "talk", "talks", "talked", "talking",
    "orchestrate", "orchestrates", "orchestrated", "orchestrating",
    "extend", "extends", "extended", "extending",
    "migrate", "migrates", "migrated", "migrating",
    "deploy", "deploys", "deployed", "deploying",
    "build", "builds", "built", "building",
    # general high-frequency dev/decision verbs
    "call", "calls", "called", "calling",
    "run", "runs", "ran", "running",
    "make", "makes", "made", "making",
    "take", "takes", "took", "taken", "taking",
    "give", "gives", "gave", "given", "giving",
    "provide", "provides", "provided", "providing",
    "create", "creates", "created", "creating",
    "update", "updates", "updated", "updating",
    "add", "adds", "added", "adding",
    "remove", "removes", "removed", "removing",
    "write", "writes", "wrote", "written", "writing",
    "send", "sends", "sent", "sending",
    "handle", "handles", "handled", "handling",
    "store", "stores", "stored", "storing",
    "fetch", "fetches", "fetched", "fetching",
    "load", "loads", "loaded", "loading",
    "save", "saves", "saved", "saving",
    "check", "checks", "checked", "checking",
    "implement", "implements", "implemented", "implementing",
    "configure", "configures", "configured", "configuring",
    "fix", "fixes", "fixed", "fixing",
    "start", "starts", "started", "starting",
    "get", "gets", "got", "gotten", "getting",
}


def parse(text: str) -> ParsedText:
    """Tokenize `text` and tag governance-verb occurrences.
    Returns the engine-neutral ParsedText consumed by extract_relations()
    and by step1_ner's noun-chunk-equivalent fallback."""
    tokens = []
    for tok_text, start, end in tokenize(text):
        lower = tok_text.lower()
        lemma = _VERB_SURFACE_TO_LEMMA.get(lower)
        tokens.append(Token(text=tok_text, start=start, end=end,
                             is_verb=lemma is not None, lemma=lemma))
    return ParsedText(text=text, tokens=tokens)


# ---------------------------------------------------------------------------
# Candidate phrase chunking (noun_chunks replacement)
# ---------------------------------------------------------------------------

def shallow_chunks(parsed: ParsedText) -> list[tuple[int, int, str]]:
    """RAKE-style candidate-phrase extraction: maximal runs of tokens that
    are neither function words, punctuation, governance-verb forms, nor
    common (non-governance) verb forms (see _COMMON_VERB_SURFACE_FORMS).
    Returns (start, end, text) triples, trailing/leading punctuation
    already excluded by construction (punctuation tokens are boundaries,
    never included in a run)."""
    chunks = []
    run: list[Token] = []
    for tok in parsed.tokens:
        is_word = tok.text[0].isalnum() or tok.text[0] == "_"
        lower = tok.text.lower()
        is_boundary = (
            (not is_word) or tok.is_verb or lower in FUNCTION_WORDS
            or lower in _COMMON_VERB_SURFACE_FORMS
        )
        if is_boundary:
            if run:
                chunks.append((run[0].start, run[-1].end,
                                " ".join(t.text for t in run)))
                run = []
            continue
        run.append(tok)
    if run:
        chunks.append((run[0].start, run[-1].end, " ".join(t.text for t in run)))
    return chunks
