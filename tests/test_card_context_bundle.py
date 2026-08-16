"""
Tests for B323 Task 5 — compile_card_context, a context bundle keyed on a
card id (MainQuest/SideQuest/ActionItem) or a Workspace.branch_name.

Uses a real (embedded, file-backed) Kùzu database via KuzuClient — the same
pattern as tests/test_b64_integration.py and tests/test_provenance.py — with
embeddings monkeypatched to a fixed vector so tests don't depend on network
access to a sentence-transformers / Ollama endpoint.
"""

from __future__ import annotations

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools import context_tools
from campy.brain.thalamus.tools.context_tools import compile_card_context
from campy.brain.thalamus.tools.task_graph import add_task_dependency_edge

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    from campy.brain.hippocampus import schema as _schema_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    monkeypatch.setattr(_schema_mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _make_quest(db: KuzuClient, quest_id: str, name: str) -> None:
    db.execute(
        "CREATE (:MainQuest {quest_id: $qid, name: $name, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, confidence: 0.5, "
        "confidence_low: false, pathway_strength: 0.5, archived: false})",
        {"qid": quest_id, "name": name, "emb": list(_FAKE_VEC)},
    )


def _make_workspace(db: KuzuClient, workspace_id: str, branch_name: str) -> None:
    db.execute(
        "CREATE (:Workspace {workspace_id: $wid, path: '/repo', branch_name: $branch})",
        {"wid": workspace_id, "branch": branch_name},
    )


def _make_lesson(db: KuzuClient, lesson_id: str, text: str) -> None:
    db.execute(
        "CREATE (:Lesson {lesson_id: $id, text_raw: $text, embedding: $emb, "
        "embedding_model: 'stub', embedding_dim: 384, domain: 'test', "
        "lesson_type: 'optimization', confidence: 0.9, confidence_low: false, "
        "pathway_strength: 0.9, archived: false})",
        {"id": lesson_id, "text": text, "emb": list(_FAKE_VEC)},
    )


def _seed_graph(db: KuzuClient) -> None:
    """B317 (target) is blocked by B310, which produced a Lesson that was
    itself deprecated by a newer Lesson and solved by an AgentWorker. B317
    is anchored to a Workspace on branch 'feature/foo'."""
    _make_quest(db, "q317", "B317")
    _make_quest(db, "q310", "B310")
    _make_workspace(db, "w1", "feature/foo")
    db.execute(
        "MATCH (q:MainQuest {quest_id: 'q317'}), (w:Workspace {workspace_id: 'w1'}) "
        "CREATE (q)-[:ANCHORED_TO]->(w)"
    )
    _make_lesson(db, "l_old", "old lesson: do not do X")
    _make_lesson(db, "l_new", "new lesson: do Y instead")
    db.execute(
        "MATCH (q:MainQuest {quest_id: 'q310'}), (l:Lesson {lesson_id: 'l_old'}) "
        "CREATE (q)-[:PRODUCED_LESSON]->(l)"
    )
    db.execute(
        "MATCH (a:Lesson {lesson_id: 'l_old'}), (b:Lesson {lesson_id: 'l_new'}) "
        "CREATE (a)-[:DEPRECATED_BY]->(b)"
    )
    db.execute(
        "CREATE (:AgentWorker {worker_id: 'agent:claude-code', "
        "first_seen_at: timestamp('2026-01-01T00:00:00+00:00'), "
        "last_seen_at: timestamp('2026-01-01T00:00:00+00:00')})"
    )
    db.execute(
        "MATCH (l:Lesson {lesson_id: 'l_old'}), (w:AgentWorker {worker_id: 'agent:claude-code'}) "
        "CREATE (l)-[:SOLVED_BY {confidence: 0.8, "
        "observed_at: timestamp('2026-01-01T00:00:00+00:00')}]->(w)"
    )


# ---------------------------------------------------------------------------
# Resolution: card id vs. branch name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolves_card_identifier(tmp_path):
    db = KuzuClient(str(tmp_path / "resolve_card.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    result = await compile_card_context({"target_id": "B317"}, db, CONFIG)
    assert "error" not in result
    assert result["interpreted_as"].startswith("MainQuest")
    target_content = result["bundle"]["sections"][0]["content"][0]
    assert target_content["node_id"] == "q317"


@pytest.mark.asyncio
async def test_resolves_branch_name(tmp_path):
    db = KuzuClient(str(tmp_path / "resolve_branch.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    result = await compile_card_context({"target_id": "feature/foo"}, db, CONFIG)
    assert "error" not in result
    assert result["interpreted_as"] == "Workspace.branch_name"
    target_content = result["bundle"]["sections"][0]["content"][0]
    assert target_content["node_id"] == "w1"


@pytest.mark.asyncio
async def test_card_wins_on_ambiguity(tmp_path):
    """When a card name and a branch name collide, the card interpretation
    is used (checked first) — and the response says so."""
    db = KuzuClient(str(tmp_path / "resolve_ambiguous.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _make_quest(db, "qX", "ambiguous-id")
    _make_workspace(db, "wX", "ambiguous-id")

    result = await compile_card_context({"target_id": "ambiguous-id"}, db, CONFIG)
    assert result["interpreted_as"].startswith("MainQuest")


@pytest.mark.asyncio
async def test_unresolvable_target_returns_error_not_raise(tmp_path):
    db = KuzuClient(str(tmp_path / "resolve_none.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    result = await compile_card_context({"target_id": "no-such-thing"}, db, CONFIG)
    assert "error" in result


@pytest.mark.asyncio
async def test_missing_target_id_returns_error(tmp_path):
    db = KuzuClient(str(tmp_path / "resolve_missing.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)

    result = await compile_card_context({}, db, CONFIG)
    assert "error" in result


# ---------------------------------------------------------------------------
# Bounded traversal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_hops_clamped_to_hard_cap(tmp_path):
    db = KuzuClient(str(tmp_path / "clamp_hops.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    result = await compile_card_context({"target_id": "B317", "max_hops": 99}, db, CONFIG)
    assert result["max_hops"] == 5


@pytest.mark.asyncio
async def test_max_hops_defaults_to_three(tmp_path):
    db = KuzuClient(str(tmp_path / "default_hops.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    result = await compile_card_context({"target_id": "B317"}, db, CONFIG)
    assert result["max_hops"] == 3


@pytest.mark.asyncio
async def test_no_unbounded_star_in_dependency_queries(tmp_path, monkeypatch):
    """The registered traversal query never issues a Cypher `*` (unbounded
    or otherwise) — compile_card_context expands one hop at a time in
    Python instead. Assert this by capturing every query text the
    dependency-hop helper issues."""
    db = KuzuClient(str(tmp_path / "no_star.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    issued_queries: list[str] = []
    original_execute = db.execute

    def _spy_execute(query, params=None):
        issued_queries.append(query)
        return original_execute(query, params)

    monkeypatch.setattr(db, "execute", _spy_execute)

    await compile_card_context({"target_id": "B317", "max_hops": 5}, db, CONFIG)

    dependency_queries = [q for q in issued_queries if "TASK_BLOCKS" in q or "TASK_ENABLES" in q or "ANCHORED_TO" in q]
    assert dependency_queries, "expected at least one dependency traversal query to be issued"
    for q in dependency_queries:
        assert "*" not in q, f"unbounded/variable-length traversal found: {q}"


# ---------------------------------------------------------------------------
# PRODUCED_LESSON / DEPRECATED_BY / SOLVED_BY content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bundle_includes_produced_lesson_and_deprecated_by(tmp_path):
    db = KuzuClient(str(tmp_path / "lessons_deprecated.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)
    await add_task_dependency_edge(
        db, rel_type="TASK_BLOCKS", table="MainQuest", from_id="q310", to_id="q317",
        declared_by="tester",
    )

    result = await compile_card_context({"target_id": "B317", "max_hops": 3}, db, CONFIG)
    sections_by_type = {s["type"]: s for s in result["bundle"]["sections"]}

    assert "lessons" in sections_by_type
    lesson_ids = {item["lesson_id"] for item in sections_by_type["lessons"]["content"]}
    assert "l_old" in lesson_ids

    assert "superseded" in sections_by_type
    superseded_ids = {item["related_node_id"] for item in sections_by_type["superseded"]["content"]}
    assert "l_new" in superseded_ids

    assert "attribution" in sections_by_type
    workers = {item["worker_id"] for item in sections_by_type["attribution"]["content"]}
    assert "agent:claude-code" in workers


@pytest.mark.asyncio
async def test_bundle_dependencies_section_has_task_blocks_edge(tmp_path):
    db = KuzuClient(str(tmp_path / "dep_edges.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)
    await add_task_dependency_edge(
        db, rel_type="TASK_BLOCKS", table="MainQuest", from_id="q310", to_id="q317",
        declared_by="tester",
    )

    result = await compile_card_context({"target_id": "B317", "max_hops": 3}, db, CONFIG)
    sections_by_type = {s["type"]: s for s in result["bundle"]["sections"]}
    assert "dependencies" in sections_by_type
    rel_types = {item["rel_type"] for item in sections_by_type["dependencies"]["content"]}
    assert "TASK_BLOCKS" in rel_types
    assert "ANCHORED_TO" in rel_types


# ---------------------------------------------------------------------------
# Structured data + Markdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_structured_bundle_and_markdown(tmp_path):
    db = KuzuClient(str(tmp_path / "structured.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    result = await compile_card_context({"target_id": "B317"}, db, CONFIG)

    assert isinstance(result["bundle"], dict)
    assert isinstance(result["bundle"]["sections"], list)
    assert isinstance(result["markdown"], str)
    assert "B317" in result["markdown"]
    assert result["bundle"]["sections"][0]["type"] == "target"


# ---------------------------------------------------------------------------
# Fail-open (B318)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dependency_traversal_failure_is_fail_open(tmp_path, monkeypatch):
    db = KuzuClient(str(tmp_path / "fail_open.db"))
    init_schema(db, SEED_PATH, EMBEDDING_MODEL)
    _seed_graph(db)

    def _boom(db_arg, frontier):
        raise RuntimeError("simulated traversal failure")

    monkeypatch.setattr(context_tools, "_card_context_dependency_hop", _boom)

    result = await compile_card_context({"target_id": "B317"}, db, CONFIG)

    assert "error" not in result
    assert result["dependency_traversal_failed"] is True
    section_types = {s["type"] for s in result["bundle"]["sections"]}
    assert section_types == {"target"}
    assert "B317" in result["markdown"]
