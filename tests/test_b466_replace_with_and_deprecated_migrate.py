"""B466: Step 1b reads "replace X with Y" and "X is deprecated ... migrate to Y".

After B460 a real-model LoCoMo store still had 2 inverted supersession edges
(B465's repair dry run): "HS256 ... RS256" from "symmetric HS256 is
deprecated ... We must migrate to RS256 asymmetric keys" and "Memcached ...
Redis" from "Replace Memcached with Redis cluster". Step 1b had no pattern for
either: "replace X with Y" gave the subject ("We REPLACES Memcached") or
nothing, and "migrate to Y" without "from X" gave nothing, so Step 3b's LLM
guessed the direction.
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
    ("We replaced Memcached with Redis.", ("Redis", "REPLACES", "Memcached")),
    ("Replace Memcached with Redis cluster on port 6379.", ("Redis cluster", "REPLACES", "Memcached")),
    ("Memcached was replaced with Redis.", ("Redis", "REPLACES", "Memcached")),
    ("We swapped Jenkins for GitHub Actions.", ("GitHub Actions", "REPLACES", "Jenkins")),
    ("We substituted Vitest for Jest.", ("Vitest", "REPLACES", "Jest")),
])
def test_replace_with_names_the_new_value_as_head(rels, text, expected):
    assert expected in rels(text)


@needs_spacy
def test_the_subject_of_replace_with_is_not_an_endpoint(rels):
    assert not any(h == "We" for h, _, _ in rels("We replaced Memcached with Redis."))


@needs_spacy
@pytest.mark.parametrize("text, expected", [
    (("Security audit complete. Update constraint: symmetric HS256 is deprecated due to key "
      "distribution risks. We must migrate to RS256 asymmetric keys."),
     ("RS256 asymmetric keys", "REPLACES", "symmetric HS256")),
    ("Update: Pickle is deprecated; migrate serialization to MessagePack.",
     ("MessagePack", "REPLACES", "Pickle")),
    ("Python 3.9 is retired. Upgrade the services to Python 3.11.",
     ("Python 3.11", "REPLACES", "Python 3.9")),
])
def test_deprecated_then_migrate_to_names_the_new_value_as_head(rels, text, expected):
    assert expected in rels(text)


@needs_spacy
@pytest.mark.parametrize("text", [
    "Migrate serialization to MessagePack.",  # nothing retired
    "Pickle is deprecated.",  # nothing to move to
    "Python 2 is deprecated. Migrate the docs to the new wiki.",  # target is not a named value
    "The old wiki is deprecated. Move everything to the new one.",
])
def test_deprecated_then_migrate_needs_both_named_values(rels, text):
    assert not any(r == "REPLACES" for _, r, _ in rels(text))


@needs_spacy
def test_a_passive_agent_still_wins_over_with(rels):
    # "with Protobuf v3" describes the agent, it is not the new value
    out = rels("Final decision: REST has been replaced by gRPC with Protobuf v3.")
    assert ("gRPC", "REPLACES", "REST") in out
    assert not any(h == "Protobuf v3" for h, _, _ in out)
