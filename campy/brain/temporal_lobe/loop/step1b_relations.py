"""
Step 1b — Relation Extraction: Fast Path (Universal Verb Patterns)

Zero LLM cost. B387: reuses the engine-neutral `shallow_parse.ParsedText`
from Step 1 (no double parse) instead of a spaCy `Doc` — `extract_relations()`
no longer accepts a spaCy `Doc`.

Extracts head -> verb -> tail triples using the nearest shallow_chunk before
and after each tagged governance verb, matches the verb lemma to a named
relation type. This is an approximation of the old nsubj/dobj dependency-tree
walk (see shallow_parse.py's header for why: no ONNX dependency parser cleared
the B387 Gate 0 license+portability bar). It does not cross a sentence
boundary (. ! ? ;) when looking for the nearest chunk, so it can't wire two
unrelated clauses together.
"""

from __future__ import annotations

from campy.brain.temporal_lobe.loop.shallow_parse import (
    VALID_RELATION_TYPES,
    VERB_PATTERNS,
    ParsedText,
    shallow_chunks,
)

__all__ = ["VALID_RELATION_TYPES", "VERB_PATTERNS", "extract_relations"]

_SENTENCE_ENDERS = {".", "!", "?", ";"}


def _crosses_sentence_boundary(parsed: ParsedText, lo: int, hi: int) -> bool:
    """True if any sentence-ending punctuation token falls in [lo, hi)."""
    if lo >= hi:
        return False
    return any(
        tok.text in _SENTENCE_ENDERS and lo <= tok.start < hi
        for tok in parsed.tokens
    )


def extract_relations(parsed: ParsedText, entities: list[dict]) -> list[dict]:
    """
    For each governance-verb occurrence, take the nearest shallow chunk
    ending before it as `head` and the nearest shallow chunk starting after
    it as `tail`, provided neither crosses a sentence boundary.
    Returns list of {head, relation_type, tail, confidence, inferred_by}.
    Empty list = Step 3b eligibility check will fire.

    `entities` is accepted for interface parity with the old spaCy-backed
    version (which also never used it — the relation walk was independent
    of the Step 1 entity list there too) and for future use.
    """
    chunks = shallow_chunks(parsed)
    relations = []

    for tok in parsed.tokens:
        if not tok.is_verb:
            continue

        relation_type = VERB_PATTERNS.get(tok.lemma)
        if not relation_type:
            continue

        head_text = None
        for c_start, c_end, c_text in reversed(chunks):
            if c_end <= tok.start:
                if _crosses_sentence_boundary(parsed, c_end, tok.start):
                    break
                head_text = c_text
                break

        tail_text = None
        for c_start, c_end, c_text in chunks:
            if c_start >= tok.end:
                if _crosses_sentence_boundary(parsed, tok.end, c_start):
                    break
                tail_text = c_text
                break

        if not head_text or not tail_text:
            continue

        relations.append({
            "head":          head_text,
            "relation_type": relation_type,
            "tail":          tail_text,
            "confidence":    0.85,
            "inferred_by":   "system",
        })

    return relations
