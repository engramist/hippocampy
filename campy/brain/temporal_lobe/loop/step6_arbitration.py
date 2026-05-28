"""
Step 6 — Constrained Contradiction Arbitration

Named IP Claim: System 2 Deliberate Reasoning applied to contradiction
detection. The LLM is constrained to a 3-way forced-choice output
(not free text), preventing hallucination creep.

Triggers when Step 5 finds a candidate in the gray zone (0.75–0.92 similarity).
LLM forced to classify the relationship as one of three options:

  "additive"      → same idea expressed differently → strengthen existing node
  "contradiction" → directly conflicts → new node + DEPRECATED_BY on old
  "uncertain"     → ambiguous → keep both as confidence_low (re-scored later)

"uncertain" is not a failure — it is the correct response when evidence
is genuinely insufficient. Both nodes remain in the graph and accumulate
context over future messages.
"""

import json
import re

VALID_CLASSIFICATIONS = {"additive", "contradiction", "uncertain"}


def arbitrate(new_concept: dict, candidates: list[dict],
              original_text: str, llm_client) -> dict:
    """
    Ask the LLM to classify the relationship between new_concept and candidates.

    new_concept: {text, gist_class, schema_org_type, confidence, ...}
    candidates:  list of Step 5 results [{concept_id, text_raw, similarity, ...}]

    Returns {classification, rationale, referenced_node_ids}.
    Falls back to "uncertain" if LLM is unavailable or returns invalid output.
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
        f"Choose exactly one classification:\n"
        f"  additive      — the new concept reinforces or restates an existing one\n"
        f"  contradiction — the new concept directly conflicts with an existing one\n"
        f"  uncertain     — not enough evidence to decide\n\n"
        f"Respond with JSON only:\n"
        f'{{\"classification\": \"<additive|contradiction|uncertain>\", '
        f'\"rationale\": \"<one sentence>\", '
        f'\"referenced_index\": <1-{len(top)} or null>}}'
    )

    try:
        raw = llm_client.chat([{"role": "user", "content": prompt}])
        # L11 fix: extract first {...} block to handle preamble, trailing text,
        # varying fence styles (```json, ```JSON, no fence).
        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if not match:
            return _uncertain([c["concept_id"] for c in top], "LLM returned no JSON")
        result = json.loads(match.group())

        classification = result.get("classification", "uncertain")
        if classification not in VALID_CLASSIFICATIONS:
            classification = "uncertain"

        ref_idx = result.get("referenced_index")
        referenced_ids = []
        # L12 fix: coerce string/float LLM outputs to int before range check.
        if ref_idx is not None:
            try:
                ref_idx = int(ref_idx)
            except (TypeError, ValueError):
                ref_idx = None
        if ref_idx is not None and 1 <= ref_idx <= len(top):
            referenced_ids = [top[ref_idx - 1]["concept_id"]]

        return {
            "classification":      classification,
            "rationale":           result.get("rationale", ""),
            "referenced_node_ids": referenced_ids,
        }

    except Exception:
        return _uncertain([c["concept_id"] for c in top], "LLM parse error")


def _uncertain(node_ids: list, rationale: str) -> dict:
    return {
        "classification":      "uncertain",
        "rationale":           rationale,
        "referenced_node_ids": node_ids,
    }
