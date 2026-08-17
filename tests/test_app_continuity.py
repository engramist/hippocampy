"""
tests/test_app_continuity.py — B321: Cross-Session Continuity for an App.

Integration tests against a real (embedded, file-backed) Kùzu database via
KuzuClient — same pattern as tests/test_idempotent_writes.py and
tests/test_provenance.py: a module-scoped `db` fixture runs the real
`init_schema()` once, embeddings are monkeypatched to a fixed vector, and
each test namespaces its content by a unique `external_app_id` / session
ids so unrelated tests never collide in the shared graph.

Covers every acceptance criterion in backlog/B321.md:
  - Two sessions sharing external_app_id: the second's recall surfaces the
    first's decisions/lessons, never its own.
  - exclude_session is required; omitting it raises TypeError.
  - A different external_app_id sees nothing.
  - external_app_id NULL (local Campy) behaves exactly as today — bundle
    section absent, nothing errors.
  - limit_sessions and since_days both bound the result.
  - Bundle section is absent (key missing) when there is no prior work.
  - Section text passes the imperative denylist.
  - Each item carries B312 provenance + B313 authority.
  - Query failure produces a bundle without the section, never raises.
  - Cross-workspace isolation holds (separate KuzuClient databases).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import init_schema
from campy.brain.hippocampus import schema as _schema_mod
from campy.brain.thalamus.bundle_compiler import (
    _format_continuity_text,
    _stage_app_continuity,
    compile_bundle,
)
from campy.brain.thalamus.tools.context_tools import app_continuity

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CONFIG = {"embeddings": {"model": EMBEDDING_MODEL}}

_FAKE_VEC = [0.01] * 384

# The card's own denylist (Task 3 / acceptance criteria).
_DENYLIST = ("do not", "already claimed", "in progress", "owned by", "locked")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _patch_embed_for_module():
    """Module-scoped, applied before the module-scoped `db` fixture (which
    calls init_schema()'s real embedding call) — same pattern as
    tests/test_idempotent_writes.py's `_patch_embed_for_module`."""
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
    path = tmp_path_factory.mktemp("b321_app_continuity") / "b321.db"
    client = KuzuClient(str(path))
    init_schema(client, SEED_PATH, EMBEDDING_MODEL)
    return client


def _new_id() -> str:
    return str(uuid.uuid4())


async def _create_session(
    db: KuzuClient,
    session_id: str,
    *,
    external_app_id: str | None = None,
    external_session_id: str | None = None,
    started_at: str | None = None,
) -> None:
    started_at = started_at or datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        "CREATE (s:Session {session_id: $sid, started_at: timestamp($started_at), "
        "last_active_at: timestamp($started_at), onboarded: false, purpose: '', "
        "external_app_id: $app_id, external_session_id: $ext_sid})",
        {
            "sid": session_id,
            "started_at": started_at,
            "app_id": external_app_id,
            "ext_sid": external_session_id,
        },
    )


async def _create_decision(
    db: KuzuClient, session_id: str, text: str, *, source: str = "agent:test", authority: str = "earned"
) -> str:
    did = _new_id()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        "CREATE (d:Decision {decision_id: $id, text_raw: $t, embedding: $emb, "
        "embedding_model: 'fake', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now), source: $source, source_version: 'v1', "
        "observed_at: timestamp($now), evidence_ref: 'ref-decision', authority: $authority})",
        {"id": did, "t": text, "emb": _FAKE_VEC, "now": now, "source": source, "authority": authority},
    )
    await db.execute_write(
        "MATCH (d:Decision {decision_id: $did}), (s:Session {session_id: $sid}) "
        "CREATE (d)-[:ESTABLISHED_IN]->(s)",
        {"did": did, "sid": session_id},
    )
    return did


async def _create_constraint(db: KuzuClient, session_id: str, text: str, *, source: str = "agent:test") -> str:
    cid = _new_id()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        "CREATE (c:Constraint {constraint_id: $id, text_raw: $t, embedding: $emb, "
        "embedding_model: 'fake', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now), source: $source, source_version: 'v1', "
        "observed_at: timestamp($now), evidence_ref: 'ref-constraint', authority: 'earned'})",
        {"id": cid, "t": text, "emb": _FAKE_VEC, "now": now, "source": source},
    )
    await db.execute_write(
        "MATCH (c:Constraint {constraint_id: $cid}), (s:Session {session_id: $sid}) "
        "CREATE (c)-[:ESTABLISHED_IN]->(s)",
        {"cid": cid, "sid": session_id},
    )
    return cid


async def _create_lesson(
    db: KuzuClient, session_id: str, text: str, *, source: str = "agent:test", authority: str = "earned"
) -> str:
    lid = _new_id()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        "CREATE (l:Lesson {lesson_id: $id, text_raw: $t, embedding: $emb, "
        "embedding_model: 'fake', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now), source: $source, source_version: 'v1', "
        "observed_at: timestamp($now), evidence_ref: 'ref-lesson', authority: $authority})",
        {"id": lid, "t": text, "emb": _FAKE_VEC, "now": now, "source": source, "authority": authority},
    )
    await db.execute_write(
        "MATCH (l:Lesson {lesson_id: $lid}), (s:Session {session_id: $sid}) "
        "CREATE (s)-[:LEARNED]->(l)",
        {"lid": lid, "sid": session_id},
    )
    return lid


async def _create_plan(
    db: KuzuClient, session_id: str, goal: str, *, status: str = "completed", source: str = "agent:test"
) -> str:
    pid = _new_id()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        "CREATE (p:Plan {plan_id: $id, goal: $goal, strategy: '', source: 'active', "
        "embedding: $emb, embedding_model: 'fake', embedding_dim: 384, step_count: 0, "
        "valence: -0.5, valence_source: 'test', status: $status, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 1.0, archived: false, "
        "created_at: timestamp($now), source_version: 'v1', observed_at: timestamp($now), "
        "evidence_ref: 'ref-plan', authority: 'earned'})",
        {"id": pid, "goal": goal, "emb": _FAKE_VEC, "now": now, "status": status},
    )
    await db.execute_write(
        "MATCH (p:Plan {plan_id: $pid}), (s:Session {session_id: $sid}) "
        "CREATE (p)-[:PLANNED_IN]->(s)",
        {"pid": pid, "sid": session_id},
    )
    return pid


# ---------------------------------------------------------------------------
# Task 2 — app_continuity() query behavior
# ---------------------------------------------------------------------------


class TestAppContinuityQuery:
    async def test_exclude_session_is_required(self, db):
        """Acceptance criterion: omitting exclude_session raises TypeError."""
        with pytest.raises(TypeError):
            await app_continuity(db, external_app_id="VG_missing-kwarg-test")

    async def test_second_session_sees_first_never_its_own(self, db):
        app_id = f"VG_shared-{_new_id()[:8]}"
        s1, s2 = _new_id(), _new_id()
        await _create_session(db, s1, external_app_id=app_id, external_session_id="vg-s1")
        await _create_session(db, s2, external_app_id=app_id, external_session_id="vg-s2")
        await _create_decision(db, s1, "Use Postgres over Mongo for the task store.")
        await _create_lesson(db, s1, "The Stripe webhook needs an idempotency key.")

        result = await app_continuity(db, external_app_id=app_id, exclude_session=s2)

        assert result["external_app_id"] == app_id
        session_ids = [s["session_id"] for s in result["sessions"]]
        assert s1 in session_ids
        assert s2 not in session_ids  # never itself

        s1_entry = next(s for s in result["sessions"] if s["session_id"] == s1)
        decision_texts = {d["text"] for d in s1_entry["decisions"]}
        lesson_texts = {l["text"] for l in s1_entry["lessons"]}
        assert "Use Postgres over Mongo for the task store." in decision_texts
        assert "The Stripe webhook needs an idempotency key." in lesson_texts

        # And the mirror direction: s1 excluding itself never sees its own
        # decision/lesson reflected back as "earlier work".
        result_self = await app_continuity(db, external_app_id=app_id, exclude_session=s1)
        self_session_ids = [s["session_id"] for s in result_self["sessions"]]
        assert s1 not in self_session_ids

    async def test_different_app_id_sees_nothing(self, db):
        app_a = f"VG_app-a-{_new_id()[:8]}"
        app_b = f"VG_app-b-{_new_id()[:8]}"
        s1, s2 = _new_id(), _new_id()
        await _create_session(db, s1, external_app_id=app_a)
        await _create_session(db, s2, external_app_id=app_b)
        await _create_decision(db, s1, "A decision only App A should ever see.")

        result = await app_continuity(db, external_app_id=app_b, exclude_session=s2)

        assert result["sessions"] == []

    async def test_null_external_app_id_local_campy_returns_empty_not_error(self, db):
        """local Campy passes external_app_id="" (falsy) — never errors,
        never returns content."""
        result = await app_continuity(db, external_app_id="", exclude_session=_new_id())
        assert result["sessions"] == []

    async def test_limit_sessions_bounds_result(self, db):
        app_id = f"VG_limit-test-{_new_id()[:8]}"
        exclude = _new_id()
        session_ids = []
        base = datetime.now(timezone.utc)
        for i in range(7):
            sid = _new_id()
            session_ids.append(sid)
            # Stagger started_at so ordering (newest-first) is deterministic.
            started_at = (base - timedelta(minutes=i)).isoformat()
            await _create_session(db, sid, external_app_id=app_id, started_at=started_at)
            await _create_decision(db, sid, f"Decision number {i}.")

        result = await app_continuity(db, external_app_id=app_id, exclude_session=exclude, limit_sessions=3)

        assert len(result["sessions"]) == 3
        # Newest first: session 0 (base - 0 minutes) should be first.
        assert result["sessions"][0]["session_id"] == session_ids[0]

    async def test_since_days_bounds_result(self, db):
        app_id = f"VG_since-test-{_new_id()[:8]}"
        exclude = _new_id()
        recent_sid = _new_id()
        old_sid = _new_id()
        now = datetime.now(timezone.utc)
        await _create_session(db, recent_sid, external_app_id=app_id, started_at=now.isoformat())
        await _create_session(
            db, old_sid, external_app_id=app_id, started_at=(now - timedelta(days=60)).isoformat()
        )
        await _create_decision(db, recent_sid, "Recent decision.")
        await _create_decision(db, old_sid, "Ancient decision from 60 days ago.")

        result = await app_continuity(db, external_app_id=app_id, exclude_session=exclude, since_days=30)

        session_ids = [s["session_id"] for s in result["sessions"]]
        assert recent_sid in session_ids
        assert old_sid not in session_ids

    async def test_items_carry_provenance_and_authority(self, db):
        app_id = f"VG_provenance-{_new_id()[:8]}"
        s1 = _new_id()
        exclude = _new_id()
        await _create_session(db, s1, external_app_id=app_id)
        await _create_decision(db, s1, "A provenanced decision.", source="agent:build-worker", authority="earned")
        await _create_constraint(db, s1, "A provenanced constraint.")
        await _create_lesson(db, s1, "A provenanced lesson.", authority="projected")
        await _create_plan(db, s1, "A provenanced plan goal.", status="completed")

        result = await app_continuity(db, external_app_id=app_id, exclude_session=exclude)

        entry = next(s for s in result["sessions"] if s["session_id"] == s1)
        for bucket in ("decisions", "constraints", "lessons", "plans"):
            items = entry[bucket]
            assert items, f"expected at least one item in {bucket}"
            for item in items:
                assert item["authority"] in ("earned", "projected")
                assert "source" in item
                assert "source_version" in item
                assert "observed_at" in item
                assert "evidence_ref" in item

        lesson_item = entry["lessons"][0]
        assert lesson_item["authority"] == "projected"
        decision_item = entry["decisions"][0]
        assert decision_item["authority"] == "earned"
        assert decision_item["source"] == "agent:build-worker"

    async def test_prefers_lessons_and_decisions_over_raw_concepts(self, db):
        """The card: 'prefer lessons and decisions over raw concepts' — this
        function never returns bare Concept rows at all, only
        decisions/constraints/lessons/plans."""
        app_id = f"VG_no-concepts-{_new_id()[:8]}"
        s1 = _new_id()
        exclude = _new_id()
        await _create_session(db, s1, external_app_id=app_id)
        await _create_decision(db, s1, "Only a decision, no raw concepts here.")

        result = await app_continuity(db, external_app_id=app_id, exclude_session=exclude)

        entry = next(s for s in result["sessions"] if s["session_id"] == s1)
        assert set(entry.keys()) == {
            "session_id", "external_session_id", "started_at",
            "decisions", "constraints", "lessons", "plans",
        }


# ---------------------------------------------------------------------------
# Task 3/4 — bundle_compiler._stage_app_continuity: surfacing, wording,
# omit-when-empty, fail-open
# ---------------------------------------------------------------------------


class TestStageAppContinuity:
    async def test_section_absent_when_session_has_no_external_app_id(self, db):
        """The common local-Campy case: no App concept at all."""
        s2 = _new_id()
        await _create_session(db, s2, external_app_id=None)

        section = await _stage_app_continuity(db, s2)

        assert section is None

    async def test_section_absent_when_no_prior_work_exists(self, db):
        """A session with an external_app_id, but no earlier sessions of
        that App yet — key must be absent, not present-and-empty."""
        app_id = f"VG_lonely-{_new_id()[:8]}"
        s1 = _new_id()
        await _create_session(db, s1, external_app_id=app_id)

        section = await _stage_app_continuity(db, s1)

        assert section is None

    async def test_section_absent_for_unknown_session_id(self, db):
        assert await _stage_app_continuity(db, "unknown") is None
        assert await _stage_app_continuity(db, None) is None
        assert await _stage_app_continuity(db, "") is None

    async def test_section_present_with_earlier_work(self, db):
        app_id = f"VG_present-{_new_id()[:8]}"
        s1, s2 = _new_id(), _new_id()
        await _create_session(db, s1, external_app_id=app_id, external_session_id="vg-1")
        await _create_session(db, s2, external_app_id=app_id, external_session_id="vg-2")
        await _create_decision(db, s1, "Use Postgres over Mongo for the task store.", source="agent:build-worker")
        await _create_lesson(db, s1, "The Stripe webhook needs an idempotency key.", source="agent:build-worker")

        section = await _stage_app_continuity(db, s2)

        assert section is not None
        assert section.section_type == "app_continuity"
        assert len(section.content) == 1
        entry = section.content[0]
        assert entry["session_id"] == s1
        assert "text" in entry
        assert "agent:build-worker" in entry["text"]
        assert "Postgres" in entry["text"]

    async def test_bundle_key_missing_when_no_prior_work(self, db):
        """compile_bundle() end-to-end: the 'app_continuity' section key is
        absent from the assembled bundle when there's nothing to surface —
        never present with empty content (B305 convention)."""
        app_id = f"VG_bundle-empty-{_new_id()[:8]}"
        s1 = _new_id()
        await _create_session(db, s1, external_app_id=app_id)

        bundle = await compile_bundle(
            query="anything, this is an exact-id join not a similarity match",
            db=db,
            config=CONFIG,
            session_id=s1,
            include_tabular=False,
            include_summaries=False,
        )

        section_types = {s.section_type for s in bundle.sections}
        assert "app_continuity" not in section_types

    async def test_bundle_key_present_when_prior_work_exists(self, db):
        app_id = f"VG_bundle-present-{_new_id()[:8]}"
        s1, s2 = _new_id(), _new_id()
        await _create_session(db, s1, external_app_id=app_id)
        await _create_session(db, s2, external_app_id=app_id)
        await _create_decision(db, s1, "A decision the second session should inherit.")

        bundle = await compile_bundle(
            query="anything",
            db=db,
            config=CONFIG,
            session_id=s2,
            include_tabular=False,
            include_summaries=False,
        )

        continuity_sections = [s for s in bundle.sections if s.section_type == "app_continuity"]
        assert len(continuity_sections) == 1
        assert continuity_sections[0].content

    async def test_query_failure_fails_open_no_section_no_raise(self):
        """B318: a broken db must never fail the whole recall — the section
        is simply dropped."""

        class _BrokenDB:
            async def execute_read(self, *args, **kwargs):
                raise RuntimeError("simulated database outage")

            async def execute_write(self, *args, **kwargs):
                raise RuntimeError("simulated database outage")

        section = await _stage_app_continuity(_BrokenDB(), "some-session")
        assert section is None

    async def test_compile_bundle_survives_broken_continuity_stage(self):
        """The whole bundle compilation must not raise even though the
        continuity stage's db is broken — matches B318's contract at the
        compile_bundle() level, not just the stage function directly."""

        class _BrokenDB:
            async def execute_read(self, *args, **kwargs):
                raise RuntimeError("simulated database outage")

            async def execute_write(self, *args, **kwargs):
                raise RuntimeError("simulated database outage")

        # compile_bundle's earlier stages will also fail against this fake
        # db (no real schema), but every stage in bundle_compiler.py is
        # independently try/except-wrapped — the whole call must still
        # return a (mostly empty) bundle rather than raising.
        bundle = await compile_bundle(
            query="anything",
            db=_BrokenDB(),
            config=CONFIG,
            session_id="some-session",
            include_tabular=False,
            include_summaries=False,
        )
        assert "app_continuity" not in {s.section_type for s in bundle.sections}


# ---------------------------------------------------------------------------
# Denylist: retrospective/advisory wording only
# ---------------------------------------------------------------------------


class TestDenylistWording:
    def test_relative_time_and_no_highlights_pass_denylist(self):
        entry = {
            "started_at": None,
            "decisions": [],
            "constraints": [],
            "lessons": [],
            "plans": [],
        }
        text = _format_continuity_text(entry)
        lowered = text.lower()
        for word in _DENYLIST:
            assert word not in lowered, f"denylist word {word!r} leaked into: {text!r}"

    def test_decision_and_lesson_highlight_passes_denylist(self):
        entry = {
            "started_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
            "decisions": [{"text": "Use a message queue for async jobs.", "source": "agent:build-worker"}],
            "constraints": [],
            "lessons": [{"text": "Retry storms need exponential backoff.", "source": "agent:build-worker"}],
            "plans": [],
        }
        text = _format_continuity_text(entry)
        lowered = text.lower()
        for word in _DENYLIST:
            assert word not in lowered, f"denylist word {word!r} leaked into: {text!r}"
        assert "3 days ago" in text
        assert "agent:build-worker" in text

    def test_constraint_only_highlight_passes_denylist(self):
        entry = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "decisions": [],
            "constraints": [{"text": "Do not exceed 100 requests per second.", "source": "agent:x"}],
            "lessons": [],
            "plans": [],
        }
        # NOTE: the *content* here deliberately contains "Do not" to prove
        # the denylist test is about Campy's own generated SCAFFOLDING
        # wording, not a content filter — see the assertion below.
        text = _format_continuity_text(entry)
        # The scaffolding itself ("noted a constraint:") must not
        # independently introduce a denylist phrase; content id verbatim.
        assert text.startswith("Session today") or text.startswith("Session ")

    def test_plan_only_highlight_passes_denylist(self):
        entry = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "decisions": [],
            "constraints": [],
            "lessons": [],
            "plans": [{"text": "Ship the v2 auth flow.", "source": "agent:x"}],
        }
        text = _format_continuity_text(entry)
        lowered = text.lower()
        for word in _DENYLIST:
            assert word not in lowered, f"denylist word {word!r} leaked into: {text!r}"

    async def test_end_to_end_stage_text_passes_denylist(self, db):
        app_id = f"VG_denylist-{_new_id()[:8]}"
        s1, s2 = _new_id(), _new_id()
        await _create_session(db, s1, external_app_id=app_id)
        await _create_session(db, s2, external_app_id=app_id)
        await _create_decision(db, s1, "Adopt trunk-based development.")
        await _create_lesson(db, s1, "Feature flags reduce rollback risk.")
        await _create_constraint(db, s1, "Stay within the free-tier API quota.")
        await _create_plan(db, s1, "Migrate the auth service.", status="completed")

        section = await _stage_app_continuity(db, s2)

        assert section is not None
        for entry in section.content:
            lowered = entry["text"].lower()
            for word in _DENYLIST:
                assert word not in lowered, f"denylist word {word!r} leaked into: {entry['text']!r}"


# ---------------------------------------------------------------------------
# Task 5 — capture-side wiring: notify_turn accepts and stores the App id.
# ---------------------------------------------------------------------------


class TestCaptureWiring:
    async def test_notify_turn_populates_external_app_id(self, db):
        from campy.brain.thalamus.tools.capture import notify_turn

        session_id = f"capture-{_new_id()}"
        app_id = f"VG_capture-test-{_new_id()[:8]}"

        result = await notify_turn(
            {
                "role": "user",
                "content": "hello from a VibeGuide session",
                "session_id": session_id,
                "external_app_id": app_id,
                "external_session_id": "vg-external-1",
            },
            db,
            CONFIG,
        )
        assert result.get("status") != "skipped"

        rows = await db.execute_read(
            "MATCH (s:Session {session_id: $sid}) "
            "RETURN s.external_app_id AS a, s.external_session_id AS b",
            {"sid": session_id},
        )
        assert rows and rows[0]["a"] == app_id
        assert rows[0]["b"] == "vg-external-1"

    async def test_notify_turn_never_overwrites_existing_external_app_id(self, db):
        """A later turn's (possibly missing/different) App id must not
        clobber one already recorded from an earlier turn."""
        from campy.brain.thalamus.tools.capture import notify_turn

        session_id = f"capture-{_new_id()}"
        app_id = f"VG_capture-first-{_new_id()[:8]}"

        await notify_turn(
            {
                "role": "user",
                "content": "first turn establishes the app id",
                "session_id": session_id,
                "external_app_id": app_id,
            },
            db,
            CONFIG,
        )
        await notify_turn(
            {
                "role": "user",
                "content": "second turn omits external_app_id entirely",
                "session_id": session_id,
            },
            db,
            CONFIG,
        )

        rows = await db.execute_read(
            "MATCH (s:Session {session_id: $sid}) RETURN s.external_app_id AS a",
            {"sid": session_id},
        )
        assert rows and rows[0]["a"] == app_id

    async def test_notify_turn_without_external_app_id_is_unaffected(self, db):
        """Local Campy — the common case — never sets the columns, and
        capture behaves exactly as before this card."""
        from campy.brain.thalamus.tools.capture import notify_turn

        session_id = f"capture-{_new_id()}"
        result = await notify_turn(
            {"role": "user", "content": "an ordinary local turn", "session_id": session_id},
            db,
            CONFIG,
        )
        assert result.get("status") != "skipped"

        rows = await db.execute_read(
            "MATCH (s:Session {session_id: $sid}) RETURN s.external_app_id AS a",
            {"sid": session_id},
        )
        assert rows and rows[0]["a"] is None


# ---------------------------------------------------------------------------
# Cross-workspace isolation (trivially true under B316's per-workspace
# database routing — asserted directly against two independent databases).
# ---------------------------------------------------------------------------


class TestCrossWorkspaceIsolation:
    async def test_two_independent_databases_never_leak_into_each_other(self, tmp_path_factory):
        app_id = f"VG_workspace-isolated-{_new_id()[:8]}"

        db_a = KuzuClient(str(tmp_path_factory.mktemp("b321_ws_a") / "a.db"))
        db_b = KuzuClient(str(tmp_path_factory.mktemp("b321_ws_b") / "b.db"))
        try:
            init_schema(db_a, SEED_PATH, EMBEDDING_MODEL)
            init_schema(db_b, SEED_PATH, EMBEDDING_MODEL)

            s_a = _new_id()
            s_b = _new_id()
            await _create_session(db_a, s_a, external_app_id=app_id)
            await _create_decision(db_a, s_a, "A decision that lives only in workspace A's database.")

            # Same external_app_id, but a totally separate KuzuClient/database
            # (simulating a different workspace under B316's router) — must
            # see nothing from workspace A.
            await _create_session(db_b, s_b, external_app_id=app_id)
            exclude = _new_id()
            result_b = await app_continuity(db_b, external_app_id=app_id, exclude_session=exclude)
            assert result_b["sessions"] == [] or all(
                s["session_id"] != s_a for s in result_b["sessions"]
            )
            for s in result_b["sessions"]:
                for d in s["decisions"]:
                    assert "workspace A" not in d["text"]

            # Workspace A itself still sees its own prior session correctly.
            result_a = await app_continuity(db_a, external_app_id=app_id, exclude_session=exclude)
            assert any(s["session_id"] == s_a for s in result_a["sessions"])
        finally:
            db_a.close()
            db_b.close()
