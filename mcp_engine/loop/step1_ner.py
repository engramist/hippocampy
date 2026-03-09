"""
Step 1 — Zoning / NER (spaCy)

Extracts raw concepts from a message: people, objects, places, actions, quantities, events.
Zero LLM cost. Fast, deterministic.

Model: en_core_web_md (trained dependency parser required for Step 1b)
       en_core_web_sm will NOT work — no trained dep parser.

Output: list of typed Entity objects passed to Step 1b and Step 2.

M3 scope: implement this step.
"""

# import spacy  # uncomment when implementing
# nlp = spacy.load("en_core_web_md")


def extract_entities(text: str) -> list[dict]:
    """
    Run spaCy NER on text.
    Returns list of {text, label, start, end} dicts.
    Entity labels: PERSON, ORG, PRODUCT, GPE, DATE, CARDINAL, etc.
    Used by Step 1b (dep parser) and Step 2 (gist classification).
    """
    # TODO M3: implement
    pass
