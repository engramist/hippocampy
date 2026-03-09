"""
Step 3b — Relation Extraction: Semantic Path (Ollama with Type Context)

Named IP Claim: Shape-First Principle applied to relation extraction.
Runs AFTER Step 3 — has full gist class + schema.org type per entity.
"Know the shape before doing semantic work" — typed entities make Ollama far more accurate.

Triggered when: >1 entity in message AND Step 1b found no relation.

Handles types Step 1b cannot extract from syntax alone:
  CHOSEN_OVER    — requires understanding decision context
  IMPLEMENTS     — requires type context
  EXTENDS        — domain-dependent meaning
  ALTERNATIVE_TO — requires situational context

Ollama prompt structure:
  Entity A: {text} (gist:{gist_class} / schema:{schema_org_type})
  Entity B: {text} (gist:{gist_class} / schema:{schema_org_type})
  Sentence: "{original_text}"
  What is the relationship between A and B?

Forced output schema: {head, relation_type, tail, confidence} or null.
Must choose from 9 named types — never forced to produce a relation.
inferred_by: "LLM"

Also refines any Step 1b edge with low confidence from ambiguous syntax.
Results written to Kùzu alongside CO_OCCURS_WITH edges.

M3 scope: implement this step.
"""

SEMANTIC_RELATION_TYPES = ["CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO"]


def extract_semantic_relations(entities: list[dict], original_text: str,
                               llm_client) -> list[dict]:
    """
    Call Ollama with typed entity context to extract semantic relations.
    Returns list of {head, relation_type, tail, confidence, inferred_by: "LLM"} dicts,
    or empty list if no confident relation found.
    """
    # TODO M3: implement
    pass
