"""B464: a value the user states as replacing another must become a Concept.

Found by campy-benchmarks (2026-10-04): in a real-model LoCoMo store after
B460, 8 deprecation probes had no Concept for one of their values -- "Python
3.12", "eu-central-1", "Tailwind CSS v3", "Cloudflare DNS", "pytest", "Debian
12 Bookworm slim" (current), "yapf", "Vue 2" (retired). Step 1b extracts the
supersession ("pytest REPLACES nose2"), but the orchestrator kept a Step 1b
relation only when an endpoint named an entity that survived Step 2's gist
classification. When Step 2 classed the message's entities as noise, the
relation was dropped, and with it the only path by which the value became a
Concept ("pytest" and "Python 3.12" are no Step 1 entity at all).
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
    return lambda text: extract_relations(nlp(text), [])


@needs_spacy
@pytest.mark.parametrize("text, head, tail", [
    # the eight LoCoMo values that never became Concepts
    ("Final decision: Python 3.11 has been replaced by Python 3.12.", "Python 3.12", "Python 3.11"),
    ("Final decision: us-west-2 has been replaced by eu-central-1.", "eu-central-1", "us-west-2"),
    ("Final decision: yapf has been replaced by Ruff and Black.", "Ruff", "yapf"),
    ("Final decision: Bulma has been replaced by Tailwind CSS v3.", "Tailwind CSS v3", "Bulma"),
    ("Final decision: Route53 has been replaced by Cloudflare DNS.", "Cloudflare DNS", "Route53"),
    ("Final decision: nose2 has been replaced by pytest.", "pytest", "nose2"),
    ("Final decision: Vue 2 has been replaced by React 19 with Next.js.", "React 19", "Vue 2"),
    ("Final decision: CentOS 7 has been replaced by Debian 12 Bookworm slim.", "Debian 12 Bookworm slim", "CentOS 7"),
    # outside the fixture's wording
    ("We switched from Jenkins to GitHub Actions last week.", "GitHub Actions", "Jenkins"),
    ("Memcached was superseded by Redis cluster on port 6379.", "Redis cluster", "Memcached"),
    # B466: "replace B with C" -- before it, this gave "Our team REPLACES flake8"
    ("Our team replaced flake8 with ruff.", "ruff", "flake8"),
])
def test_step1b_marks_supersessions_between_names(rels, text, head, tail):
    from campy.brain.temporal_lobe.loop.orchestrator import _stated_supersession

    out = rels(text)
    match = [r for r in out if (r["head"], r["relation_type"], r["tail"]) == (head, "REPLACES", tail)]
    assert match, out
    assert match[0]["names"] is True
    assert _stated_supersession(match[0])


@needs_spacy
@pytest.mark.parametrize("text", [
    "The new version replaces the old one.",
    "This approach replaces the manual process.",
    "The team deprecated the old API.",
    "We replaced it.",
    "We replaced it with the new one.",
    "The team replaced the old process with a script.",
])
def test_step1b_supersession_between_common_nouns_is_not_a_stated_value(rels, text):
    from campy.brain.temporal_lobe.loop.orchestrator import _stated_supersession

    assert not any(_stated_supersession(r) for r in rels(text))


def test_stated_supersession_needs_replaces_between_two_names():
    from campy.brain.temporal_lobe.loop.orchestrator import _stated_supersession

    rel = lambda h, t, typ="REPLACES", names=True: {
        "head": h, "relation_type": typ, "tail": t, "names": names}
    assert _stated_supersession(rel("pytest", "nose2"))
    assert not _stated_supersession(rel("pytest", "nose2", names=False))
    assert not _stated_supersession(rel("pytest", "nose2", typ="REQUIRES"))
    assert not _stated_supersession({"head": "pytest", "relation_type": "REPLACES", "tail": "nose2"})
    assert not _stated_supersession(rel("pytest", "PyTest"))  # a value does not replace itself
    assert not _stated_supersession(rel("pytest", "0.92"))  # junk endpoint


class _Result:
    def __init__(self):
        self._rows = []

    def has_next(self):
        return False

    def get_next(self):
        return None


class _DB:
    """Records writes; every lookup finds nothing."""

    def __init__(self):
        self.writes = []

    def execute(self, query, params=None):
        return _Result()

    async def execute_write(self, query, params=None):
        self.writes.append({"query": query, "params": params or {}})

    async def execute_read(self, query, params=None):
        return []

    def vector_search(self, table_name, index_name, embedding, limit):
        return []


async def _concepts_written(text: str) -> set[str]:
    from campy.brain.temporal_lobe.loop.orchestrator import run_loop

    db = _DB()
    await run_loop(
        message_id="m-b464", text=text, db=db, llm_client=None,
        config={"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
                "nlp": {"spacy_model": "en_core_web_md"}},
        centroids={},  # no gist class scores above the noise floor: Step 2 drops every entity
    )
    return {w["params"]["text_raw"] for w in db.writes
            if "CREATE (c:Concept" in w["query"] and "text_raw" in w["params"]}


@needs_spacy
@pytest.mark.asyncio
async def test_stated_values_become_concepts_when_step2_drops_every_entity():
    texts = await _concepts_written(
        "Final decision: nose2 has been replaced by pytest. Constraint: strictly use pytest "
        "for testing_framework, do NOT use unittest or nose2.")
    assert {"pytest", "nose2"} <= texts
    assert not texts & {"Final decision", "Constraint", "Update"}


@needs_spacy
@pytest.mark.asyncio
async def test_versioned_value_named_only_by_the_relation_becomes_a_concept():
    # NER finds only "Python"; "Python 3.12" exists nowhere but in the relation
    texts = await _concepts_written(
        "Final decision: Python 3.11 has been replaced by Python 3.12. Constraint: strictly use "
        "Python 3.12 for python_version, do NOT use Python 3.9 or Python 3.11.")
    assert {"Python 3.12", "Python 3.11"} <= texts
    assert not texts & {"Final decision", "Constraint", "Python"}


@needs_spacy
@pytest.mark.asyncio
async def test_common_noun_supersession_still_needs_a_surviving_entity():
    assert await _concepts_written("The new version replaces the old one.") == set()
