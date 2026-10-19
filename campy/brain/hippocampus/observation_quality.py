"""B486: a read-time quality score for Observations.

Observations are tagged at capture and never dropped there; this module lets
the *reader* (`bundle_compiler._stage_observations`) rank them by how likely
each is to be a specific, true-looking, speaker-grounded fact. It is a pure
function over the stored row: stdlib only, no model, no I/O, no dataset
special-casing.

`observation_quality(obs) -> (score, reasons)`; `score` is in [0, 1] (1 = no
problem found) and `reasons` names every rule that fired, so a score can be
audited. Rules (each subtracts a penalty):

  no_content_object   the object has no content word left after stopwords,
                      pronouns and generic words ("people", "day", "made")
  generic_object      the only content words are generic nouns / bare verbs
  thin_object         one content word under did / plans / has_attribute
  bad_subject         subject is second person ("you", "your X") or a
                      greeting / exclamation, or a bare demonstrative
  long_subject        the subject is a clause, not an entity
  quote_about_listener subject is the speaker but the quote addresses the
                      listener ("your wedding") with no first person in it
  greeting_quote      the quote is a greeting / thanks / imperative opener
  short_quote         under four words
  name_only_attribute has_attribute whose value is just {'name': ...}
  fragment_object     is_a / has_attribute object is a clause ("where I practice")
  vague_relation      predicate relates_to (no relation named)
  ungrounded_object   no content word of the object occurs in the quote
  plan_without_future predicate plans, quote has no future / intent cue
"""

from __future__ import annotations

import re
from typing import Any, Mapping

PENALTIES: dict[str, float] = {
    "no_content_object": 0.60,
    "generic_object": 0.45,
    "thin_object": 0.15,
    "bad_subject": 0.65,
    "long_subject": 0.30,
    "quote_about_listener": 0.50,
    "greeting_quote": 0.50,
    "short_quote": 0.35,
    "name_only_attribute": 0.45,
    "fragment_object": 0.40,
    "vague_relation": 0.40,
    "ungrounded_object": 0.35,
    "plan_without_future": 0.35,
}

_PRONOUNS = frozenset(
    "i me my mine myself we us our ours ourselves you your yours yourself he him his she her hers "
    "it its they them their theirs this that these those one someone something anyone anything "
    "everything everyone all both each other another".split()
)
# Generic nouns, adjectives and bare verbs that carry no fact on their own.
_GENERIC = frozenset(
    "people person thing things stuff day days time times way ways lot lots bit kind sort "
    "made make makes making get gets got getting go goes went going do does did done doing "
    "try tried trying explore keep kept check working updated need needs needed see saw want wants wanted take took "
    "have has had having be is are was were been being come came let help use used say said "
    "good great nice cool awesome amazing lovely fun calming happy glad sorry sure really very "
    "so too just also back here there out up down over again yet still even much many more most "
    "life work world place somewhere sometime someday anytime soon today tomorrow yesterday "
    "tonight now then well like love enjoy it's i'm don't can't won't".split()
)
_STOP_EXTRA = frozenset("a an the and or but of to in on at for with from by as if so not no yes".split())

_FIRST_PERSON_RE = re.compile(r"(?<![\w'])(i|i'm|i've|i'd|i'll|me|my|mine|myself|we|we're|we've|our|let's)(?![\w])", re.I)
_SECOND_PERSON_RE = re.compile(r"(?<![\w'])(you|your|yours|you're|you've|you'd|you'll|yourself)(?![\w])", re.I)
_GREETING_RE = re.compile(
    r"^\W*(thanks|thank you|thank|enjoy|hey|hi|hello|bye|goodbye|wow|congrats|congratulations|cheers|"
    r"good luck|take care|have a|see you|nice one|great job|well done|sounds good|no worries|sorry)\b", re.I)
_FUTURE_RE = re.compile(
    r"\b(will|won't|going to|gonna|plan|planning|plans|want|wanna|wish|hope|hoping|might|may|maybe|"
    r"let's|can't wait|cannot wait|decide|decided|someday|soon|next|intend|aim|aiming|look forward|"
    r"looking forward|thinking of|thinking about|would|should|need to|have to|about to|sign up|signing up)\b|"
    r"\w+'ll\b", re.I)
_DEMONSTRATIVE = frozenset({"this", "that", "these", "those", "it", "they", "them", "there", "here", "one"})
_WORD_RE = re.compile(r"[^\W_]+(?:'[a-z]+)?", re.I)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _stopwords() -> frozenset[str]:
    try:
        from campy.brain.hippocampus.graph.vector_store import _FTS_STOPWORDS
        return frozenset(_FTS_STOPWORDS) | _STOP_EXTRA
    except Exception:  # pragma: no cover - the helper is a convenience only
        return _STOP_EXTRA


_STOP = _stopwords()


def _content(text: str) -> list[str]:
    return [w for w in _words(text) if w not in _STOP and w not in _PRONOUNS and w not in _GENERIC and len(w) > 1]


def _object_text(obs: Mapping[str, Any]) -> str:
    return str(obs.get("event_text") or obs.get("object_text") or "").strip()


def _stem(w: str) -> str:
    return w[:4]


def observation_quality(obs: Mapping[str, Any]) -> tuple[float, list[str]]:
    """Score one Observation row (a mapping with subject_text, predicate,
    object_text / event_text, evidence_text, speaker). Returns
    `(score in [0, 1], reasons)`."""
    get = obs.get
    subject = str(get("subject_text") or "").strip()
    predicate = str(get("predicate") or "").strip().lower()
    obj = _object_text(obs)
    quote = str(get("evidence_text") or "").strip()
    speaker = str(get("speaker") or "").strip().lower()
    reasons: list[str] = []

    def hit(name: str) -> None:
        if name not in reasons:
            reasons.append(name)

    # -- object ----------------------------------------------------------------
    is_name_only_dict = bool(re.fullmatch(r"\{\s*'name'\s*:\s*'[^']*'\s*\}", obj))
    obj_plain = obj if not obj.startswith("{") else " ".join(re.findall(r"'([^']*)'", obj))
    obj_words = [w for w in _words(obj_plain) if w not in _STOP]
    obj_content = _content(obj_plain)
    if is_name_only_dict:
        hit("name_only_attribute")
    if not obj_content:
        # every word is a pronoun / generic: nothing specific is claimed
        hit("no_content_object" if all(w in _PRONOUNS or w in _GENERIC for w in obj_words) else "generic_object")
    elif len(obj_content) == 1 and predicate in {"did", "plans", "has_attribute"} and len(obj_words) <= 1:
        hit("thin_object")
    first_word = (_words(obj_plain) or [""])[0]
    if predicate in {"is_a", "has_attribute"} and first_word in {
            "where", "when", "what", "how", "which", "who", "whether", "why"}:
        hit("fragment_object")
    if predicate == "relates_to":
        hit("vague_relation")

    # -- subject ---------------------------------------------------------------
    subj_words = _words(subject)
    low_subject = subject.lower()
    is_first = low_subject in {"i", "me", "we", "the user"} or (speaker and low_subject == speaker)
    if subj_words and (subj_words[0] in {"you", "your", "yours", "you're"} or "you" in subj_words[:3]
                       and low_subject.startswith("you")):
        hit("bad_subject")
    elif subject.endswith(("!", "?")) or (len(subj_words) == 1 and subj_words[0] in _DEMONSTRATIVE):
        hit("bad_subject")
    elif len(subj_words) > 4:
        hit("long_subject")

    # -- evidence quote --------------------------------------------------------
    qwords = _words(quote)
    if quote:
        if _GREETING_RE.match(quote):
            hit("greeting_quote")
        if len(qwords) < 4:
            hit("short_quote")
        if (is_first or not subject) and _SECOND_PERSON_RE.search(quote) and not _FIRST_PERSON_RE.search(quote):
            hit("quote_about_listener")
        if obj_content and not is_name_only_dict:
            qstems = {_stem(w) for w in qwords}
            if not any(_stem(w) in qstems for w in obj_content):
                hit("ungrounded_object")
        if predicate == "plans" and not _FUTURE_RE.search(quote) and str(get("polarity") or "") != "planned":
            hit("plan_without_future")

    score = 1.0 - sum(PENALTIES[r] for r in reasons)
    return max(0.0, min(1.0, round(score, 3))), reasons
