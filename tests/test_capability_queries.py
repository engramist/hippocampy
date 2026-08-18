"""
Tests for B317 — Named-Query Eval Pack: bounded multi-hop capability
conformance suite.

Real, embedded, file-backed Kùzu database via KuzuClient — the same pattern
as tests/test_provenance.py / tests/test_authority.py — with embeddings
monkeypatched to a fixed vector so nothing here depends on network access to
a sentence-transformers / Ollama endpoint. The fixture graph's own semantic
(Q5) embeddings are deterministic, hand-constructed vectors baked into
benchmarks/capability_eval/fixtures.py — they never touch the (patched)
embedding model at all; only init_schema()'s startup dimension-validation
probe does.

Seeds via `benchmarks.capability_eval.fixtures.seed_fixture_graph()` — the
REAL `ingest_entities()` / `ingest_facts()` path, never raw Cypher — then
runs each of the five `capability.*` named queries through
`GraphGateway.run()` and asserts against the exact expected sets hand-traced
in `benchmarks/capability_eval/questions.py`.

This file doubles as the backend-conformance suite `benchmarks/capability_eval/
README.md` documents: any storage adapter claiming to back Campy is expected
to pass this file unmodified against the same fixture.
"""

from __future__ import annotations

import ast
import inspect
import re

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.provenance import drop_projections
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools.lessons import upsert_lesson

from benchmarks.capability_eval import fixtures as capability_fixtures
from benchmarks.capability_eval import questions as q

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

# Matches fixtures.py's module-private `_SOURCE` — duplicated here as a
# literal (per the B317 card's own Task 2 instruction) rather than imported,
# since a test asserting behavior against "the fixture's source string"
# should pin the actual string, not silently track a private rename.
_FIXTURE_SOURCE = "harvest:capability-eval-fixture"

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """See tests/test_provenance.py's identical fixture for why this patches
    each consuming module's already-bound `emb` object directly rather than
    the dotted import path. Only schema.py's startup dimension-validation
    probe and lessons.py's upsert_lesson() (used by the drop_projections
    round-trip test below) call a real embedding function anywhere in this
    file's call graph — the fixture graph's own Q5 embeddings are supplied
    as explicit vectors and never touch emb.embed() at all."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import lessons as _lessons_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    monkeypatch.setattr(_schema_mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)
    monkeypatch.setattr(_lessons_mod.emb, "embed", _fake_embed)


async def _seeded_gateway(tmp_path, name: str = "capability.db"):
    """Fresh temp Kùzu DB, schema initialized, fixture graph seeded through
    the real ingest path. Returns (db, gateway) — caller is responsible for
    db.close() (mirrors tests/test_authority.py's try/finally pattern)."""
    db = KuzuClient(str(tmp_path / name))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    gateway = GraphGateway(db, REGISTRY)
    await capability_fixtures.seed_fixture_graph(gateway)
    return db, gateway


def _normalize_q5(rows) -> list[dict]:
    """Round similarity to tame float noise from array_cosine_similarity(),
    and turn `requires` into a set so element order never matters."""
    out = []
    for row in rows:
        out.append(
            {
                "entity_id": row["entity_id"],
                "label": row["label"],
                "similarity": round(row["similarity"], 6),
                "requires": set(row["requires"]) if row["requires"] else set(),
            }
        )
    return out


def _normalize_q4(rows) -> list[dict]:
    out = []
    for row in rows:
        out.append(
            {
                "producer_id": row["producer_id"],
                "producer_type": row["producer_type"],
                "approved_by": set(row["approved_by"]) if row["approved_by"] is not None else None,
                "reads": set(row["reads"]) if row["reads"] is not None else None,
                "deployed_on": set(row["deployed_on"]) if row["deployed_on"] is not None else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Registration + gateway-only access + bounded-hop static checks
# ---------------------------------------------------------------------------

_FIVE_QUESTION_NAMES = [item["name"] for item in q.QUESTIONS]


def test_all_five_questions_registered_in_shared_registry():
    for name in _FIVE_QUESTION_NAMES:
        assert name in REGISTRY, f"{name} is not registered"
    assert len(_FIVE_QUESTION_NAMES) == 5


def test_facts_and_capability_modules_never_call_execute_raw():
    """AC: 'None of them use execute_raw()' — a real AST assertion against
    both the write path (facts.py) and the query definitions
    (capability.py): looks for an actual `.execute_raw` attribute access
    anywhere in the parsed module, not a plain substring search (both
    modules' docstrings *mention* `GraphGateway.execute_raw()` in prose,
    which a naive `"execute_raw" not in src` check would misfire on)."""
    from campy.brain.hippocampus import facts as facts_mod
    from campy.brain.hippocampus.graph.queries import capability as capability_mod

    for mod in (facts_mod, capability_mod):
        tree = ast.parse(inspect.getsource(mod))
        offenders = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "execute_raw"
        ]
        assert not offenders, f"{mod.__name__} contains an actual execute_raw attribute access"


@pytest.mark.parametrize("name", _FIVE_QUESTION_NAMES)
def test_query_cypher_has_no_unbounded_star_quantifier(name):
    """AC: every query is bounded. A bare unbounded `*` quantifier (not
    immediately followed by a digit — i.e. not part of an `N..M` hop-bound
    form) must never appear in any of the five's registered Cypher."""
    cypher = REGISTRY.get(name).cypher
    assert re.search(r"\*(?!\d)", cypher) is None, (
        f"{name}: found a '*' not immediately followed by a digit — looks like an "
        "unbounded variable-length quantifier"
    )


# Q1-Q4 all traverse a variable-length relationship pattern and must carry an
# explicit N..M hop bound in their Cypher (`*1..5`, `*1..4`, `*1..6`). Q5
# (reuse_candidates) has no variable-length pattern at all — it matches a
# single candidate node plus one fixed-depth OPTIONAL MATCH hop — so there is
# no `*` quantifier to bound in the first place; its "bounded" property is
# that it never introduces one, covered by the no-unbounded-star check above.
_MULTI_HOP_QUESTION_NAMES = [name for name in _FIVE_QUESTION_NAMES if name != "capability.reuse_candidates"]


@pytest.mark.parametrize("name", _MULTI_HOP_QUESTION_NAMES)
def test_query_cypher_has_explicit_hop_bound(name):
    cypher = REGISTRY.get(name).cypher
    assert re.search(r"\*\d+\.\.\d+", cypher), f"{name}: no explicit N..M hop bound found in cypher"


def test_reuse_candidates_has_no_variable_length_pattern_at_all():
    """Documents *why* Q5 is exempt from the explicit-hop-bound check above:
    its Cypher has zero variable-length quantifiers to bound — every hop is
    a single fixed-depth OPTIONAL MATCH."""
    cypher = REGISTRY.get("capability.reuse_candidates").cypher
    assert "*" not in cypher


# ---------------------------------------------------------------------------
# Q1 — capability.permitted_paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q1_permitted_paths_default_excludes_superseded(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.permitted_paths", **q.Q1_PARAMS)
        assert result == q.Q1_EXPECTED
        assert "cap.lint_code_old" not in {r["entity_id"] for r in result}
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q1_permitted_paths_include_superseded_recovers_legacy_lint(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.permitted_paths", **q.Q1_PARAMS_INCLUDE_SUPERSEDED)
        assert result == q.Q1_EXPECTED_INCLUDE_SUPERSEDED
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Q2 — capability.explain_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q2_explain_path_primary_case(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.explain_path", **q.Q2_PARAMS)
        assert result == q.Q2_EXPECTED
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q2_explain_path_superseded_policy_hidden_by_default(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.explain_path", **q.Q2_SUPERSEDED_PARAMS)
        assert result == q.Q2_SUPERSEDED_EXPECTED
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q2_explain_path_include_superseded_recovers_legacy_policy(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run(
            "capability.explain_path", **q.Q2_SUPERSEDED_PARAMS_INCLUDE_SUPERSEDED
        )
        assert result == q.Q2_SUPERSEDED_EXPECTED_INCLUDE_SUPERSEDED
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Q3 — capability.impact_of
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q3_impact_of_default_excludes_superseded_staging_pipeline(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.impact_of", **q.Q3_PARAMS)
        got = {row["entity_type"]: set(row["entity_ids"]) for row in result}
        assert got == q.Q3_EXPECTED
        assert "workflow.staging_pipeline" not in got.get("workflow", set())
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q3_impact_of_include_superseded_recovers_staging_pipeline(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.impact_of", **q.Q3_PARAMS_INCLUDE_SUPERSEDED)
        got = {row["entity_type"]: set(row["entity_ids"]) for row in result}
        assert got == q.Q3_EXPECTED_INCLUDE_SUPERSEDED
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q3_impact_of_deduplicates_diamond_dependency(tmp_path):
    """agent.release_bot reaches infra.terraform_prod_cluster via TWO
    distinct 2-hop paths (through workflow.ci_pipeline and
    workflow.cd_pipeline) — it must appear exactly once in the 'agent'
    group's raw collected list, not merely 'be present' in a set that would
    silently hide a duplicate."""
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.impact_of", **q.Q3_PARAMS)
        agent_row = next(row for row in result if row["entity_type"] == "agent")
        assert agent_row["entity_ids"].count("agent.release_bot") == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Q4 — capability.lineage_of
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q4_lineage_of_default_excludes_superseded_release_config(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.lineage_of", **q.Q4_PARAMS)
        got = _normalize_q4(result)
        assert got == _normalize_q4(q.Q4_EXPECTED)
        build_run_row = next(r for r in got if r["producer_id"] == "evidence.build_run_42")
        assert "data.release_config" not in (build_run_row["reads"] or set())
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q4_lineage_of_include_superseded_recovers_release_config(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.lineage_of", **q.Q4_PARAMS_INCLUDE_SUPERSEDED)
        got = _normalize_q4(result)
        assert got == _normalize_q4(q.Q4_EXPECTED_INCLUDE_SUPERSEDED)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Q5 — capability.reuse_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q5_reuse_candidates_default(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.reuse_candidates", **q.Q5_PARAMS)
        assert _normalize_q5(result) == _normalize_q5(q.Q5_EXPECTED)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q5_reuse_candidates_include_superseded_recovers_old_relay(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.reuse_candidates", **q.Q5_PARAMS_INCLUDE_SUPERSEDED)
        assert _normalize_q5(result) == _normalize_q5(q.Q5_EXPECTED_INCLUDE_SUPERSEDED)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q5_below_floor_and_unsatisfiable_entities_never_appear(tmp_path):
    """cap.image_resizer (0.20 similarity, below the 0.70 floor) and
    cap.unreliable_forwarder (0.80 similarity, above the floor, but its
    REQUIRES target is superseded at the node level) must never appear in
    either scenario — proving the similarity floor and the satisfiability
    check are independent filters."""
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        for params in (q.Q5_PARAMS, q.Q5_PARAMS_INCLUDE_SUPERSEDED):
            result = await gateway.run("capability.reuse_candidates", **params)
            got_ids = {row["entity_id"] for row in result}
            assert got_ids.isdisjoint(q.Q5_NEVER_APPEARS), (params, got_ids)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_q5_finds_near_duplicate_via_vector_similarity_not_string_match(tmp_path):
    """cap.mailer_service's label ('Mailer Dispatch Unit') shares no words
    with the query's own label ('Send Email Notification') yet is found at
    ~0.90 similarity — a string/keyword matcher would miss it entirely, so
    finding it proves this query is doing real vector similarity."""
    db, gateway = await _seeded_gateway(tmp_path)
    try:
        result = await gateway.run("capability.reuse_candidates", **q.Q5_PARAMS)
        by_id = {row["entity_id"]: row for row in result}
        assert "cap.mailer_service" in by_id
        assert by_id["cap.mailer_service"]["similarity"] == pytest.approx(0.90, abs=1e-6)
        assert by_id["cap.email_notifier"]["similarity"] == pytest.approx(1.0, abs=1e-6)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# drop_projections(source=...) round-trip — the fixture graph is fully
# rebuildable/discardable, and never touches earned memory in the same DB.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drop_projections_removes_fixture_graph_leaves_earned_lesson(tmp_path):
    """Seeds the fixture capability graph AND an 'earned' Lesson that
    deliberately shares the fixture's own `source` string (the strongest
    version of this safety proof — see provenance.drop_projections()'s
    docstring: 'an earned row that happens to share a source string is
    never a deletion candidate'). Then calls drop_projections(dry_run=False)
    and asserts the whole projected subgraph is gone while the earned
    Lesson survives untouched.

    Deviation from the card's literal `drop_projections(db, source=...)`
    phrasing: `provenance.py`'s `_PK_COLUMN` (and therefore
    `drop_projections()`'s *default* `tables=None` table list) only covers
    B312's PROVENANCE_TABLES — it does not know about `FactEntity`, B317's
    new node table. `drop_projections()` itself has no dependency on
    `_PK_COLUMN` inside its loop (it only matches on `n.source` /
    `n.authority`), so passing `tables=["FactEntity", "Lesson"]` explicitly
    works correctly and is exactly what tests/test_authority.py's own
    drop_projections tests already do for `Concept` — this file follows
    that established convention rather than relying on a default table list
    that would silently no-op on the projected capability subgraph.
    """
    db, gateway = await _seeded_gateway(tmp_path, name="drop_projections.db")
    try:
        before = db.execute("MATCH (n:FactEntity) RETURN count(n)").get_next()[0]
        assert before > 0

        lesson_result = await upsert_lesson(
            {
                "text": "earned lesson sharing the fixture's source string",
                "domain": "test",
                "source": _FIXTURE_SOURCE,
            },
            db,
            CONFIG,
        )
        lesson_id = lesson_result["lesson_id"]

        result = await drop_projections(
            db, source=_FIXTURE_SOURCE, dry_run=False, tables=["FactEntity", "Lesson"]
        )

        assert result["deleted"] == before
        assert result["skipped_earned"] == 1

        after = db.execute("MATCH (n:FactEntity) RETURN count(n)").get_next()[0]
        assert after == 0

        r = db.execute(
            "MATCH (l:Lesson {lesson_id: $id}) RETURN l.text_raw", {"id": lesson_id}
        )
        assert r.has_next()
        assert r.get_next()[0] == "earned lesson sharing the fixture's source string"

        # The projected subgraph is genuinely gone, not just undercounted —
        # a live named query against it now returns nothing rather than
        # erroring (Cypher MATCH against a missing node is just empty, not
        # an exception).
        empty = await gateway.run("capability.permitted_paths", **q.Q1_PARAMS)
        assert empty == []
    finally:
        db.close()


@pytest.mark.asyncio
async def test_drop_projections_dry_run_does_not_delete_fixture_graph(tmp_path):
    db, gateway = await _seeded_gateway(tmp_path, name="drop_projections_dry.db")
    try:
        before = db.execute("MATCH (n:FactEntity) RETURN count(n)").get_next()[0]
        assert before > 0

        result = await drop_projections(
            db, source=_FIXTURE_SOURCE, tables=["FactEntity"]
        )  # dry_run defaults True

        assert result["deleted"] == before
        after = db.execute("MATCH (n:FactEntity) RETURN count(n)").get_next()[0]
        assert after == before  # nothing actually deleted
    finally:
        db.close()
