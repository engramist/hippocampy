"""
campy/brain/hippocampus/graph/queries/continuity.py — B321 named-query slice.

Cross-session continuity for an App: what earlier sessions sharing the same
platform-supplied `Session.external_app_id` decided, tried, and learned,
surfaced to a new session on that same App via `context_tools.app_continuity()`
and `bundle_compiler._stage_app_continuity()`.

This is an **exact-id join**, not a similarity match — no embedding, no
distance floor (the `0.30`/`0.70` conventions used throughout
`bundle_compiler.py`'s other stages do not apply here; see the B321 card).
It is also purely advisory and pull-only (B318 fail-open contract; both
call sites above swallow any error from these queries and simply omit the
section) — nothing here locks, claims, or warns about collisions. Campy
provides no mutual exclusion between sessions; see docs/ARCHITECTURE.md's
B321 section.

Six queries:

  - `app_continuity.prior_sessions` — prior sessions of an App, newest
    first, bounded by `limit_sessions` and a `since_iso` floor.
  - `app_continuity.decisions_for_sessions` / `.constraints_for_sessions` /
    `.lessons_for_sessions` / `.plans_for_sessions` — the B312-provenanced,
    B313-authority-carrying facts attributable to a batch of prior
    sessions, joined via the pre-existing `ESTABLISHED_IN` (Decision/
    Constraint -> Session), `LEARNED` (Session -> Lesson), and
    `PLANNED_IN` (Plan -> Session) edges — no new relationship tables.
    Each takes a single `$session_ids` list and `UNWIND`s it, rather than
    one round trip per session.
  - `app_continuity.session_external_app_id` — the one-row lookup
    `bundle_compiler._stage_app_continuity()` uses to decide whether a
    session's App has any continuity to surface at all before calling
    `app_continuity()` a second time.
  - `app_continuity.set_session_external_ids` — the capture-side write
    (`capture.py::notify_turn`) that best-effort populates the two nullable
    `Session` columns from ordinary tool-call params, `COALESCE`d against
    whatever is already stored so a later turn can fill in an id an
    earlier turn omitted, but never overwrites one already set.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

CONTINUITY_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="app_continuity.prior_sessions",
        cypher="""
            MATCH (s:Session)
            WHERE s.external_app_id = $external_app_id
                  AND s.session_id <> $exclude_session
                  AND s.started_at >= $since_iso
            RETURN s.session_id AS session_id, s.started_at AS started_at,
                   s.external_session_id AS external_session_id
            ORDER BY s.started_at DESC
            LIMIT $limit_sessions
            """,
        params=("external_app_id", "exclude_session", "since_iso", "limit_sessions"),
        mutating=False,
        description="B321: prior sessions of an App (excluding the calling session), "
                    "newest first, bounded by limit_sessions and a since_iso floor.",
    ),
    NamedQuery(
        name="app_continuity.decisions_for_sessions",
        cypher="""
            UNWIND $session_ids AS sid
            MATCH (d:Decision)-[:ESTABLISHED_IN]->(s:Session {session_id: sid})
            WHERE d.superseded_by IS NULL AND (d.archived = false OR d.archived IS NULL)
            RETURN sid AS session_id, d.decision_id AS id, d.text_raw AS text,
                   d.source AS source, d.source_version AS source_version,
                   d.observed_at AS observed_at, d.evidence_ref AS evidence_ref,
                   d.authority AS authority, d.created_at AS created_at
            ORDER BY d.created_at DESC
            """,
        params=("session_ids",),
        mutating=False,
        description="B321: live (non-superseded, non-archived) Decisions established in a "
                    "batch of prior sessions, with B312 provenance + B313 authority.",
    ),
    NamedQuery(
        name="app_continuity.constraints_for_sessions",
        cypher="""
            UNWIND $session_ids AS sid
            MATCH (c:Constraint)-[:ESTABLISHED_IN]->(s:Session {session_id: sid})
            WHERE c.superseded_by IS NULL AND (c.archived = false OR c.archived IS NULL)
            RETURN sid AS session_id, c.constraint_id AS id, c.text_raw AS text,
                   c.source AS source, c.source_version AS source_version,
                   c.observed_at AS observed_at, c.evidence_ref AS evidence_ref,
                   c.authority AS authority, c.created_at AS created_at
            ORDER BY c.created_at DESC
            """,
        params=("session_ids",),
        mutating=False,
        description="B321: live Constraints established in a batch of prior sessions, "
                    "with B312 provenance + B313 authority.",
    ),
    NamedQuery(
        name="app_continuity.lessons_for_sessions",
        cypher="""
            UNWIND $session_ids AS sid
            MATCH (s:Session {session_id: sid})-[:LEARNED]->(l:Lesson)
            WHERE l.superseded_by IS NULL AND (l.archived = false OR l.archived IS NULL)
            RETURN sid AS session_id, l.lesson_id AS id, l.text_raw AS text,
                   l.source AS source, l.source_version AS source_version,
                   l.observed_at AS observed_at, l.evidence_ref AS evidence_ref,
                   l.authority AS authority, l.created_at AS created_at
            ORDER BY l.created_at DESC
            """,
        params=("session_ids",),
        mutating=False,
        description="B321: live Lessons learned in a batch of prior sessions, "
                    "with B312 provenance + B313 authority.",
    ),
    NamedQuery(
        name="app_continuity.plans_for_sessions",
        cypher="""
            UNWIND $session_ids AS sid
            MATCH (p:Plan)-[:PLANNED_IN]->(s:Session {session_id: sid})
            WHERE p.superseded_by IS NULL AND (p.archived = false OR p.archived IS NULL)
            RETURN sid AS session_id, p.plan_id AS id, p.goal AS text,
                   p.status AS status, p.valence AS valence,
                   p.source AS source, p.source_version AS source_version,
                   p.observed_at AS observed_at, p.evidence_ref AS evidence_ref,
                   p.authority AS authority, p.created_at AS created_at
            ORDER BY p.created_at DESC
            """,
        params=("session_ids",),
        mutating=False,
        description="B321: live Plan outcomes (goal/status/valence) planned in a batch "
                    "of prior sessions, with B312 provenance + B313 authority.",
    ),
    NamedQuery(
        name="app_continuity.session_external_app_id",
        cypher="""
            MATCH (s:Session {session_id: $session_id})
            RETURN s.external_app_id AS external_app_id
            """,
        params=("session_id",),
        mutating=False,
        description="B321: one-row lookup so _stage_app_continuity can skip straight to "
                    "'no section' for the common local-Campy case (external_app_id NULL) "
                    "without running the full continuity query.",
    ),
    NamedQuery(
        name="app_continuity.set_session_external_ids",
        cypher="""
            MATCH (s:Session {session_id: $session_id})
            SET s.external_app_id = COALESCE(s.external_app_id, $external_app_id),
                s.external_session_id = COALESCE(s.external_session_id, $external_session_id)
            """,
        params=("session_id", "external_app_id", "external_session_id"),
        mutating=True,
        description="B321: best-effort populate Session.external_app_id/external_session_id "
                    "from capture.py's notify_turn params, without overwriting a value "
                    "already stored from an earlier turn.",
    ),
)
