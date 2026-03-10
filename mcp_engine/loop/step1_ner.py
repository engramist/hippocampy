"""Step 1 — Zoning / NER (spaCy). Zero LLM cost."""

import spacy

_nlp = None


def get_nlp(model_name: str = "en_core_web_md"):
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(model_name)
    return _nlp


def extract_entities(text: str, model_name: str = "en_core_web_md") -> tuple:
    """
    Run spaCy NER + dependency parse on text.
    Returns (doc, entities) where entities is a list of dicts.
    doc is kept for Step 1b (dep parser reuses it — no double parse).
    """
    nlp = get_nlp(model_name)
    doc = nlp(text)

    entities = [
        {
            "text":  ent.text,
            "label": ent.label_,   # PERSON, ORG, PRODUCT, GPE, DATE, CARDINAL, etc.
            "start": ent.start_char,
            "end":   ent.end_char,
        }
        for ent in doc.ents
    ]

    return doc, entities
