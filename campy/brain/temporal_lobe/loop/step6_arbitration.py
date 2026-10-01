"""
Step 6 — Constrained Contradiction Arbitration

Named IP Claim: System 2 Deliberate Reasoning applied to contradiction
detection. The LLM is constrained to a 3-way forced-choice output
(not free text), preventing hallucination creep.

Triggers when Step 5 finds a candidate in the gray zone (0.75–0.92 similarity).
LLM forced to classify the relationship as one of three options
(B460: a single option letter; probabilities from token log-probabilities
where the provider returns them):

  "additive"      → same idea expressed differently → strengthen existing node
  "contradiction" → directly conflicts → new node + DEPRECATED_BY on old
  "uncertain"     → ambiguous → keep both as confidence_low (re-scored later)

"uncertain" is not a failure — it is the correct response when evidence
is genuinely insufficient. Both nodes remain in the graph and accumulate
context over future messages.
"""

from campy.brain.llm.decide import decide, log_near_tie, options_block

VALID_CLASSIFICATIONS = {"additive", "contradiction", "uncertain"}

# B460: option order is fixed so letters are stable across calls.
_OPTIONS = ["additive", "contradiction", "uncertain"]
_DESCRIPTIONS = {
    "additive":      "the new concept reinforces or restates an existing one",
    "contradiction": "the new concept directly conflicts with an existing one",
    "uncertain":     "not enough evidence to decide",
}


def arbitrate(new_concept: dict, candidates: list[dict],
              original_text: str, llm_client) -> dict:
    """
    Ask the LLM to classify the relationship between new_concept and candidates.

    new_concept: {text, gist_class, schema_org_type, confidence, ...}
    candidates:  list of Step 5 results [{concept_id, text_raw, similarity, ...}]

    Returns {classification, rationale, referenced_node_ids, probs}.
    Falls back to "uncertain" if the LLM is unavailable or its answer can't be
    read. B460: the answer is a single option letter; where the provider
    returns log-probabilities, a near tie between the top two options is
    treated as "uncertain" (both nodes stay confidence_low) and logged.
    """
    if llm_client is None or not candidates:
        return _uncertain([], "LLM unavailable or no candidates")

    # Only send top-3 candidates to keep prompt tight
    top = candidates[:3]

    candidate_lines = "\n".join(
        f"  [{i+1}] \"{c['text_raw']}\" "
        f"(similarity: {c['similarity']:.2f}, strength: {c['pathway_strength']:.2f})"
        for i, c in enumerate(top)
    )

    prompt = (
        f"A new concept arrived in a conversation. Determine if it adds to, "
        f"contradicts, or is ambiguously related to existing knowledge.\n\n"
        f"New concept: \"{new_concept.get('text', '')}\" "
        f"(type: {new_concept.get('gist_class', '?')} / "
        f"{new_concept.get('schema_org_type', '?')})\n\n"
        f"Context sentence: \"{original_text}\"\n\n"
        f"Existing similar concepts:\n{candidate_lines}\n\n"
        + options_block(_OPTIONS, _DESCRIPTIONS)
    )

    decision = decide(llm_client, prompt, _OPTIONS)
    if decision.choice is None:
        return _uncertain([c["concept_id"] for c in top], "LLM answer unreadable")

    classification = decision.choice
    rationale = f"model choice ({decision.source})"
    if decision.near_tie():
        log_near_tie("step6_arbitration", decision, new_concept.get("text", ""))
        if classification != "uncertain":
            classification = "uncertain"
            rationale = (f"near tie {decision.top_two[0]}|{decision.top_two[1]} "
                         f"(margin {decision.margin:.2f})")

    return {
        "classification":      classification,
        "rationale":           rationale,
        # The orchestrator acts on the top candidate (and links "uncertain"
        # DisambiguationEvents to it); report it as the reference.
        "referenced_node_ids": [top[0]["concept_id"]],
        "probs":               decision.probs,
    }


def _uncertain(node_ids: list, rationale: str) -> dict:
    return {
        "classification":      "uncertain",
        "rationale":           rationale,
        "referenced_node_ids": node_ids,
        "probs":               None,
    }
