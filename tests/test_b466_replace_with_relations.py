"""B466: "replace X with Y" records Y REPLACES X, whoever does the replacing.

Found while building B465 (`campy graph repair-supersession-edges`): the
LoCoMo fixture's user message "Architecture change: Replace Memcached with
Redis cluster on port 6379." gave Step 1b nothing, so the inverted edge
"Memcached CHOSEN_OVER Redis" could not be verified. Step 1b read a
replace-type verb only as subject -> verb -> object, which takes the person
doing the replacing as the new value ("We replaced Memcached with Redis":
We REPLACES Memcached) and finds nothing in an imperative or in "swap X for Y".
"""

from __future__ import annotations

import pytest

from tests._spacy import SPACY_AVAILABLE

needs_spacy = pytest.mark.skipif(not SPACY_AVAILABLE, reason="needs spaCy with en_core_web_md")


@pytest.fixture(scope="module")
def rels():
    import spacy

    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations

    nlp = spacy.load("en_core_web_md")
    return lambda text: [(r["head"], r["relation_type"], r["tail"]) for r in extract_relations(nlp(text), [])]


@needs_spacy
@pytest.mark.parametrize("text, expected", [
    # the LoCoMo fixture's message: an imperative, no subject
    ("Architecture change: Replace Memcached with Redis cluster on port 6379.",
     ("Redis cluster", "REPLACES", "Memcached")),
    ("We replaced Memcached with Redis.", ("Redis", "REPLACES", "Memcached")),
    ("The team swapped Jenkins for GitHub Actions.", ("GitHub Actions", "REPLACES", "Jenkins")),
    ("We swapped out Jenkins for GitHub Actions.", ("GitHub Actions", "REPLACES", "Jenkins")),
    ("We substituted REST with gRPC.", ("gRPC", "REPLACES", "REST")),
    ("We decided to replace Memcached with Redis.", ("Redis", "REPLACES", "Memcached")),
    # the passive of the same construction
    ("Memcached was replaced with Redis.", ("Redis", "REPLACES", "Memcached")),
    ("Jenkins was swapped for GitHub Actions.", ("GitHub Actions", "REPLACES", "Jenkins")),
])
def test_step1b_replace_x_with_y_names_y_as_head(rels, text, expected):
    assert rels(text) == [expected]


@needs_spacy
def test_step1b_substitute_x_for_y_names_x_as_head(rels):
    # "substitute X for Y" puts X in Y's place -- the reverse of "swap X for Y"
    assert rels("We substituted gRPC for REST.") == [("gRPC", "REPLACES", "REST")]


@needs_spacy
@pytest.mark.parametrize("text", [
    "Do not replace Memcached with Redis.",   # a negated replacement states none
    "We did not replace Memcached with Redis.",  # ... not even "We REPLACES Memcached"
    "We swapped seats with the other team.",  # "with" belongs to the object, not the verb
    "We traded messages with the vendor.",    # "trade/exchange X with Y" is not a replacement
])
def test_step1b_no_replacement_read_where_none_is_stated(rels, text):
    assert rels(text) == []


@needs_spacy
def test_step1b_replace_without_with_is_unchanged(rels):
    assert rels("OpenTelemetry replaced Zipkin.") == [("OpenTelemetry", "REPLACES", "Zipkin")]
