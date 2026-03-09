"""
Step 1b — Relation Extraction: Fast Path (Universal Verb Patterns)

Syntactic relation extraction via spaCy dependency parser.
Zero LLM cost. Domain-agnostic — works for software, writing, research, business.

Method: identify nsubj→verb→dobj triples via dep parser.
Match verb lemma against universal pattern dict:

  require/need/depend/necessitate       → REQUIRES
  enable/allow/support/facilitate/permit → ENABLES
  replace/supersede/deprecate/override  → REPLACES
  contradict/conflict/violate/negate    → CONTRADICTS
  contain/include (+ "is part of" dep)  → PART_OF

Types requiring entity type context (CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO)
are deferred to Step 3b which has full gist+schema.org context.

Output: list of {head, relation_type, tail, confidence, inferred_by: "system"} dicts.
Confirmed edges written to Kùzu immediately.

M3 scope: implement this step.
"""

VERB_PATTERNS = {
    "require":    "REQUIRES",
    "need":       "REQUIRES",
    "depend":     "REQUIRES",
    "necessitate":"REQUIRES",
    "enable":     "ENABLES",
    "allow":      "ENABLES",
    "support":    "ENABLES",
    "facilitate": "ENABLES",
    "permit":     "ENABLES",
    "replace":    "REPLACES",
    "supersede":  "REPLACES",
    "deprecate":  "REPLACES",
    "override":   "REPLACES",
    "contradict": "CONTRADICTS",
    "conflict":   "CONTRADICTS",
    "violate":    "CONTRADICTS",
    "negate":     "CONTRADICTS",
    "contain":    "PART_OF",
    "include":    "PART_OF",
}


def extract_relations(doc, entities: list[dict]) -> list[dict]:
    """
    Run verb pattern matching on a spaCy doc.
    Returns list of {head, relation_type, tail, confidence, inferred_by} dicts.
    Returns empty list if no patterns match (triggers Step 3b eligibility check).
    """
    # TODO M3: implement
    pass
