"""
Tests for B317 — the bounded multi-hop conformance suite
(`campy/brain/hippocampus/graph/queries/capability.py`'s five named
queries, run through `GraphGateway` against a real temporary Kùzu
database seeded via `benchmarks/capability_eval/fixtures.py`).

This is the acceptance test the card exists to produce: every one of the
five customer questions gets an exact expected result set, not "returns
something." See `benchmarks/capability_eval/README.md` for the fixture's
scope notes (three joinable entity types; everything else is explicitly
synthetic) and its deliberate-difficulty inventory (blocked path,
superseded edge, near-duplicate pair, diamond dependency).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from benchmarks.capability_eval.fixtures import (
    APPROVER_RELEASE_MGR,
    APPROVER_SECURITY_TEAM,
    ARTIFACT_INTERMEDIATE,
    ARTIFACT_QUOTE_REPORT,
    CAP_DIAMOND_MID_A,
    CAP_DIAMOND_MID_B,
    CAP_DIAMOND_ROOT,
    CAP_DIAMOND_TOP,
    CAP_DUP_1,
    CAP_DUP_2,
    CAP_ENTRY,
    CAP_GUARDED_1,
    CAP_GUARDED_2,
    CAP_OPEN_1,
    CAP_OPEN_2,
    CAP_OPEN_3,
    CAP_REUSE_SATISFIABLE,
    CAP_REUSE_UNSATISFIABLE,
    MCP_UNSATISFIABLE_DEP,
    RUN_BUILD_482,
    SOURCE,
    seed_fixture_graph,
)
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.capability import _QUESTION_QUERIES
from campy.brain.hippocampus.schema import init_schema

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

_QUESTION_NAMES = (
    "capability.permitted_paths",
    "capability.explain_path",
    "capability.impact_of",
    "capability.lineage_of",
    "capability.reuse_candidates",
)

# Deterministic, well-separated pseudo-random 384-dim vectors used by the
# fake embedder below — genuinely varied per-dimension (not a constant
# vector; a constant vector is cosine-similarity ~1.0 with every other
# positive constant vector regardless of scale, which would silently
# defeat the "distinguishes near-duplicates from everything else" test).
def _prng_vector(seed: int) -> list[float]:
    import random
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(384)]


_V_DUP = _prng_vector(1001)
_V_SAT = _prng_vector(2002)


def _fake_embed(text, model_name=None):
    if text in ("Fast quote verification pass", "Velocity checking service for quotes"):
        # near-identical (tiny per-call jitter), NOT bit-identical — proves
        # this is a real cosine-similarity computation, not an object-identity
        # or exact-string shortcut.
        jitter = (abs(hash(text)) % 1000) * 1e-9
        return [v + jitter for v in _V_DUP]
    if text in ("Reuse candidate with satisfiable deps", "Reuse candidate with unsatisfiable deps"):
        jitter = (abs(hash(text)) % 1000) * 1e-9
        return [v + jitter for v in _V_SAT]
    return _prng_vector(abs(hash(text)) % (2**31))


def _fake_embed_batch(texts, model_name=None):
    return [_fake_embed(t) for t in texts]


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    from campy.brain.hippocampus import facts as _facts_mod
    from campy.brain.hippocampus import schema as _schema_mod

    for mod in (_facts_mod, _schema_mod):
        monkeypatch.setattr(mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


@pytest.fixture
def gw(tmp_path):
    db = KuzuClient(str(tmp_path / "capability.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    return GraphGateway(db, REGISTRY)


async def _seeded(gw_: GraphGateway) -> GraphGateway:
    """Seed `gw_`'s database with the fixture graph and return it
    unchanged — a plain async helper (not a fixture) so every test calls
    it explicitly and there's no ambiguity around async-fixture value
    resolution across pytest-asyncio versions/modes."""
    await seed_fixture_graph(gw_, {"embeddings": {"model": EMBEDDING_MODEL}})
    return gw_


def _by_entity_id(rows: list[dict]) -> dict:
    return {r["entity_id"]: r for r in rows}


# ---------------------------------------------------------------------------
# Non-negotiable: every query bounded (explicit hop limit, never unbounded `*`)
# ---------------------------------------------------------------------------

# An unbounded/open-ended quantifier: a bare `*]`, or `*N..]` with no upper
# bound. `*N..M` (both bounds present) is fine and is what every one of
# these queries uses.
_UNBOUNDED_STAR_RE = re.compile(r"\*(?:\d+\.\.)?\]|\*\]")


def test_all_five_questions_are_bounded_no_unbounded_star():
    by_name = {q.name: q for q in _QUESTION_QUERIES}
    assert set(by_name) == set(_QUESTION_NAMES)
    for name in _QUESTION_NAMES:
        cypher = by_name[name].cypher
        assert not _UNBOUNDED_STAR_RE.search(cypher), f"{name}: unbounded '*' traversal found"


def test_permitted_paths_hop_limit_is_5():
    q = REGISTRY.get("capability.permitted_paths")
    assert "*1..5]" in q.cypher.replace(" ", "")


def test_impact_of_hop_limit_is_4():
    q = REGISTRY.get("capability.impact_of")
    assert "*1..4]" in q.cypher.replace(" ", "")


def test_lineage_of_hop_limit_is_6():
    q = REGISTRY.get("capability.lineage_of")
    assert "*1..6]" in q.cypher.replace(" ", "")


def test_explain_path_and_reuse_candidates_have_no_variable_length_traversal_at_all():
    """Q2/Q5 don't need a `*` at all — one hop per pair (Q2) / a plain
    filtered scan + 1-hop REQUIRES check (Q5) — which is bounded by
    construction, the strictest form of bounded."""
    for name in ("capability.explain_path", "capability.reuse_candidates"):
        cypher = REGISTRY.get(name).cypher
        assert "*" not in cypher.replace("$", "")  # no variable-length quantifier at all


def test_all_five_questions_declare_include_superseded_param():
    for name in _QUESTION_NAMES:
        assert "include_superseded" in REGISTRY.get(name).params


# ---------------------------------------------------------------------------
# All five reached only through GraphGateway.run() — none use execute_raw()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_five_questions_callable_through_gateway_run(gw):
    gw_ = await _seeded(gw)
    r1 = await gw_.run("capability.permitted_paths", entry_id=CAP_ENTRY, trust_tier="public", include_superseded=False)
    assert isinstance(r1, list)
    r2 = await gw_.run("capability.explain_path", pairs=[{"from": CAP_ENTRY, "to": CAP_OPEN_1}], include_superseded=False)
    assert isinstance(r2, list)
    r3 = await gw_.run("capability.impact_of", entity_id=CAP_DIAMOND_ROOT, include_superseded=False)
    assert isinstance(r3, list)
    r4 = await gw_.run("capability.lineage_of", artifact_id=ARTIFACT_QUOTE_REPORT, include_superseded=False)
    assert isinstance(r4, list)
    r5 = await gw_.run("capability.reuse_candidates", entity_id=CAP_DUP_1, query_embedding=_V_DUP, floor=0.70, include_superseded=False)
    assert isinstance(r5, list)


# ---------------------------------------------------------------------------
# Q1 — capability.permitted_paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q1_permitted_paths_public_tier_excludes_guarded_branch(gw):
    gw_ = await _seeded(gw)
    rows = await gw_.run("capability.permitted_paths", entry_id=CAP_ENTRY, trust_tier="public", include_superseded=False)
    by_id = _by_entity_id(rows)

    assert set(by_id) == {CAP_OPEN_1, CAP_OPEN_2, CAP_OPEN_3}
    assert by_id[CAP_OPEN_1]["hops"] == 1
    assert by_id[CAP_OPEN_2]["hops"] == 2
    assert by_id[CAP_OPEN_3]["hops"] == 3


@pytest.mark.asyncio
async def test_q1_permitted_paths_elevated_tier_includes_guarded_branch(gw):
    gw_ = await _seeded(gw)
    rows = await gw_.run("capability.permitted_paths", entry_id=CAP_ENTRY, trust_tier="elevated", include_superseded=False)
    by_id = _by_entity_id(rows)

    assert set(by_id) == {CAP_OPEN_1, CAP_OPEN_2, CAP_OPEN_3, CAP_GUARDED_1, CAP_GUARDED_2}
    assert by_id[CAP_GUARDED_1]["hops"] == 1
    assert by_id[CAP_GUARDED_2]["hops"] == 2


@pytest.mark.asyncio
async def test_q1_excludes_superseded_edge_by_default(gw):
    """Directly supersede one live edge on the open chain (without
    replacement, simulating a retracted relationship) and prove the
    target it uniquely provided drops out of the default result — and
    comes back with include_superseded=True. A same-object re-ingest
    (facts.py's normal supersede+recreate flow) always leaves a live
    replacement edge to the same target, so it can't demonstrate this by
    itself; a direct gateway call is the honest way to prove the exclusion
    filter actually does something."""
    gw_ = await _seeded(gw)

    # CAP_OPEN_2 -> CAP_OPEN_3 is the only edge reaching CAP_OPEN_3.
    await gw_.run(
        "capability.supersede_edge_requires",
        subject_id=CAP_OPEN_2, object_id=CAP_OPEN_3,
        superseded_by="retracted", superseded_at=_NOW.isoformat(), reason="source_removed",
    )

    rows_default = await gw_.run("capability.permitted_paths", entry_id=CAP_ENTRY, trust_tier="public", include_superseded=False)
    assert CAP_OPEN_3 not in _by_entity_id(rows_default)
    assert {CAP_OPEN_1, CAP_OPEN_2} <= set(_by_entity_id(rows_default))

    rows_included = await gw_.run("capability.permitted_paths", entry_id=CAP_ENTRY, trust_tier="public", include_superseded=True)
    assert CAP_OPEN_3 in _by_entity_id(rows_included)


# ---------------------------------------------------------------------------
# Q2 — capability.explain_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q2_explain_path_returns_edge_provenance(gw):
    gw_ = await _seeded(gw)
    rows = await gw_.run(
        "capability.explain_path",
        pairs=[{"from": CAP_ENTRY, "to": CAP_OPEN_1}],
        include_superseded=False,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["from_id"] == CAP_ENTRY
    assert row["to_id"] == CAP_OPEN_1
    assert row["predicate"] == "FACT_REQUIRES"
    assert row["edge_confidence"] == 0.9  # live v2 confidence, not the superseded v1's 0.5


@pytest.mark.asyncio
async def test_q2_explain_path_surfaces_constrained_by_policy(gw):
    gw_ = await _seeded(gw)
    # CAP_GUARDED_1 is the node CONSTRAINED_BY the elevated-tier policy —
    # explain_path surfaces policies on a hop's SOURCE node, so the pair
    # must have CAP_GUARDED_1 as `from` (the next hop out of it).
    rows = await gw_.run(
        "capability.explain_path",
        pairs=[{"from": CAP_GUARDED_1, "to": CAP_GUARDED_2}],
        include_superseded=False,
    )
    assert len(rows) == 1
    policies = [p for p in rows[0]["policies"] if p["policy_id"] is not None]
    assert len(policies) == 1
    assert policies[0]["confidence"] == 1.0
    assert policies[0]["source"] == SOURCE


@pytest.mark.asyncio
async def test_q2_excludes_superseded_edge_by_default_includes_when_asked(gw):
    """CAP_ENTRY -> CAP_OPEN_1 has a real supersession from the fixture
    (v1 confidence 0.5, superseded by v2 confidence 0.9)."""
    gw_ = await _seeded(gw)

    default_rows = await gw_.run(
        "capability.explain_path", pairs=[{"from": CAP_ENTRY, "to": CAP_OPEN_1}], include_superseded=False,
    )
    assert len(default_rows) == 1
    assert default_rows[0]["edge_confidence"] == 0.9

    included_rows = await gw_.run(
        "capability.explain_path", pairs=[{"from": CAP_ENTRY, "to": CAP_OPEN_1}], include_superseded=True,
    )
    confidences = {r["edge_confidence"] for r in included_rows}
    assert confidences == {0.5, 0.9}


# ---------------------------------------------------------------------------
# Q3 — capability.impact_of
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q3_impact_of_dedups_diamond_dependency(gw):
    gw_ = await _seeded(gw)
    rows = await gw_.run("capability.impact_of", entity_id=CAP_DIAMOND_ROOT, include_superseded=False)
    by_id = _by_entity_id(rows)

    assert set(by_id) == {CAP_DIAMOND_MID_A, CAP_DIAMOND_MID_B, CAP_DIAMOND_TOP}
    assert len(rows) == 3  # the dedup proof — not 4 (naive non-deduped join would double-count TOP)
    assert by_id[CAP_DIAMOND_MID_A]["hops"] == 1
    assert by_id[CAP_DIAMOND_MID_B]["hops"] == 1
    assert by_id[CAP_DIAMOND_TOP]["hops"] == 2


@pytest.mark.asyncio
async def test_q3_excludes_superseded_edge_by_default(gw):
    gw_ = await _seeded(gw)
    await gw_.run(
        "capability.supersede_edge_requires",
        subject_id=CAP_DIAMOND_MID_A, object_id=CAP_DIAMOND_ROOT,
        superseded_by="retracted", superseded_at=_NOW.isoformat(), reason="source_removed",
    )

    rows_default = await gw_.run("capability.impact_of", entity_id=CAP_DIAMOND_ROOT, include_superseded=False)
    by_id_default = _by_entity_id(rows_default)
    assert CAP_DIAMOND_MID_A not in by_id_default
    # CAP_DIAMOND_TOP is still impacted via MID_B's still-live edge
    assert CAP_DIAMOND_TOP in by_id_default

    rows_included = await gw_.run("capability.impact_of", entity_id=CAP_DIAMOND_ROOT, include_superseded=True)
    assert CAP_DIAMOND_MID_A in _by_entity_id(rows_included)


# ---------------------------------------------------------------------------
# Q4 — capability.lineage_of
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q4_lineage_of_collects_produced_chain_and_approvals(gw):
    gw_ = await _seeded(gw)
    rows = await gw_.run("capability.lineage_of", artifact_id=ARTIFACT_QUOTE_REPORT, include_superseded=False)
    by_id = _by_entity_id(rows)

    assert set(by_id) == {ARTIFACT_INTERMEDIATE, RUN_BUILD_482}
    assert by_id[ARTIFACT_INTERMEDIATE]["hops"] == 1
    assert by_id[RUN_BUILD_482]["hops"] == 2
    assert set(by_id[ARTIFACT_INTERMEDIATE]["approved_by"]) == {APPROVER_SECURITY_TEAM}
    assert set(by_id[RUN_BUILD_482]["approved_by"]) == {APPROVER_RELEASE_MGR}


@pytest.mark.asyncio
async def test_q4_excludes_superseded_edge_by_default(gw):
    gw_ = await _seeded(gw)
    await gw_.run(
        "capability.supersede_edge_produced",
        subject_id=RUN_BUILD_482, object_id=ARTIFACT_INTERMEDIATE,
        superseded_by="retracted", superseded_at=_NOW.isoformat(), reason="source_removed",
    )

    rows_default = await gw_.run("capability.lineage_of", artifact_id=ARTIFACT_QUOTE_REPORT, include_superseded=False)
    assert RUN_BUILD_482 not in _by_entity_id(rows_default)
    assert ARTIFACT_INTERMEDIATE in _by_entity_id(rows_default)

    rows_included = await gw_.run("capability.lineage_of", artifact_id=ARTIFACT_QUOTE_REPORT, include_superseded=True)
    assert RUN_BUILD_482 in _by_entity_id(rows_included)


# ---------------------------------------------------------------------------
# Q5 — capability.reuse_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q5_finds_near_duplicate_by_embedding_not_string_match(gw):
    gw_ = await _seeded(gw)

    # Labels share no meaningful substring — a string-similarity heuristic
    # (token overlap, edit distance, substring match) would not pair these
    # two; only their (test-controlled) near-identical embeddings do.
    assert not (set("fast quote verification pass".split()) & set("velocity checking service for quotes".split()) - {"quote", "quotes"})

    rows = await gw_.run(
        "capability.reuse_candidates", entity_id=CAP_DUP_1, query_embedding=_V_DUP, floor=0.70, include_superseded=False,
    )
    by_id = _by_entity_id(rows)
    assert set(by_id) == {CAP_DUP_2}
    assert by_id[CAP_DUP_2]["similarity"] >= 0.70
    assert CAP_DUP_1 not in by_id  # self-excluded


@pytest.mark.asyncio
async def test_q5_respects_similarity_floor(gw):
    """A capability well below the 0.70 floor must not appear, even though
    it's the same entity_type."""
    gw_ = await _seeded(gw)
    rows = await gw_.run(
        "capability.reuse_candidates", entity_id=CAP_DUP_1, query_embedding=_V_DUP, floor=0.70, include_superseded=False,
    )
    # every capability other than CAP_DUP_1/CAP_DUP_2 got an independent
    # random vector — vanishingly unlikely to clear 0.70 against _V_DUP.
    assert CAP_ENTRY not in _by_entity_id(rows)
    assert CAP_OPEN_1 not in _by_entity_id(rows)
    assert CAP_DIAMOND_ROOT not in _by_entity_id(rows)


@pytest.mark.asyncio
async def test_q5_verifies_requires_satisfiable(gw):
    gw_ = await _seeded(gw)

    # retire the MCP tool CAP_REUSE_UNSATISFIABLE depends on
    await gw_.run(
        "capability.supersede_fact_entity",
        entity_id=MCP_UNSATISFIABLE_DEP,
        superseded_by="decommissioned", superseded_at=_NOW.isoformat(), reason="source_removed",
    )

    rows = await gw_.run(
        "capability.reuse_candidates", entity_id="__none__", query_embedding=_V_SAT, floor=0.70, include_superseded=False,
    )
    by_id = _by_entity_id(rows)
    assert set(by_id) == {CAP_REUSE_SATISFIABLE, CAP_REUSE_UNSATISFIABLE}
    assert by_id[CAP_REUSE_SATISFIABLE]["requires_satisfiable"] is True
    assert by_id[CAP_REUSE_UNSATISFIABLE]["requires_satisfiable"] is False


@pytest.mark.asyncio
async def test_q5_excludes_superseded_entity_by_default(gw):
    gw_ = await _seeded(gw)
    await gw_.run(
        "capability.supersede_fact_entity",
        entity_id=CAP_DUP_2,
        superseded_by="replaced-in-catalog", superseded_at=_NOW.isoformat(), reason="replaced",
    )

    rows_default = await gw_.run(
        "capability.reuse_candidates", entity_id=CAP_DUP_1, query_embedding=_V_DUP, floor=0.70, include_superseded=False,
    )
    assert CAP_DUP_2 not in _by_entity_id(rows_default)

    rows_included = await gw_.run(
        "capability.reuse_candidates", entity_id=CAP_DUP_1, query_embedding=_V_DUP, floor=0.70, include_superseded=True,
    )
    assert CAP_DUP_2 in _by_entity_id(rows_included)


# ---------------------------------------------------------------------------
# Fixture seed sanity (also exercises ingest's rejection path end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_seed_rejects_the_deliberately_unknown_predicate(gw):
    gw_ = await _seeded(gw)
    # _seeded() already ran seed_fixture_graph once; re-run (idempotent)
    # and inspect its own return value for the rejection record.
    result = await seed_fixture_graph(gw_, {"embeddings": {"model": EMBEDDING_MODEL}})
    assert len(result["facts_v1"]["rejected"]) == 1
    assert result["facts_v1"]["rejected"][0]["predicate"] == "ENDORSES"
