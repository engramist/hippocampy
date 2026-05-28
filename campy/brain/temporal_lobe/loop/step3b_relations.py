"""
Step 3b — Relation Extraction: Semantic Path (Ollama with Type Context)

Named IP Claim: Shape-First Principle applied to relation extraction.
Triggered: >1 typed entity AND Step 1b found no relation.
"""

import json

SEMANTIC_TYPES = ["CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO"]


def extract_semantic_relations(entities: list[dict], original_text: str,
                               llm_client) -> list[dict]:
    """
    entities: list of {text, label, gist_class, schema_org_type}
    Returns list of {head, relation_type, tail, confidence, inferred_by: "LLM"}
    or empty list if no confident relation found (LLM may return null).
    """
    if len(entities) < 2 or llm_client is None:
        return []

    # Build typed entity context (Shape-First: typed entities narrow semantic space)
    entity_lines = "\n".join(
        f"  Entity {i+1}: {e['text']} "
        f"(gist:{e.get('gist_class', '?')} / schema:{e.get('schema_org_type', '?')})"
        for i, e in enumerate(entities[:4])  # cap at 4 entities per message
    )

    relation_list = ", ".join(SEMANTIC_TYPES)

    prompt = (
        f"Given these typed entities and the sentence they appear in, "
        f"identify if there is a semantic relationship between any two of them.\n\n"
        f"Entities:\n{entity_lines}\n\n"
        f"Sentence: \"{original_text}\"\n\n"
        f"If a relationship exists, choose from: {relation_list}\n"
        f"If no clear relationship exists, return null.\n\n"
        f"Respond with JSON only:\n"
        f'{{"head": "<entity text>", "relation_type": "<TYPE>", '
        f'"tail": "<entity text>", "confidence": <0.0-1.0>}}\n'
        f"or: null"
    )

    try:
        raw = llm_client.chat([{"role": "user", "content": prompt}])
        raw = raw.strip().strip("```json").strip("```").strip()

        if raw.lower() == "null" or not raw:
            return []

        result = json.loads(raw)
        if not result or result.get("relation_type") not in SEMANTIC_TYPES:
            return []

        return [{
            "head":          result["head"],
            "relation_type": result["relation_type"],
            "tail":          result["tail"],
            "confidence":    float(result.get("confidence", 0.75)),
            "inferred_by":   "LLM",
        }]
    except Exception:
        return []
