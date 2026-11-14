"""Step 3: the query_hits rows as a `graph_facts` bundle section (flag `[retrieval] graph_facts`, default off).

Made-up two-speaker store from tests/test_query_hits.py (real capture writes, no model, no benchmark data). Pins: the
flag; the fixed-shape fact lines, each with its source turn; the computed block per question-analysis shape (list,
count, latest, yes/no, when); no section without a subject, an object Concept or a fact, or when too broad; and that
compile_bundle carries graph_facts instead of graph_count when the flag is on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.thalamus import graph_facts as gf
from tests.b564_helpers import Q
from tests.test_query_hits import build

ON = {"retrieval": {"graph_facts": True}}
PETS = "What pets does Nora have?"


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "graph_facts.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


def shape(s):
    return SimpleNamespace(shape=s)


async def section(db, q, s="open", config=ON):
    return await gf.build_graph_facts_section(db, q, config, analysis=shape(s))


def test_flag_default_off_and_env():
    assert _DEFAULT_CONFIG["retrieval"]["graph_facts"] is False
    assert not gf.graph_facts_enabled(_DEFAULT_CONFIG)
    cfg = apply_env_overrides({"retrieval": {}}, environ={"CAMPY_GRAPH_FACTS": "1"})
    assert gf.graph_facts_enabled(cfg)


async def test_flag_off_gives_no_section(db, gw):
    await build(db, gw)
    assert await section(db, PETS, config={"retrieval": {}}) is None


async def test_fact_lines_keep_their_source_turn(db, gw):
    mids, facts = await build(db, gw)
    sec = await section(db, PETS)
    lines = sec.content[0]["text"].splitlines()
    assert lines == [
        '[fact] Nora · owns · Biscuit (dog) · said 2023-05-01 · "I adopted a puppy called Biscuit"',
        '[fact] Nora · owns · Mochi (dog) · said 2023-05-09 · "I adopted another puppy, Mochi"',
    ]
    assert sec.section_type == "graph_facts" and sec.source_node_ids == [facts["biscuit"], facts["mochi"]]


@pytest.mark.parametrize("s, head", [
    ("list", "[computed: list, 2 rows] Nora → Biscuit (dog); Mochi (dog)"),
    ("count", "[computed: count, 2 objects] Nora → Biscuit (dog); Mochi (dog)"),
    ("latest", "[computed: latest] Nora → Mochi (dog) (said 2023-05-09)"),
    ("yes_no", "[computed: exists] Nora → yes (2 rows)"),
    ("when", "[computed: dated, 2 rows, oldest first] Nora"),
])
async def test_computed_block_by_shape(db, gw, s, head):
    await build(db, gw)
    text = (await section(db, PETS, s)).content[0]["text"]
    assert text.splitlines()[0] == head and text.count("[fact]") == 2


async def test_no_section_without_subject_object_or_fact_or_when_too_broad(db, gw, monkeypatch):
    await build(db, gw)
    assert await section(db, "What pets does Zed have?") is None          # no subject
    assert await section(db, "What does Nora like?") is None               # no object Concept named
    assert await section(db, "Does Nora own a goldfish?") is None          # only an archived fact
    monkeypatch.setattr(gf, "MAX_FACTS", 1)
    assert await section(db, PETS) is None                                 # too broad


async def test_without_analysis_rows_are_plain_fact_lines(db, gw):
    await build(db, gw)
    text = (await gf.build_graph_facts_section(db, PETS, ON, analysis=None)).content[0]["text"]
    assert text.startswith("[fact] Nora · owns · Biscuit (dog)") and "[computed" not in text


async def test_compile_bundle_uses_graph_facts_instead_of_graph_count(db, gw):
    from campy.brain.thalamus.bundle_compiler import compile_bundle
    await build(db, gw)
    base = {"retrieval": {"conversation_token_budget": 0, "graph_count": True}}
    off = await compile_bundle(PETS, db, base)
    assert "graph_facts" not in [s.section_type for s in off.sections]
    on = await compile_bundle(PETS, db, {"retrieval": {**base["retrieval"], "graph_facts": True}})
    types = [s.section_type for s in on.sections]
    assert "graph_facts" in types and "graph_count" not in types
