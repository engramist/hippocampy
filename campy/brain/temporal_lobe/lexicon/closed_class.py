"""
campy/brain/temporal_lobe/lexicon/closed_class.py -- B565: a closed-class word is never a Concept.

A Concept is an entity or a kind (P8). Pronouns ("we", "it", "what", "something"), articles and determiners, and the
conjunctions and auxiliaries that have no noun or name reading are function words: storing one as a Concept makes a
question's "What" name it, and anchors facts on "We". Four of five benchmark-free principled stores held such Concepts
(written by the Loop and by the fact extractor's entity path).

The rule (`is_closed_class`): the label, with surrounding whitespace removed, is ONE word whose lower-case form is in
`CLOSED_CLASS_WORDS`, and it is not written in capitals of two letters or more ("US", "IT", "WHO" are names). The list
is grouped by grammatical class, and every word that also has a common noun or name reading is left out (will, may,
can, might, must, mine, do, does; prepositions such as down, past, like, round, over). Numerals and open-class stop words
("one", "other", "part", "show") are not function words and are not in it.

One list, one place: the capture writers call `is_closed_class` before creating a Concept, and the cleanup query
(`entity_hygiene.closed_class_concepts`) receives `CLOSED_CLASS_WORDS` as its VALUES parameter.
"""

from __future__ import annotations

_PRONOUNS = (
    # personal, object, possessive (without "mine"), reflexive
    "i me my you your yours yourself yourselves he him his himself she her hers herself it its itself "
    "we us our ours ourselves they them their theirs themselves "
    # demonstrative, interrogative and relative
    "this that these those what which who whom whose whatever whichever whoever "
    # indefinite
    "anything anyone anybody everything everyone everybody something someone somebody nothing nobody"
)
_DETERMINERS = "a an the each every some any both either neither"
_CONJUNCTIONS = "and or nor because although though unless whereas"
_AUXILIARIES = "am is are was were been being has had should would could shall"

CLOSED_CLASS_WORDS: frozenset[str] = frozenset(
    " ".join((_PRONOUNS, _DETERMINERS, _CONJUNCTIONS, _AUXILIARIES)).split()
)


def is_closed_class(text: str | None) -> bool:
    """True when `text` is a single closed-class word (see the module docstring); never for a capitalised acronym of
    two letters or more, or for more than one word."""
    word = (text or "").strip()
    if not word or len(word.split()) != 1:
        return False
    if len(word) >= 2 and word.isupper():
        return False
    return word.lower() in CLOSED_CLASS_WORDS
