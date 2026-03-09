"""
Step 6 — Constrained Contradiction Arbitration

Only triggers in gray zone (0.75–0.92 similarity) or same artifact type match.
LLM forced to output: {classification, rationale_tokens, referenced_nodes}

classification options:
  "additive"      → strengthen existing node pathway (Step 7 additive path)
  "contradiction" → create new node + DEPRECATED_BY edge on old (Step 7 contradiction path)
  "uncertain"     → store both as confidence_low=True, re-scored as context accumulates

LLM is constrained — cannot return free text. Must choose from 3 classifications.
"uncertain" is a valid and common output; it is not a failure.

Ollama used for real-time arbitration (latency-sensitive).
Cloud providers acceptable for document ingestion path.

M4 scope: implement this step.
"""


def arbitrate(new_concept: dict, candidates: list[dict], llm_client) -> dict:
    """
    Ask LLM to classify the relationship between new_concept and existing candidates.
    Returns {classification, rationale, referenced_node_ids}.
    """
    # TODO M4: implement
    pass
