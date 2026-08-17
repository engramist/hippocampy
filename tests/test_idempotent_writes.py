"""
Tests for B320 — Idempotent Writes: Content-Addressed Deduplication for
Retried Captures.

Two layers:

  1. Pure-function tests for `provenance.content_hash()` /
     `resolve_dedupe_key()` — no DB involved, fast, cover the
     canonicalization contract directly (whitespace/NFC folding, case
     sensitivity, source/workspace sensitivity, the hardcoded-digest
     regression check).
  2. Integration tests against a real (embedded, file-backed) Kùzu database
     via KuzuClient — the same pattern as tests/test_provenance.py and
     tests/test_task_dependency.py — exercising the actual write paths this
     card modifies: `lessons.upsert_lesson`, `lessons._create_plan_graph`,
     and `lessons._store_plan_outcome_lesson`. Embeddings are monkeypatched
     to a fixed vector so nothing here depends on network access to a
     sentence-transformers / Ollama endpoint.

A single module-scoped database is shared across the integration tests
(schema init is not free); each test namespaces its content by a unique
`source`/text so unrelated tests never collide on the same content_hash.
"""

from __future__ import annotations

import uuid

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.provenance import (
    CONTENT_HASH_VERSION,
    content_hash,
    mark_superseded,
    resolve_dedupe_key,
)
from campy.brain.hippocampus.schema import CONTENT_HASH_TABLES, init_schema
from campy.brain.thalamus.tools.lessons import (
    _create_plan_graph,
    _store_plan_outcome_lesson,
    upsert_lesson,
)

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384


# ---------------------------------------------------------------------------
# Pure-function tests: provenance.content_hash() / resolve_dedupe_key()
# ---------------------------------------------------------------------------


def test_content_hash_hardcoded_digest():
    """Frozen-digest regression test (card acceptance criterion): if
    canonicalization ever changes accidentally, this fails loudly instead
    of silently re-partitioning every future dedup decision."""
    digest = content_hash(
        table="Lesson",
        text="The quick brown fox",
        source="agent:claude-code",
        workspace_id="local",
    )
    assert digest == "726187682ce5753d71ede3e0c968e99ff4cefd6fdf4a96e43710caaabbab6bba"
    assert len(digest) == 64  # sha256 hex digest length


def test_content_hash_stable_across_repeated_calls():
    """Pure function: no clock, no randomness, no I/O — same inputs always
    produce the same digest, including across separate calls (a process
    restart can't be simulated in-process, but purity is exactly what
    makes that guarantee hold)."""
    kwargs = dict(table="Concept", text="Water boils at 100C", source="user:direct")
    assert content_hash(**kwargs) == content_hash(**kwargs)


def test_content_hash_whitespace_and_nfc_normalize_to_same_hash():
    base = content_hash(table="Lesson", text="hello world", source="s")
    # Leading/trailing whitespace + collapsed internal runs (tabs, newlines,
    # repeated spaces).
    assert content_hash(table="Lesson", text="  hello   world\n\t", source="s") == base
    # NFC: "e" + combining acute accent (NFD) should normalize the same as
    # its precomposed form. Use a plain-ASCII example that differs only in
    # composed-vs-decomposed accent form.
    decomposed = "café"  # "café" spelled with a combining acute accent
    composed = "café"
    h_decomposed = content_hash(table="Lesson", text=decomposed, source="s")
    h_composed = content_hash(table="Lesson", text=composed, source="s")
    assert h_decomposed == h_composed


def test_content_hash_case_sensitive():
    """Card is explicit: do NOT fold case — it can be semantically
    load-bearing, so a case-only difference must NOT dedupe."""
    a = content_hash(table="Lesson", text="Deploy to Production", source="s")
    b = content_hash(table="Lesson", text="deploy to production", source="s")
    assert a != b


def test_content_hash_source_sensitive():
    a = content_hash(table="Lesson", text="same text", source="agent:claude-code")
    b = content_hash(table="Lesson", text="same text", source="agent:codex")
    assert a != b


def test_content_hash_workspace_sensitive():
    a = content_hash(table="Lesson", text="same text", source="s", workspace_id="ws-a")
    b = content_hash(table="Lesson", text="same text", source="s", workspace_id="ws-b")
    assert a != b


def test_content_hash_table_sensitive():
    a = content_hash(table="Lesson", text="same text", source="s")
    b = content_hash(table="Concept", text="same text", source="s")
    assert a != b


def test_content_hash_extra_discriminator_and_key_order_independence():
    a = content_hash(table="Lesson", text="t", source="s", extra={"a": 1, "b": 2})
    b = content_hash(table="Lesson", text="t", source="s", extra={"b": 2, "a": 1})
    c = content_hash(table="Lesson", text="t", source="s", extra={"a": 1, "b": 3})
    assert a == b  # key order in `extra` must not affect the hash
    assert a != c  # but the actual discriminator values must


def test_content_hash_version_is_hashed():
    """CONTENT_HASH_VERSION is folded into the hashed payload — bumping it
    must re-partition every hash rather than silently colliding old and
    new. Sanity-check by hashing the same payload the function builds
    internally with a different version tag and confirming it diverges."""
    import hashlib
    import json

    real = content_hash(table="Lesson", text="t", source="s", workspace_id="local")
    other_version_payload = {
        "v": CONTENT_HASH_VERSION + 1,
        "table": "Lesson",
        "text": "t",
        "source": "s",
        "workspace_id": "local",
        "extra": {},
    }
    other = hashlib.sha256(
        json.dumps(other_version_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert real != other


def test_resolve_dedupe_key_falls_back_to_content_hash():
    key = resolve_dedupe_key(table="Lesson", text="t", source="s", workspace_id="local")
    assert key == content_hash(table="Lesson", text="t", source="s", workspace_id="local")


def test_resolve_dedupe_key_idempotency_key_overrides_text():
    """Task 4 acceptance criterion: idempotency_key dedupes two calls whose
    text differs."""
    key1 = resolve_dedupe_key(
        table="Lesson", text="version one", source="s", idempotency_key="retry-42"
    )
    key2 = resolve_dedupe_key(
        table="Lesson", text="a completely different version", source="s",
        idempotency_key="retry-42",
    )
    assert key1 == key2


def test_resolve_dedupe_key_idempotency_key_namespaced_away_from_hashes():
    """A caller-chosen idempotency_key must never collide with a computed
    sha256 digest for unrelated content."""
    key = resolve_dedupe_key(table="Lesson", text="t", source="s", idempotency_key="abc")
    assert key.startswith("idemp:")
    assert key != content_hash(table="Lesson", text="t", source="s")


# ---------------------------------------------------------------------------
# Integration tests: real Kùzu DB + the actual write paths (upsert_lesson,
# _create_plan_graph, _store_plan_outcome_lesson)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _patch_embed_for_module():
    """Same pattern as tests/test_provenance.py's `_patch_embed`, but
    module-scoped (and applied *before* the module-scoped `db` fixture
    below, which calls init_schema()'s real embedding call) — a
    function-scoped `monkeypatch` fixture cannot be depended on by a
    module-scoped fixture in pytest, so this patches/restores the bound
    `emb` attributes directly instead of going through `monkeypatch`.
    Patches each consuming module's already-bound `emb` object rather
    than the dotted string path: with enough other test modules loaded
    first, this codebase's test suite can end up with two distinct module
    objects registered for that same dotted path (a pre-existing quirk,
    unrelated to B320), so a string-path patch can silently miss the one
    a given module actually calls."""
    from campy.brain.hippocampus import schema as _schema_mod
    from campy.brain.thalamus.tools import lessons as _lessons_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    originals = {
        "schema_embed": _schema_mod.emb.embed,
        "schema_embed_batch": _schema_mod.emb.embed_batch,
        "lessons_embed": _lessons_mod.emb.embed,
    }
    _schema_mod.emb.embed = _fake_embed
    _schema_mod.emb.embed_batch = _fake_embed_batch
    _lessons_mod.emb.embed = _fake_embed
    try:
        yield
    finally:
        _schema_mod.emb.embed = originals["schema_embed"]
        _schema_mod.emb.embed_batch = originals["schema_embed_batch"]
        _lessons_mod.emb.embed = originals["lessons_embed"]


@pytest.fixture(scope="module")
def db(tmp_path_factory, _patch_embed_for_module):
    # Explicitly depends on _patch_embed_for_module (even though it's also
    # autouse) to guarantee ordering: init_schema() below makes a real
    # emb.embed() call, which must already be patched.
    path = tmp_path_factory.mktemp("b320_idempotent") / "b320.db"
    client = KuzuClient(str(path))
    init_schema(client, SEED_PATH, EMBEDDING_MODEL)
    return client


def _count_lessons_with_text(db: KuzuClient, text: str) -> int:
    r = db.execute(
        "MATCH (l:Lesson) WHERE l.text_raw = $text RETURN count(*)", {"text": text}
    )
    return int(r.get_next()[0]) if r.has_next() else 0


def _lesson_pathway_strength(db: KuzuClient, lesson_id: str) -> float:
    r = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) RETURN l.pathway_strength", {"id": lesson_id}
    )
    assert r.has_next()
    return float(r.get_next()[0])


def _lesson_content_hash(db: KuzuClient, lesson_id: str) -> str | None:
    r = db.execute(
        "MATCH (l:Lesson {lesson_id: $id}) RETURN l.content_hash", {"id": lesson_id}
    )
    assert r.has_next()
    return r.get_next()[0]


# --- Schema (Task 1) --------------------------------------------------------


def test_content_hash_column_exists_on_tier1_tables(db):
    for table in CONTENT_HASH_TABLES:
        r = db.execute(f"CALL table_info('{table}') RETURN *")
        cols = set()
        while r.has_next():
            cols.add(str(r.get_next()[1]))
        assert "content_hash" in cols, f"{table} is missing content_hash"


def test_content_hash_tables_excludes_arc_tier2_tables():
    """Card scopes the column to Tier 1 only — Arc* Tier 2 tables are
    deliberately excluded (see schema.py's CONTENT_HASH_TABLES comment)."""
    assert not any(t.startswith("Arc") for t in CONTENT_HASH_TABLES)
    assert "ArcMechanic" not in CONTENT_HASH_TABLES


# --- upsert_lesson (Task 3 + 4) ---------------------------------------------


@pytest.mark.asyncio
async def test_upsert_lesson_dedupes_identical_retry(db):
    """AC: capturing identical content twice produces one node, and both
    calls return the same node id; the second call doesn't raise/warn and
    is indistinguishable in return shape."""
    params = {
        "text": "Always pin the Kùzu version in requirements.txt",
        "domain": "b320-retry-1",
        "agent_source": "claude-code",
    }
    r1 = await upsert_lesson(dict(params), db, CONFIG)
    r2 = await upsert_lesson(dict(params), db, CONFIG)

    assert r1["status"] == "upserted"
    assert r2["status"] == "upserted"
    assert set(r1.keys()) == set(r2.keys())
    assert r1["lesson_id"] == r2["lesson_id"]
    assert _count_lessons_with_text(db, params["text"]) == 1


@pytest.mark.asyncio
async def test_upsert_lesson_dedup_hit_does_not_bump_pathway_strength(db):
    params = {
        "text": "pathway strength must not move on a dedup hit",
        "domain": "b320-pathway",
        "agent_source": "claude-code",
    }
    r1 = await upsert_lesson(dict(params), db, CONFIG)
    before = _lesson_pathway_strength(db, r1["lesson_id"])
    assert before == 1.0  # fresh Lesson's initial pathway_strength

    r2 = await upsert_lesson(dict(params), db, CONFIG)
    after = _lesson_pathway_strength(db, r2["lesson_id"])
    assert r2["lesson_id"] == r1["lesson_id"]
    assert after == before  # NOT bumped by +0.1 the way an explicit-id update would be


@pytest.mark.asyncio
async def test_upsert_lesson_case_differs_no_dedupe(db):
    r1 = await upsert_lesson(
        {"text": "Restart the Daemon", "domain": "b320-case", "agent_source": "claude-code"},
        db, CONFIG,
    )
    r2 = await upsert_lesson(
        {"text": "restart the daemon", "domain": "b320-case", "agent_source": "claude-code"},
        db, CONFIG,
    )
    assert r1["lesson_id"] != r2["lesson_id"]


@pytest.mark.asyncio
async def test_upsert_lesson_source_differs_no_dedupe(db):
    text = "same text, different source, b320"
    r1 = await upsert_lesson(
        {"text": text, "domain": "b320-source", "agent_source": "claude-code"}, db, CONFIG
    )
    r2 = await upsert_lesson(
        {"text": text, "domain": "b320-source", "agent_source": "codex"}, db, CONFIG
    )
    assert r1["lesson_id"] != r2["lesson_id"]
    assert _count_lessons_with_text(db, text) == 2


@pytest.mark.asyncio
async def test_upsert_lesson_workspace_differs_no_dedupe(db):
    """B315: workspace identity for the content-hash discriminator comes
    from `principal.workspace_id` — never from a `workspace_id` request
    param (the forbidden-key guard now rejects that at the daemon
    dispatch layer before this handler would ever see it; see
    tests/test_auth_context.py). This test's B320 property — the same
    text in two different workspaces must NOT dedupe together — still
    holds, just exercised through the correct channel: two principals with
    different `workspace_id`, not two request bodies."""
    from campy.brain.auth import Principal

    def _principal(workspace_id: str) -> Principal:
        return Principal(
            subject_id="test-subject", tenant_id="test-tenant",
            workspace_id=workspace_id, scopes=frozenset({"memory.write"}),
            client="claude-code", session_id=None, derived_from="test",
        )

    text = "same text, different workspace, b320"
    r1 = await upsert_lesson(
        {"text": text, "domain": "b320-ws", "agent_source": "claude-code"},
        db, CONFIG, principal=_principal("ws-alpha"),
    )
    r2 = await upsert_lesson(
        {"text": text, "domain": "b320-ws", "agent_source": "claude-code"},
        db, CONFIG, principal=_principal("ws-beta"),
    )
    assert r1["lesson_id"] != r2["lesson_id"]


@pytest.mark.asyncio
async def test_upsert_lesson_whitespace_and_nfc_dedupe(db):
    r1 = await upsert_lesson(
        {"text": "collapse   these\tspaces", "domain": "b320-ws-fold", "agent_source": "claude-code"},
        db, CONFIG,
    )
    r2 = await upsert_lesson(
        {"text": "  collapse these spaces  ", "domain": "b320-ws-fold", "agent_source": "claude-code"},
        db, CONFIG,
    )
    assert r1["lesson_id"] == r2["lesson_id"]


@pytest.mark.asyncio
async def test_upsert_lesson_null_content_hash_never_matches(db):
    """AC: a row with NULL content_hash (pre-B320) never matches anything
    and is never updated. Simulate a pre-B320 row by writing it directly
    (bypassing upsert_lesson, which always sets content_hash), then call
    upsert_lesson with the exact same text/source/domain and confirm it
    creates a *new* node rather than reusing the NULL row."""
    text = "pre-B320 lesson with no content_hash"
    old_id = str(uuid.uuid4())
    db.execute(
        "CREATE (l:Lesson {lesson_id: $id, text_raw: $text, domain: $domain, "
        "lesson_type: 'optimization', confidence: 0.9, confidence_low: false, "
        "pathway_strength: 1.0, archived: false, source: $source, "
        "content_hash: NULL})",
        {"id": old_id, "text": text, "domain": "b320-null", "source": "agent:claude-code"},
    )

    result = await upsert_lesson(
        {"text": text, "domain": "b320-null", "agent_source": "claude-code"}, db, CONFIG
    )

    assert result["lesson_id"] != old_id
    assert _count_lessons_with_text(db, text) == 2
    assert _lesson_content_hash(db, result["lesson_id"]) is not None


@pytest.mark.asyncio
async def test_upsert_lesson_superseded_row_not_matched(db):
    """AC: superseded rows do not block a re-capture — capturing content
    identical to a superseded fact creates a new live node."""
    params = {
        "text": "this fact will be superseded then re-captured",
        "domain": "b320-superseded",
        "agent_source": "claude-code",
    }
    original = await upsert_lesson(dict(params), db, CONFIG)
    original_id = original["lesson_id"]

    # A distinct replacement node to point SUPERSEDES at.
    replacement = await upsert_lesson(
        {"text": "the replacement fact", "domain": "b320-superseded", "agent_source": "claude-code"},
        db, CONFIG,
    )
    await mark_superseded(
        db,
        table="Lesson",
        node_id=original_id,
        superseded_by=replacement["lesson_id"],
        reason="replaced",
    )

    # Re-capturing the *original* content again must NOT resurrect/match
    # the now-superseded row — it must create a fresh live node.
    recaptured = await upsert_lesson(dict(params), db, CONFIG)
    assert recaptured["lesson_id"] != original_id
    assert _count_lessons_with_text(db, params["text"]) == 2


@pytest.mark.asyncio
async def test_upsert_lesson_idempotency_key_dedupes_different_text(db):
    """AC: idempotency_key deduplicates two calls whose text differs."""
    r1 = await upsert_lesson(
        {
            "text": "attempt one wording",
            "domain": "b320-idemp",
            "agent_source": "claude-code",
            "idempotency_key": "capture-xyz-789",
        },
        db, CONFIG,
    )
    r2 = await upsert_lesson(
        {
            "text": "attempt two, worded completely differently",
            "domain": "b320-idemp",
            "agent_source": "claude-code",
            "idempotency_key": "capture-xyz-789",
        },
        db, CONFIG,
    )
    assert r1["lesson_id"] == r2["lesson_id"]
    # Only the first call's text should have been persisted.
    assert _count_lessons_with_text(db, "attempt one wording") == 1
    assert _count_lessons_with_text(db, "attempt two, worded completely differently") == 0


@pytest.mark.asyncio
async def test_upsert_lesson_explicit_lesson_id_bypasses_content_dedup(db):
    """An explicit lesson_id is a stronger identity mechanism than content
    hashing and keeps its pre-B320 update-by-id semantics, including the
    existing pathway_strength += 0.1 reinforcement — content-hash dedup
    must not interfere with (or be confused for) that path."""
    fixed_id = str(uuid.uuid4())
    r1 = await upsert_lesson(
        {
            "text": "explicit id lesson v1", "domain": "b320-explicit",
            "agent_source": "claude-code", "lesson_id": fixed_id,
        }, db, CONFIG,
    )
    assert r1["lesson_id"] == fixed_id
    before = _lesson_pathway_strength(db, fixed_id)

    r2 = await upsert_lesson(
        {
            "text": "explicit id lesson v1", "domain": "b320-explicit",
            "agent_source": "claude-code", "lesson_id": fixed_id,
        }, db, CONFIG,
    )
    assert r2["lesson_id"] == fixed_id
    after = _lesson_pathway_strength(db, fixed_id)
    assert after == pytest.approx(before + 0.1)


# --- _create_plan_graph / _store_plan_outcome_lesson (capture.py's paths) --


def _count_plans_with_goal(db: KuzuClient, goal: str) -> int:
    r = db.execute("MATCH (p:Plan) WHERE p.goal = $g RETURN count(*)", {"g": goal})
    return int(r.get_next()[0]) if r.has_next() else 0


def _plan_pathway_strength(db: KuzuClient, plan_id: str) -> float:
    r = db.execute("MATCH (p:Plan {plan_id: $id}) RETURN p.pathway_strength", {"id": plan_id})
    assert r.has_next()
    return float(r.get_next()[0])


@pytest.mark.asyncio
async def test_create_plan_graph_dedupes_retry_when_capture_source_given(db):
    """This is the shape capture.py's notify_turn calls with (capture_source
    set, evidence_ref=message_id) — a retried passive-plan-detection call
    must return the same Plan id instead of forking a duplicate."""
    kwargs = dict(
        db=db,
        goal="B320 retry goal — fix the flaky test",
        steps=["Reproduce locally", "Bisect the regression", "Patch and verify"],
        session_id="unknown",
        embedding_model=EMBEDDING_MODEL,
        now_iso="2026-08-11T00:00:00+00:00",
        source="passive",
        capture_source="agent:claude-code",
        evidence_ref="msg-b320-1",
    )
    plan_id_1, step_ids_1, _ = await _create_plan_graph(**kwargs)
    plan_id_2, step_ids_2, _ = await _create_plan_graph(**kwargs)

    assert plan_id_1 == plan_id_2
    assert step_ids_1 == step_ids_2
    assert _count_plans_with_goal(db, kwargs["goal"]) == 1
    assert _plan_pathway_strength(db, plan_id_1) == max(0.90, 0.5)  # unbumped default confidence


@pytest.mark.asyncio
async def test_create_plan_graph_without_capture_source_is_unaffected(db):
    """Scope guard: callers that don't identify a capture_source (e.g.
    quests.py's register_plan) get zero behavior change from this card —
    every call inserts, exactly as before B320."""
    kwargs = dict(
        db=db,
        goal="B320 no-capture-source goal",
        steps=["Step one", "Step two", "Step three"],
        session_id="unknown",
        embedding_model=EMBEDDING_MODEL,
        now_iso="2026-08-11T00:00:00+00:00",
        source="active",
    )
    plan_id_1, _, _ = await _create_plan_graph(**kwargs)
    plan_id_2, _, _ = await _create_plan_graph(**kwargs)

    assert plan_id_1 != plan_id_2
    assert _count_plans_with_goal(db, kwargs["goal"]) == 2


@pytest.mark.asyncio
async def test_store_plan_outcome_lesson_dedupes_retry(db):
    kwargs = dict(
        db=db,
        plan_id="",
        outcome="Nailed it, all tests pass after the fix",
        valence=0.85,
        session_id="unknown",
        embedding_model=EMBEDDING_MODEL,
        now_iso="2026-08-11T00:00:00+00:00",
        capture_source="user:direct",
        evidence_ref="msg-b320-2",
    )
    lesson_id_1 = await _store_plan_outcome_lesson(**kwargs)
    lesson_id_2 = await _store_plan_outcome_lesson(**kwargs)

    assert lesson_id_1 is not None
    assert lesson_id_1 == lesson_id_2
    assert _lesson_pathway_strength(db, lesson_id_1) == 0.85  # unbumped default, not reinforced
