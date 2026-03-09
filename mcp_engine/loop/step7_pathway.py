"""
Step 7 — Pathway Update (Recognition / Availability Heuristic)

Named IP Claims:
  - Hebbian Learning: pathway_strength accumulation = "wire together"
  - Long-Term Potentiation: CO_OCCURS_WITH → named edge promotion

Two update paths based on Step 6 output:

  Additive (classification = "additive" or similarity > 0.92):
    strength += 1 * log(1 + 1/days_since_last_access)
    No duplicate node created.
    Trigger event-driven confidence re-scoring on confidence_low nodes 1–2 hops out.

  Contradiction (classification = "contradiction"):
    Create new Concept node.
    Draw DEPRECATED_BY edge from old node to new node.
    Old node preserved in audit trail, filtered from current_truth.
    Create MergeEvent with delta pointers for deterministic rollback.

After pathway update:
  CO_OCCURS_WITH: write (or increment via MERGE) edges between all concept pairs
  from the same message that cleared the noise floor (>60% confidence).
  strength initialized to min(confidence_A, confidence_B).

  # Implementation note: use Kùzu MERGE pattern for idempotent upsert:
  # MERGE (a)-[r:CO_OCCURS_WITH]-(b)
  # ON CREATE SET r.count = 1, r.strength = $min_conf, r.first_seen = timestamp()
  # ON MATCH SET r.count = r.count + 1, r.strength = (r.strength + $new_conf) / 2

  Check CO_OCCURS_WITH count against co_occurrence_threshold (default 10).
  If threshold crossed → trigger LLM auto-promotion (Hebbian Trigger 2).

M4 scope: implement this step.
"""

import math


def pathway_strength_increment(current_strength: float,
                               days_since_last_access: float) -> float:
    """
    Strengthening formula (Hebbian reinforcement / Recognition Heuristic).
    new_strength = current + 1 * log(1 + 1/days_since_last_access)
    """
    if days_since_last_access <= 0:
        days_since_last_access = 1 / 86400  # minimum: 1 second
    return current_strength + math.log(1 + 1 / days_since_last_access)


def pathway_strength_decay(current_strength: float, decay_rate: float,
                           days_since_last_access: float) -> float:
    """
    Decay formula (Ebbinghaus Forgetting Curve / Synaptic Pruning).
    new_strength = current * decay_rate ^ days_since_last_access
    Called by background sweep, not by this step.
    """
    return current_strength * (decay_rate ** days_since_last_access)


def update_pathway(concept: dict, arbitration_result: dict,
                   message_concepts: list[dict], db) -> dict:
    """
    Apply additive update or contradiction resolution.
    Write CO_OCCURS_WITH edges for all concept pairs from this message.
    Returns {updated_node_id, action: "additive"|"contradiction", merge_event_id}.
    """
    # TODO M4: implement
    pass
