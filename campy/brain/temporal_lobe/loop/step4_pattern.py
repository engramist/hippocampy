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
ASSISTANT_CAP      = 0.85   # ISSUE-024: assistant turns can never cross HARD_LOCK

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
    r"\bforbidden\b", r"\brequired?\b", r"\bshall not\b", r"\bno .+? allowed\b",
    r"\bmandatory\b", r"\bprohibited\b", r"\bnon-negotiable\b",
    r"\bmake sure\b", r"\bensure\b", r"\bno .+? except\b",
    r"\bno unauthenticated\b", r"\bno unauthorized\b",
]
_REQUIREMENT_SIGNALS = [
    r"\bwe need\b", r"\bwe require\b", r"\bshould\b", r"\bneeds to\b",
    r"\brequirement[:\s]", r"\bacceptance criteri", r"\bexpected to\b",
]
_ACTION_SIGNALS = [
    r"\bwe will\b", r"\bnext step\b", r"\bplan to\b", r"\bgoing to\b",
    r"\btodo\b", r"\baction item\b", r"\bwe'll\b", r"\bscheduled\b",
]

# B68 — Plan sense (fallback passive plan detector)
_PLAN_SIGNALS = [
    r"(?:^|\n)\s*(?:step\s+)?\d+[\.\):]",
    r"(?:^|\n)\s*[-•]\s+(?:first|then|next|finally)\b",
    r"\bmy (?:approach|plan|strategy)\b",
    r"\bhere(?:'s| is) (?:the|my) plan\b",
    r"\bi(?:'ll| will) (?:start by|begin with|first)\b",
    r"\bthe steps (?:are|would be)\b",
]

# B69 — Outcome sense (success/failure language)
_SUCCESS_SIGNALS = [
    r"\bperfect\b", r"\bgreat job\b", r"\bexactly (?:right|what)\b",
    r"\bship it\b", r"\bapproved\b", r"\blooks good\b", r"\bwell done\b",
    r"\bnailed it\b", r"\ball tests pass\b", r"\bmerged?\b",
]

_FAILURE_SIGNALS = [
    r"\bthat(?:'s| is) wrong\b", r"\brevert\b", r"\bundo\b",
    r"\bthat broke\b",
    r"\b(?:it|this|that|build|test|tests|deploy|deployment) (?:has )?failed\b",
    r"\bfailed to\b",
    r"\brollback\b",
    r"\bnot what i (?:asked|wanted|meant)\b", r"\bstart over\b",
    r"\btry again\b", r"\bwrong approach\b",
]

# Emotion sense — 7th Cocktail Party sense (Amygdala)
# Emotional language boosts pathway_strength via salience multiplier.
_FRUSTRATION_SIGNALS = [
    r"\bi told you\b", r"\bhow many times\b", r"\bstop doing\b",
    r"\bwrong again\b", r"\bnot what i (?:asked|wanted|meant)\b",
    r"\bthis is (?:broken|terrible|awful)\b", r"\bugh\b",
    r"\bdamn\b", r"\bwhy (?:does|is) (?:it|this)\b",
    r"\bso frustrat", r"\bi(?:'m| am) (?:annoyed|frustrated|angry)\b",
    r"\bfor the (?:third|fourth|fifth|last) time\b",
    r"\bno[,!]+ no\b", r"\bstop[!]+\b",
]
_EXCITEMENT_SIGNALS = [
    r"\byes[!]+", r"\bexactly[!]+", r"\bbrilliant\b",
    r"\blove (?:it|this|that)\b", r"\bamazing\b",
    r"\bthis is (?:great|awesome|incredible|fantastic)\b",
    r"\bhell yeah\b", r"\blet(?:'s| us) go\b",
    r"\bi(?:'m| am) (?:excited|pumped|stoked)\b",
]
_URGENCY_SIGNALS = [
    r"\basap\b", r"\bneed this (?:now|today|immediately)\b",
    r"\bcritical\b", r"\bblocking\b", r"\bemergency\b",
    r"\bdeadline\b", r"\burgent\b", r"\btime.?sensitive\b",
    r"\bcan(?:'t| not) wait\b", r"\bdrop everything\b",
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
                      entity_text: str | None = None,
                      role: str = "user") -> dict:
    """
    Classify text into an artifact type using ontological context + keyword signals.
    Returns {artifact_type, confidence, confidence_low, should_proceed}.

    artifact_type: "decision" | "constraint" | "requirement" | "action_item" | "noise"
    should_proceed: True if confidence >= NOISE_FLOOR

    ISSUE-024: role="assistant" caps confidence at ASSISTANT_CAP (0.85) to prevent
    hallucination poisoning. Assistant-originated content can create Concepts and
    confidence_low artifacts, but can never create confirmed (>90%) Decisions or
    Constraints on its own. Only user-originated content crosses HARD_LOCK.
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
        # Scale keyword hits → confidence: 1 hit ≈ 0.82, 2+ hits → 0.97
        confidence = min(0.67 + (best_score * 0.15), 0.97)
        artifact_type = best_type

    # Boost confidence if gist class agrees AND keyword signals were found.
    # A keyword match + gist agreement is strong evidence (1 hit + agree = 0.92).
    # Gist prior alone (no keyword signals) stays below HARD_LOCK.
    prior_type, _ = _GIST_ARTIFACT_PRIOR.get(gist_class, (None, 0))
    if prior_type == artifact_type and best_score > 0:
        confidence = min(confidence + 0.10, 0.98)

    # B300: single-token entities may exist as tentative Concepts but can
    # never become confirmed artifacts — one word carries no actionable
    # content on its own. Same kind of cap as ASSISTANT_CAP above, applied
    # before the HARD_LOCK comparison, overriding any keyword/gist boost.
    candidate_text = entity_text if entity_text is not None else text
    if candidate_text.strip() and ' ' not in candidate_text.strip():
        confidence = min(confidence, 0.60)

    if confidence < NOISE_FLOOR:
        return {
            "artifact_type":  artifact_type,
            "confidence":     confidence,  # preserve raw for salience rescue
            "confidence_low": True,
            "should_proceed": False,
        }

    # ISSUE-024: assistant turns capped below HARD_LOCK — prevents hallucination
    # poisoning. Assistant content enters as confidence_low=True and must be
    # corroborated by user input or graph evidence to be promoted.
    if role == "assistant":
        confidence = min(confidence, ASSISTANT_CAP)

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


def detect_ordered_plan_steps(text: str) -> list[str]:
    """
    Extract ordered step lines from numbered/bulleted plan text.
    Returns normalized step strings in source order.
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    steps: list[str] = []

    numbered = re.compile(r"^(?:step\s+)?\d+[\.\):]\s+(.+)$", re.IGNORECASE)
    bullet = re.compile(r"^[\-•]\s+(.+)$")
    ordered_words = re.compile(r"^(?:first|then|next|finally)\b[:\-]?\s*(.+)$", re.IGNORECASE)

    for line in lines:
        m_num = numbered.match(line)
        if m_num:
            steps.append(m_num.group(1).strip())
            continue

        m_ord = ordered_words.match(line)
        if m_ord:
            steps.append(m_ord.group(1).strip())
            continue

        m_bul = bullet.match(line)
        if m_bul and ordered_words.match(m_bul.group(1).strip()):
            steps.append(m_bul.group(1).strip())

    # Dedup while preserving order, drop trivially short items
    seen = set()
    clean: list[str] = []
    for step in steps:
        key = step.lower()
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        clean.append(step)
    return clean


def has_plan_signal(text: str) -> bool:
    """Return True when plan framing/structure indicators are present."""
    lower = (text or "").lower()
    return any(re.search(p, lower) for p in _PLAN_SIGNALS)


def infer_outcome_valence_detail(text: str) -> tuple[float | None, list[str]]:
    """
    Infer a coarse valence from outcome language, with the matched signals.

    Returns +0.8 for success, -0.8 for failure, None for neutral/ambiguous,
    alongside the list of signal patterns that drove the call (empty when None).

    B301: a valence is only returned when one side has hits and the other has
    none, or the margin between sides is >= 2. A 3-vs-2 mixed message is
    ambiguous and returns None rather than picking the plurality side —
    a plurality-of-one was how "17 failed + 12 errors" outweighed "192 passed"
    in an assistant self-summary and mislabeled a success as a failure.
    """
    lower = (text or "").lower()
    success_matches = [p for p in _SUCCESS_SIGNALS if re.search(p, lower)]
    failure_matches = [p for p in _FAILURE_SIGNALS if re.search(p, lower)]
    success_hits = len(success_matches)
    failure_hits = len(failure_matches)

    if success_hits == 0 and failure_hits == 0:
        return None, []
    if failure_hits == 0:
        return 0.8, success_matches
    if success_hits == 0:
        return -0.8, failure_matches
    if abs(success_hits - failure_hits) >= 2:
        return (0.8, success_matches) if success_hits > failure_hits else (-0.8, failure_matches)
    return None, []


def infer_outcome_valence(text: str) -> float | None:
    """
    Infer a coarse valence from outcome language.
    Returns +0.8 for success, -0.8 for failure, None for neutral/ambiguous.
    """
    valence, _signals = infer_outcome_valence_detail(text)
    return valence


def compute_salience_multiplier(text: str) -> float:
    """
    Compute emotional salience multiplier from text signals.

    7th Cocktail Party sense — the Amygdala. Detects frustration,
    excitement, and urgency language. Returns a multiplier in [1.0, 1.6]
    that boosts pathway_strength at encoding time.

    Frustration weighs highest (1.0 per hit) because negative emotional
    memories encode more strongly than positive ones.
    """
    if not text:
        return 1.0

    frustration_hits = _match_signals(text, _FRUSTRATION_SIGNALS)
    excitement_hits = _match_signals(text, _EXCITEMENT_SIGNALS)
    urgency_hits = _match_signals(text, _URGENCY_SIGNALS)

    # Reuse existing outcome sense as additional input
    valence = infer_outcome_valence(text)
    outcome_boost = 0.5 if valence is not None else 0.0

    # Weight frustration highest (amygdala: negative > positive)
    raw_score = (
        frustration_hits * 1.0 +
        excitement_hits * 0.7 +
        urgency_hits * 0.8 +
        outcome_boost
    )

    if raw_score == 0:
        return 1.0

    return min(1.0 + (raw_score * 0.15), 1.6)
