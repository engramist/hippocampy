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


def extract_relations(doc, entities: list[dict]) -> list[dict]:
    """
    Walk the dep tree looking for: nsubj → VERB → dobj patterns.
    Returns list of {head, relation_type, tail, confidence, inferred_by}.
    Empty list = Step 3b eligibility check will fire.
    """
    relations = []
    entity_texts = {e["text"].lower() for e in entities}

    for token in doc:
        if token.pos_ != "VERB":
            continue

        relation_type = VERB_PATTERNS.get(token.lemma_.lower())
        if not relation_type:
            continue

        # Find nsubj (head) and dobj or attr (tail)
        head_tok = next((c for c in token.children if c.dep_ in ("nsubj", "nsubjpass")), None)
        tail_tok = next((c for c in token.children if c.dep_ in ("dobj", "attr", "pobj")), None)

        if not head_tok or not tail_tok:
            continue

        head_text = head_tok.text
        tail_text = tail_tok.text

        # Expand to full noun chunk if possible
        for chunk in doc.noun_chunks:
            if head_tok in chunk:
                head_text = chunk.text
            if tail_tok in chunk:
                tail_text = chunk.text

        relations.append({
            "head":          head_text,
            "relation_type": relation_type,
            "tail":          tail_text,
            "confidence":    0.85,
            "inferred_by":   "system",
        })

    return relations
