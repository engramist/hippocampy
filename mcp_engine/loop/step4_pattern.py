"""
Step 4 — Heuristic Pattern Matching + Selective Attention

Named IP Claims:
  - Representativeness Heuristic: artifact classification via ontological shape
  - Cocktail Party Effect: confidence gate IS the selective attention filter

Confidence gate (not blocking — all above noise floor enter the graph):
  < 0.60  → noise, no Concept node
  0.60–0.90 → Concept node, confidence_low=True
  > 0.90  → Concept node, full confidence; if artifact type identified → REIFIED_AS
"""

from __future__ import annotations
import re

NOISE_FLOOR        = 0.60
HARD_LOCK          = 0.90

# Cocktail Party Effect — five senses (keyword signals)
_DECISION_SIGNALS = [
    r"\bwe decided\b", r"\bwe chose\b", r"\bwe agreed\b", r"\bwe resolved\b",
    r"\bdecision[:\s]", r"\bchosen\b", r"\bselected\b", r"\bwent with\b",
    r"\bfinalized\b", r"\bsettled on\b",
]
_CONSTRAINT_SIGNALS = [
    # L6 fix: "must not" listed first and matched as a single unit to prevent
    # "must" pattern double-counting the same text.
    r"\bmust not\b", r"\bmust(?!\s+not)\b", r"\bnever\b", r"\balways\b",
    r"\bforbidden\b", r"\brequired\b", r"\bshall not\b", r"\bno .+? allowed\b",
    r"\bmandatory\b", r"\bprohibited\b", r"\bnon-negotiable\b",
]
_REQUIREMENT_SIGNALS = [
    r"\bwe need\b", r"\bwe require\b", r"\bshould\b", r"\bneeds to\b",
    r"\brequirement[:\s]", r"\bacceptance criteri", r"\bexpected to\b",
]
_ACTION_SIGNALS = [
    r"\bwe will\b", r"\bnext step\b", r"\bplan to\b", r"\bgoing to\b",
    r"\btodo\b", r"\baction item\b", r"\bwe'll\b", r"\bscheduled\b",
]

# gist class → likely artifact type (prior probability)
_GIST_ARTIFACT_PRIOR: dict[str, tuple[str, float]] = {
    "Restriction":   ("constraint",   0.80),
    "PlannedEvent":  ("action_item",  0.72),
    "PhysicalThing": ("decision",     0.55),
    "Magnitude":     ("constraint",   0.50),
    "Category":      ("decision",     0.55),
    "Agent":         (None,           0.40),
    "Event":         ("decision",     0.50),
}


def _match_signals(text: str, patterns: list[str]) -> int:
    """Count how many signal patterns match in text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for p in patterns if re.search(p, text_lower))


def _entity_sentence(full_text: str, entity_text: str) -> str:
    """
    L5 fix: extract the sentence(s) containing entity_text from full_text
    so signal matching is scoped to entity context, not the whole message.
    Falls back to full_text if the entity can't be located.
    """
    lower_full = full_text.lower()
    lower_entity = entity_text.lower()
    pos = lower_full.find(lower_entity)
    if pos == -1:
        return full_text
    # Find sentence boundaries around pos
    sent_start = max(0, full_text.rfind(".", 0, pos) + 1)
    sent_end_match = full_text.find(".", pos)
    sent_end = sent_end_match + 1 if sent_end_match != -1 else len(full_text)
    return full_text[sent_start:sent_end].strip() or full_text


def classify_artifact(text: str, gist_class: str | None,
                      schema_org_type: str | None,
                      entity_text: str | None = None) -> dict:
    """
    Classify text into an artifact type using ontological context + keyword signals.
    Returns {artifact_type, confidence, confidence_low, should_proceed}.

    artifact_type: "decision" | "constraint" | "requirement" | "action_item" | "noise"
    should_proceed: True if confidence >= NOISE_FLOOR
    """
    if not gist_class:
        return _noise_result()

    # L5 fix: score signals against entity-local sentence context, not full message.
    match_text = _entity_sentence(text, entity_text) if entity_text else text

    # Score each artifact type by signal count
    scores = {
        "decision":    _match_signals(match_text, _DECISION_SIGNALS),
        "constraint":  _match_signals(match_text, _CONSTRAINT_SIGNALS),
        "requirement": _match_signals(match_text, _REQUIREMENT_SIGNALS),
        "action_item": _match_signals(match_text, _ACTION_SIGNALS),
    }

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    # Apply gist prior if no strong keyword signal
    if best_score == 0:
        prior_type, prior_conf = _GIST_ARTIFACT_PRIOR.get(gist_class, (None, 0.40))
        if prior_type is None:
            return _noise_result()
        confidence = prior_conf
        artifact_type = prior_type
    else:
        # Scale keyword hits → confidence: 1 hit ≈ 0.75, 2+ hits ≈ 0.90+
        confidence = min(0.65 + (best_score * 0.12), 0.97)
        artifact_type = best_type

    # Boost confidence if gist class agrees with the inferred artifact type
    prior_type, _ = _GIST_ARTIFACT_PRIOR.get(gist_class, (None, 0))
    if prior_type == artifact_type:
        confidence = min(confidence + 0.05, 0.98)

    if confidence < NOISE_FLOOR:
        return _noise_result()

    return {
        "artifact_type":  artifact_type,
        "confidence":     confidence,
        "confidence_low": confidence < HARD_LOCK,
        "should_proceed": True,
    }


def _noise_result() -> dict:
    return {
        "artifact_type":  "noise",
        "confidence":     0.0,
        "confidence_low": True,
        "should_proceed": False,
    }
