"""B460: relation extraction must record which value replaced which.

Found by campy-benchmarks (2026-10-04): in a LoCoMo store built with
llama3.1:8b, 8 of 11 CHOSEN_OVER edges between a probe's current and retired
values pointed the wrong way -- "PostgreSQL 14 CHOSEN_OVER PostgreSQL 16"
from "We have completely migrated from PostgreSQL 14 to PostgreSQL 16",
"Zipkin CHOSEN_OVER OpenTelemetry OTel" from "Zipkin has been replaced by
OpenTelemetry OTel". Supersessions name the retired value first; Step 1b's
verb patterns handled neither the passive nor "from X to Y", so Step 3b's
LLM picked the relation, without REPLACES on offer or any statement of
direction, and took the first-named value as the head.
"""

from __future__ import annotations

import pytest


def _spacy_md_loads() -> bool:
    # Checked here rather than via `from conftest import SPACY_AVAILABLE`: in a
    # full `pytest tests/` run that import resolves to
    # tests/patent_claims/conftest.py, which has no such name, and every test
    # using it is silently skipped. (tests/conftest.py stubs spacy.load to
    # raise when spaCy is unusable, so this is False there too.)
    try:
        import spacy

        spacy.load("en_core_web_md")
        return True
    except Exception:  # noqa: BLE001 -- missing model, stubbed spaCy, broken pydantic: all "no"
        return False


needs_spacy = pytest.mark.skipif(not _spacy_md_loads(), reason="needs spaCy with en_core_web_md")


@pytest.fixture(scope="module")
def rels():
    import spacy

    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations

    nlp = spacy.load("en_core_web_md")
    return lambda text: [(r["head"], r["relation_type"], r["tail"]) for r in extract_relations(nlp(text), [])]


@needs_spacy
@pytest.mark.parametrize("text, expected", [
    # LoCoMo's own supersession sentences, which produced inverted edges
    (("CRITICAL UPDATE: We have completely migrated from PostgreSQL 14 to PostgreSQL 16. "
      "Constraint: do NOT use PostgreSQL 14 anymore, all new deployments target PostgreSQL 16."),
     ("PostgreSQL 16", "REPLACES", "PostgreSQL 14")),
    (("Final decision: Zipkin has been replaced by OpenTelemetry OTel. Constraint: strictly use "
      "OpenTelemetry OTel for tracing, do NOT use Jaeger standalone or Zipkin."),
     ("OpenTelemetry OTel", "REPLACES", "Zipkin")),
    ("Final decision: Logstash has been replaced by Vector to OpenSearch.",  # two passive subjects
     ("Vector", "REPLACES", "Logstash")),
    ("Final decision: CentOS 7 has been replaced by Debian 12 Bookworm slim.",
     ("Debian 12 Bookworm slim", "REPLACES", "CentOS 7")),
    ("Final decision: us-west-2 has been replaced by eu-central-1.",  # hyphenated names, split by the tokenizer
     ("eu-central-1", "REPLACES", "us-west-2")),
    ("Final decision: Vue 2 has been replaced by React 19 with Next.js.",
     ("React 19", "REPLACES", "Vue 2")),
    # the same constructions outside the fixture's wording
    ("We switched from Jenkins to GitHub Actions last week.", ("GitHub Actions", "REPLACES", "Jenkins")),
    ("Memcached was superseded by Redis cluster on port 6379.", ("Redis cluster", "REPLACES", "Memcached")),
    ("The token is required by the gateway.", ("gateway", "REQUIRES", "token")),
    # active voice is unchanged
    ("OpenTelemetry replaced Zipkin.", ("OpenTelemetry", "REPLACES", "Zipkin")),
])
def test_step1b_names_the_new_value_as_head(rels, text, expected):
    assert expected in rels(text)


@needs_spacy
def test_step1b_needs_both_ends_of_a_move(rels):
    # "migrate X to Y" names no retired value: no edge rather than a guess
    assert rels("Update: Pickle is deprecated; migrate serialization to MessagePack.") == []


def test_step3b_prompt_offers_replaces_and_states_direction():
    from campy.brain.temporal_lobe.loop.step3b_relations import (
        SEMANTIC_TYPES,
        extract_semantic_relations,
    )

    seen = []

    class LLM:
        def chat(self, messages):
            seen.append(messages[0]["content"])
            return '{"head": "PostgreSQL 16", "relation_type": "REPLACES", "tail": "PostgreSQL 14", "confidence": 0.9}'

    out = extract_semantic_relations(
        [{"text": "PostgreSQL 14"}, {"text": "PostgreSQL 16"}],
        "We migrated from PostgreSQL 14 to PostgreSQL 16.", LLM())
    assert "REPLACES" in SEMANTIC_TYPES
    assert out and out[0]["head"] == "PostgreSQL 16" and out[0]["relation_type"] == "REPLACES"
    prompt = seen[0]
    assert '"A REPLACES B": A supersedes B' in prompt
    assert '"A CHOSEN_OVER B": A was selected instead of B' in prompt
    assert "whatever order the sentence names them in" in prompt


def test_llm_relation_on_a_step1b_pair_is_dropped_in_either_direction():
    from campy.brain.temporal_lobe.loop.orchestrator import _llm_relation_is_new

    covered = {("postgresql 16", "postgresql 14")}
    rel = lambda h, t: {"head": h, "relation_type": "CHOSEN_OVER", "tail": t}
    assert not _llm_relation_is_new(rel("PostgreSQL 16", "PostgreSQL 14"), covered)
    assert not _llm_relation_is_new(rel("PostgreSQL 14", "PostgreSQL 16"), covered)  # the inverted guess
    assert _llm_relation_is_new(rel("PostgreSQL 16", "AWS RDS"), covered)


def test_step1b_endpoint_names_an_entity_when_it_contains_it():
    from campy.brain.temporal_lobe.loop.orchestrator import _names_entity

    ents = {"postgresql", "tls"}
    assert _names_entity("PostgreSQL 16", ents)
    assert _names_entity("Strict TLS 1.3", ents)
    assert not _names_entity("TLSv2-ish", {"tls 1.3"})
    assert not _names_entity("Postgres", ents)
    assert not _names_entity("mtls", {"tls"})  # whole words only
