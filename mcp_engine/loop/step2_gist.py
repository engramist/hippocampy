"""
Step 2 — gist Rapid Classification (Kahneman System 1 / System 2)

Named IP Claim: Kahneman System 1/2 hybrid classifier.

Maps each concept to a gist ontological class using dual-process approach:
  System 1 (fast):      embedding cosine similarity vs. GistClass.centroid
    > 0.85              → accept result instantly, no LLM call
    0.60 – 0.85         → ambiguous → escalate to System 2
    < 0.60              → noise → early exit, vector-log only
  System 2 (deliberate): Ollama LLM call for disambiguation
    Resolved examples saved → centroid updated → S2 rate decreases over time

gist classes: Restriction, PlannedEvent, PhysicalThing, Magnitude, Category, Agent, Event

Centroids: loaded from GistClass nodes in Kùzu (bootstrapped at M1 schema init
from InvertorsDocs/GistSeedExamples.md — 105 examples, 15 per class).

Self-improving: System 2 resolutions appended to GistSeedExamples.md
and centroid updated (running mean — no retraining needed).

M3 scope: implement this step.
"""

CONFIDENCE_SYSTEM1_THRESHOLD = 0.85
CONFIDENCE_NOISE_FLOOR = 0.60

GIST_CLASSES = [
    "Restriction", "PlannedEvent", "PhysicalThing",
    "Magnitude", "Category", "Agent", "Event"
]


def classify_concept(entity_text: str, embedding: list[float],
                     centroids: dict[str, list[float]]) -> dict:
    """
    Classify a single concept into a gist class.
    Returns {gist_class, confidence, system: "1"|"2"|"noise"}.
    """
    # TODO M3: implement cosine similarity + LLM fallback
    pass
