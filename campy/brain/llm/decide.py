"""
B460 — constrained choices with model-derived probabilities.

A decision step asks the model to pick one of a fixed set of options, labelled
A, B, C, ... and to answer with the letter only. When the provider returns
token log-probabilities, the probability of each option is read from the
first answer token's distribution (renormalised over the valid letters).
That replaces asking the model to write its own "confidence" number, which is
not a probability.

When the provider gives no log-probabilities (Bedrock, some OpenAI-compatible
gateways, test doubles), the choice is parsed from the text and `probs` is
None: callers must treat confidence as unknown rather than invent one.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from string import ascii_uppercase

_logger = logging.getLogger(__name__)

# Default top-1 vs top-2 probability margin under which a decision is a near
# tie (B460 card default). Callers may pass their own.
NEAR_TIE_MARGIN = 0.15


@dataclass
class Decision:
    choice: str | None                       # option label, None if unparseable
    probs: dict[str, float] | None = None    # label -> probability, None if unavailable
    source: str = "none"                     # "logprobs" | "text" | "none"
    raw: str = ""
    top_two: tuple[str, str] | None = field(default=None, init=False)

    def __post_init__(self):
        if self.probs and len(self.probs) >= 2:
            ranked = sorted(self.probs, key=self.probs.get, reverse=True)
            self.top_two = (ranked[0], ranked[1])

    @property
    def probability(self) -> float | None:
        """Probability of the chosen option, or None if unknown."""
        if self.probs is None or self.choice is None:
            return None
        return self.probs.get(self.choice)

    @property
    def margin(self) -> float | None:
        """Top-1 minus top-2 probability, or None if unknown."""
        if self.top_two is None:
            return None
        a, b = self.top_two
        return self.probs[a] - self.probs[b]

    def near_tie(self, margin: float = NEAR_TIE_MARGIN) -> bool:
        m = self.margin
        return m is not None and m < margin


def option_letters(labels: list[str]) -> dict[str, str]:
    """{'A': labels[0], 'B': labels[1], ...}"""
    if len(labels) > len(ascii_uppercase):
        raise ValueError("too many options")
    return dict(zip(ascii_uppercase, labels))


def options_block(labels: list[str], descriptions: dict[str, str] | None = None) -> str:
    """Render the lettered option list plus the answer instruction."""
    lines = []
    for letter, label in option_letters(labels).items():
        desc = (descriptions or {}).get(label)
        lines.append(f"{letter}) {label}" + (f": {desc}" if desc else ""))
    return ("Options:\n" + "\n".join(lines)
            + "\n\nAnswer with the single letter of the best option, nothing else.")


def _letter_of(token: str, letters: dict[str, str]) -> str | None:
    t = token.strip().strip(").:*").upper()
    return t if len(t) == 1 and t in letters else None


def _parse_text(text: str, letters: dict[str, str]) -> str | None:
    """Letter answer first ('B', 'B)', '(B)'); else a unique option label in the text."""
    stripped = text.strip()
    m = re.match(r"^\(?([A-Za-z])[).:]?(\s|$)", stripped)
    if m and m.group(1).upper() in letters:
        return letters[m.group(1).upper()]
    found = [label for label in letters.values()
             if re.search(rf"\b{re.escape(label)}\b", text, re.IGNORECASE)]
    return found[0] if len(found) == 1 else None


def _probs_from_top_logprobs(top: list[tuple[str, float]],
                             letters: dict[str, str]) -> dict[str, float] | None:
    mass: dict[str, float] = {}
    for token, logprob in top:
        letter = _letter_of(token, letters)
        if letter is not None:
            mass[letters[letter]] = mass.get(letters[letter], 0.0) + math.exp(logprob)
    total = sum(mass.values())
    if total <= 0:
        return None
    return {label: mass.get(label, 0.0) / total for label in letters.values()}


def decide(llm_client, prompt: str, labels: list[str]) -> Decision:
    """
    Ask `llm_client` to choose one of `labels`. `prompt` should already
    contain options_block(labels). Never raises; returns Decision(choice=None)
    on failure.
    """
    letters = option_letters(labels)
    messages = [{"role": "user", "content": prompt}]
    try:
        chat_choice = getattr(llm_client, "chat_choice", None)
        if callable(chat_choice):
            text, top = chat_choice(messages)
            if top:
                probs = _probs_from_top_logprobs(top, letters)
                if probs:
                    choice = max(probs, key=probs.get)
                    return Decision(choice, probs, "logprobs", text)
        else:
            text = llm_client.chat(messages)
        choice = _parse_text(text or "", letters)
        return Decision(choice, None, "text" if choice else "none", text or "")
    except Exception:
        _logger.exception("decide(): LLM call failed")
        return Decision(None, None, "none", "")


def log_near_tie(step: str, decision: Decision, context: str = "") -> None:
    """Structured log line for near-ties, so recurring vague pairs can be found."""
    if decision.top_two is None:
        return
    a, b = decision.top_two
    _logger.info("[Gate:NearTie] step=%s pair=%s|%s p=%.2f|%.2f margin=%.2f context=%r",
                 step, a, b, decision.probs[a], decision.probs[b], decision.margin,
                 context[:80])
