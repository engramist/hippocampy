"""B496: no replacement edge for negated or person "swap" sentences; "substitute X with Y".

A negated replacement ("we did not replace Memcached with Redis") states no
supersession; writing "Redis REPLACES Memcached" retires a value that is still
current. "Swap seats with the other team" trades places, it does not replace a
technology. Rules are general constructions: negation scope over a replace-type
verb, and swap/exchange needing two named non-person things.
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
    ("We substituted REST with gRPC.", ("gRPC", "REPLACES", "REST")),
    ("The team substituted Jenkins with GitHub Actions.", ("GitHub Actions", "REPLACES", "Jenkins")),
    ("We swapped Memcached with Redis.", ("Redis", "REPLACES", "Memcached")),
])
def test_substitute_and_swap_with_between_things_replace(rels, text, expected):
    assert rels(text) == [expected]


@needs_spacy
@pytest.mark.parametrize("text", [
    "Do not replace Memcached with Redis.",
    "We did not replace Memcached with Redis.",
    "We never replaced Memcached with Redis.",
    "Don't replace Memcached with Redis.",
    "We decided not to replace Memcached with Redis.",
    "Instead of replacing Memcached with Redis, we kept it.",
    "OpenTelemetry did not replace Zipkin.",
])
def test_negated_replacement_writes_no_edge(rels, text):
    assert rels(text) == []


@needs_spacy
@pytest.mark.parametrize("text", [
    "We swapped seats with the other team.",
    "We swapped shifts with Dana.",
    "Alice swapped desks with Bob.",
    "We swapped Alice with Bob.",
])
def test_swap_with_people_or_places_is_not_a_replacement(rels, text):
    assert rels(text) == []


@needs_spacy
def test_unnegated_replacement_still_written(rels):
    assert rels("We replaced Memcached with Redis.") == [("Redis", "REPLACES", "Memcached")]
