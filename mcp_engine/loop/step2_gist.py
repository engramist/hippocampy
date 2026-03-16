"""
Step 2 — gist Rapid Classification (Kahneman System 1 / System 2)

Named IP Claim: Kahneman System 1/2 hybrid classifier.
System 1: cosine similarity vs. GistClass centroids (fast, no LLM).
System 2: Ollama LLM call for ambiguous 0.60–0.85 range.
"""

import json
from mcp_engine.graph import embeddings as emb

SYSTEM1_THRESHOLD = 0.85
NOISE_FLOOR       = 0.60

GIST_CLASSES = [
    "Restriction", "PlannedEvent", "PhysicalThing",
    "Magnitude", "Category", "Agent", "Event"
]

GIST_DESCRIPTIONS = {
    "Restriction":   "rules, limits, constraints, requirements, policies — things that govern behavior",
    "PlannedEvent":  "intended future actions, scheduled work, next steps, goals to accomplish",
    "PhysicalThing": "tangible objects, software artifacts, systems, files, tools, infrastructure",
    "Magnitude":     "numbers, measures, quantities, thresholds, percentages, durations, sizes",
    "Category":      "labels, types, classifications, definitions, taxonomies, roles",
    "Agent":         "people, teams, organizations, systems, or processes acting with intent",
    "Event":         "things that happened, are happening, or were triggered — occurrences",
}


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Dot product of normalized vectors = cosine similarity."""
    return sum(x * y for x, y in zip(a, b))


def load_centroids(db) -> dict[str, list[float]]:
    """Load all GistClass centroids from Kùzu. Call at daemon startup and cache."""
    result = db.execute("MATCH (g:GistClass) RETURN g.name, g.centroid")
    centroids = {}
    while result.has_next():
        row = result.get_next()
        if row[1]:  # centroid may be None before bootstrap
            centroids[row[0]] = row[1]
    return centroids


def classify_concept(entity_text: str, embedding_model: str,
                     centroids: dict[str, list[float]],
                     llm_client=None) -> dict:
    """
    Classify a single concept into a gist class.
    Returns {gist_class, confidence, system: "1"|"2"|"noise", vector: list[float]}.
    The "vector" key is always included so callers can store System 2 examples
    without re-computing the embedding.
    """
    vector = emb.embed(entity_text, model_name=embedding_model)

    # System 1: compare against all class centroids
    best_class = None
    best_score = -1.0
    for class_name, centroid in centroids.items():
        score = _cosine_sim(vector, centroid)
        if score > best_score:
            best_score = score
            best_class = class_name

    if best_score >= SYSTEM1_THRESHOLD:
        return {"gist_class": best_class, "confidence": best_score,
                "system": "1", "vector": vector}

    if best_score < NOISE_FLOOR:
        return {"gist_class": None, "confidence": best_score,
                "system": "noise", "vector": vector}

    # System 2: LLM disambiguation
    if llm_client is None:
        # Ollama unavailable — store as confidence_low with best System 1 guess
        return {"gist_class": best_class, "confidence": best_score,
                "system": "2_degraded", "confidence_low": True, "vector": vector}

    result = _classify_with_llm(entity_text, llm_client)
    result["vector"] = vector
    return result


def _classify_with_llm(entity_text: str, llm_client) -> dict:
    """System 2: ask Ollama to classify. Saves example for centroid improvement."""
    class_list = "\n".join(
        f"- {name}: {desc}" for name, desc in GIST_DESCRIPTIONS.items()
    )
    prompt = (
        f'Classify this concept into exactly one gist ontology class.\n\n'
        f'Concept: "{entity_text}"\n\n'
        f'Classes:\n{class_list}\n\n'
        f'Respond with JSON only, no explanation:\n'
        f'{{"class": "<class_name>", "confidence": <0.0-1.0>}}'
    )
    try:
        raw = llm_client.chat([{"role": "user", "content": prompt}])
        # Strip markdown code fences if present
        raw = raw.strip().strip("```json").strip("```").strip()
        result = json.loads(raw)
        class_name = result.get("class", "")
        confidence = float(result.get("confidence", 0.7))
        # L2 fix: return noise for unrecognized classes rather than silently
        # misclassifying as the first entry ("Restriction").
        if class_name not in GIST_CLASSES:
            return {"gist_class": None, "confidence": 0.0, "system": "noise"}
        return {"gist_class": class_name, "confidence": confidence, "system": "2"}
    except Exception:
        return {"gist_class": None, "confidence": 0.0, "system": "noise"}
