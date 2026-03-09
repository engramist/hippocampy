"""
Step 4 — Heuristic Pattern Matching + Selective Attention

Named IP Claims:
  - Representativeness Heuristic: classify into artifact type using ontological context
  - Cocktail Party Effect: Step 4 confidence gate IS the selective attention filter

The Brain is always-on (adapter forwards all turns). Most conversation is background
noise — only specific patterns cause the Brain's "senses" to fire:

  Decision sense:      "we decided", "we chose", past-tense resolution language
  Constraint sense:    "never", "must", "always", "forbidden", directive language
  Plan sense:          "we will", "next step", future-tense action language
  Entity sense:        known graph entity mentioned by name or near-match embedding
  Contradiction sense: Step 5 retrieval finds 0.75–0.92 similarity to existing node

Confidence gate (NOT a blocking gate — all above noise floor enter the graph):
  < 0.60  → noise, vector-log only, no Concept node created
  0.60–0.90 → store Concept with confidence_low=True, pathway_strength=confidence
  > 0.90  → store Concept with full confidence, proceed to Steps 5–7
             pathway_strength initialized to max(confidence, 0.50)

Push-based: LLM does NOT decide what to remember. The Brain decides.

M3 scope: implement this step.
"""

NOISE_FLOOR = 0.60
HARD_LOCK_THRESHOLD = 0.90


def classify_artifact(entities: list[dict], schema_context: dict,
                       text: str) -> dict:
    """
    Match against artifact templates using ontological context from Steps 2–3.
    Returns {artifact_type, confidence, confidence_low, should_proceed}.
    artifact_type: decision | constraint | requirement | action_item | noise
    """
    # TODO M3: implement pattern matching with confidence gates
    pass
