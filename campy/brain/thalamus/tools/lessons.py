"""Planning primitives and lesson/procedure memory handlers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.provenance import (
    find_live_by_dedupe_key,
    provenance_fields,
    resolve_dedupe_key,
)
from campy.brain.hippocampus.schema import upsert_agent_worker_and_link

from ._shared import (
    _CONCEPT_INDEX,
    _LESSON_INDEX,
    _PLAN_INDEX,
    _logger,
    _safe_result_dict,
)

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.auth import Principal


def _gateway(db) -> GraphGateway:
    """B314: wrap `db` in a `GraphGateway` bound to this module's
    named-query registry, or pass a `GraphGateway` through unchanged.

    Keeps every public function in this file on its existing
    `db: KuzuClient` signature (changing that is B315's job, not this
    one's — ~14 tool modules and the daemon dispatch depend on it) while
    routing every query through the B314 chokepoint internally. Cheap to
    call repeatedly: the gateway is a thin wrapper, not a connection.
    """
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)



async def _create_plan_graph(
    *,
    db,
    goal: str,
    steps: list[str],
    session_id: str,
    embedding_model: str,
    now_iso: str,
    strategy: str = "",
    source: str = "active",
    confidence: float = 0.90,
    confidence_low: bool = False,
    capture_source: str | None = None,
    evidence_ref: str | None = None,
    idempotency_key: str | None = None,
    workspace_id: str = "local",
) -> tuple[str, list[str], str]:
    """Create Plan + PlanStep chain and basic relationships.

    B312: `capture_source`/`evidence_ref` are the primary-capture-path
    provenance identifiers (e.g. "agent:claude-code" / a message_id). When
    omitted (the default — every caller other than capture.py's
    notify_turn), all four provenance columns stay NULL, matching prior
    behavior. Note `source` here is Plan's pre-existing "plan origin"
    field ("active"/"passive") — a different, narrower concept than the
    B312 provenance `source` column, which PlanStep gets but Plan does not
    (Plan already had a `source` column before this card; see schema.py).

    B320: dedup-on-write only activates when `capture_source` or
    `idempotency_key` is supplied — i.e. only for the primary capture path
    (capture.py's notify_turn), matching this card's declared scope. Other
    callers (quests.py's register_plan) pass neither, so `dedupe_key` stays
    None below and every call behaves exactly as it did pre-B320 (always
    inserts, content_hash column stays NULL). A dedup hit returns the
    *existing* plan's id/step_ids/quest_id — indistinguishable in shape
    from a fresh insert — instead of creating a duplicate Plan node.
    """
    gw = _gateway(db)

    dedupe_key: str | None = None
    if capture_source or idempotency_key:
        dedupe_key = resolve_dedupe_key(
            table="Plan",
            text=goal,
            source=capture_source or "",
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        # B320: the dedup lookup fails open — any error here (including a
        # test double / caller-supplied `db` that doesn't implement
        # execute_read) falls through to a normal insert rather than
        # raising and blocking the write. Mirrors this file's/capture.py's
        # existing try/except-around-optional-enhancement style throughout
        # notify_turn (warm frontier, proactive push, etc.) — dedup is a
        # best-effort optimization on the primary capture path, never a
        # hard dependency of it.
        try:
            existing_plan_id = await find_live_by_dedupe_key(
                db, table="Plan", pk_column="plan_id", dedupe_key=dedupe_key
            )
        except Exception:
            _logger.exception("B320: dedup lookup failed for Plan; proceeding with insert")
            existing_plan_id = None
        if existing_plan_id:
            existing_step_ids: list[str] = []
            try:
                step_rows = await gw.run("lessons.list_plan_step_ids", pid=existing_plan_id)
                existing_step_ids = [r["step_id"] for r in step_rows]
            except Exception:
                _logger.exception("B320: failed to load steps for deduped plan %s", existing_plan_id)
            existing_quest_id = ""
            try:
                quest_rows = await gw.run("lessons.find_quest_for_plan", pid=existing_plan_id)
                if quest_rows:
                    existing_quest_id = quest_rows[0].get("quest_id") or ""
            except Exception:
                _logger.exception("B320: failed to load quest for deduped plan %s", existing_plan_id)
            return existing_plan_id, existing_step_ids, existing_quest_id

    plan_id = str(uuid.uuid4())
    step_ids = [str(uuid.uuid4()) for _ in steps]
    goal_vec = emb.embed(goal, model_name=embedding_model)

    prov = (
        provenance_fields(source=capture_source, evidence_ref=evidence_ref)
        if capture_source
        else {"source": None, "source_version": None, "observed_at": None, "evidence_ref": None}
    )

    # Resolve quest_id from session if not provided
    quest_id = ""
    if session_id and session_id != "unknown":
        try:
            quest_rows = await gw.run("lessons.find_quest_for_session", sid=session_id)
            if quest_rows:
                quest_id = quest_rows[0].get("quest_id") or ""
        except Exception:
            pass

    # Pre-calculate step data and ACTS_ON links
    step_params = []
    for idx, (step_id, step_text) in enumerate(zip(step_ids, steps), start=1):
        step_vec = emb.embed(step_text, model_name=embedding_model)
        acts_on = []
        try:
            # B75: pre-calculate ACTS_ON via vector search
            rows = db.vector_search("Concept", _CONCEPT_INDEX, step_vec, 5)
            for row in rows:
                # B279: ACTS_ON links require true cosine similarity >= 0.75.
                if row["score"] >= 0.75:
                    node = _safe_result_dict(row.get("node", {}))
                    cid = node.get("concept_id")
                    if cid and not node.get("archived", False):
                        acts_on.append(cid)
        except Exception:
            pass

        step_params.append({
            "step_id": step_id,
            "step_number": idx,
            "description": step_text,
            "embedding": step_vec,
            "acts_on": acts_on
        })

    try:
        # B75: Create Plan node first
        await gw.run(
            "lessons.create_plan",
            plan_id=plan_id,
            goal=goal,
            strategy=strategy,
            source=source,
            embedding=goal_vec,
            embedding_model=embedding_model,
            embedding_dim=len(goal_vec),
            step_count=len(steps),
            confidence=confidence,
            confidence_low=confidence_low,
            pathway_strength=max(confidence, 0.5),
            created_at=now_iso,
            prov_source_version=prov["source_version"],
            prov_observed_at=prov["observed_at"],
            prov_evidence_ref=prov["evidence_ref"],
            # B320: NULL unless capture_source/idempotency_key made this
            # call dedup-eligible (see the docstring above) — matches
            # every other pre-B320 Plan row's NULL content_hash.
            content_hash=dedupe_key,
        )

        # B68: Create each PlanStep individually (separate CREATE for each step)
        # This allows passive plan detection to work with test assertions
        for s in step_params:
            await gw.run(
                "lessons.create_plan_step",
                step_id=s["step_id"],
                step_number=s["step_number"],
                description=s["description"],
                embedding=s["embedding"],
                embedding_model=embedding_model,
                embedding_dim=len(s["embedding"]),
                created_at=now_iso,
                prov_source=prov["source"],
                prov_source_version=prov["source_version"],
                prov_observed_at=prov["observed_at"],
                prov_evidence_ref=prov["evidence_ref"],
            )
            # Link to Plan
            await gw.run("lessons.link_step_to_plan", plan_id=plan_id, step_id=s["step_id"])
            # Link ACTS_ON relationships
            if s["acts_on"]:
                await gw.run(
                    "lessons.link_step_acts_on_concepts", sid=s["step_id"], cids=s["acts_on"]
                )

        # Kuzu parser compatibility: perform optional relationships as
        # separate conditional writes instead of Cypher FOREACH blocks.
        if session_id and session_id != "unknown":
            await gw.run("lessons.link_plan_to_session", plan_id=plan_id, session_id=session_id)

        if quest_id:
            # Try to link to either MainQuest or SideQuest
            try:
                await gw.run("lessons.link_plan_to_main_quest", plan_id=plan_id, quest_id=quest_id)
            except Exception:
                # Quest might be a SideQuest, try that
                try:
                    await gw.run(
                        "lessons.link_plan_to_side_quest", plan_id=plan_id, quest_id=quest_id
                    )
                except Exception:
                    # Neither quest type found, skip the relationship
                    pass

        # B75 Call 2: chain steps with NEXT_STEP
        if len(step_ids) > 1:
            next_pairs = [{"a": a, "b": b} for a, b in zip(step_ids, step_ids[1:])]
            await gw.run("lessons.chain_plan_steps", pairs=next_pairs)

    except Exception as e:
        _logger.exception("B75: Transactional plan write failed, cleaning up %s", plan_id)
        # Compensating delete to ensure atomicity.
        # Delete steps by known ids first, then delete plan node.
        try:
            if step_ids:
                await gw.run("lessons.delete_plan_steps", ids=step_ids)
            await gw.run("lessons.delete_plan", pid=plan_id)
        except Exception:
            pass
        raise e

    return plan_id, step_ids, quest_id


async def _plan_feedback_from_similarity(db, goal_vec: list[float], exclude_plan_id: str) -> tuple[list[dict], list[dict]]:
    """Amygdala reflex: similar historical plans -> warnings/suggestions.

    B314: made async (was sync) so its PlanStep read can go through
    `GraphGateway.run()` like every other query in this file — its sole
    caller, quests.py's `register_plan`, already awaits everything else in
    its own async function body, so this only required adding one `await`
    at that call site.
    """
    gw = _gateway(db)
    warnings: list[dict] = []
    suggestions: list[dict] = []

    try:
        candidates = db.vector_search("Plan", _PLAN_INDEX, goal_vec, 12)
    except Exception:
        return warnings, suggestions

    for item in candidates:
        node = _safe_result_dict(item.get("node", {}))
        pid = node.get("plan_id", "")
        if not pid or pid == exclude_plan_id:
            continue

        similarity = float(item.get("score", 0.0) or 0.0)
        # B279: warnings/suggestions only consider true cosine similarity > 0.75.
        if similarity <= 0.75:
            continue

        valence = node.get("valence")
        if valence is None:
            continue
        valence = float(valence)

        step_rows: list[dict] = []
        try:
            raw_rows = await gw.run("lessons.list_plan_steps_for_feedback", pid=pid)
            step_rows = [
                {
                    "step_number": int(r["step_number"]),
                    "description": r["description"] or "",
                    "valence": r["valence"],
                    "status": r["status"] or "",
                }
                for r in raw_rows
            ]
        except Exception:
            pass

        payload = {
            "plan_id": pid,
            "goal": node.get("goal", ""),
            "valence": valence,
            "similarity": round(similarity, 4),
            "steps": step_rows,
            "score": abs(valence * similarity),
        }
        if valence < -0.5:
            warnings.append(payload)
        elif valence > 0.5:
            suggestions.append(payload)

    warnings.sort(key=lambda x: x["score"], reverse=True)
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    for row in warnings:
        row.pop("score", None)
    for row in suggestions:
        row.pop("score", None)
    return warnings[:5], suggestions[:5]


async def _store_plan_outcome_lesson(db, *, plan_id: str, outcome: str, valence: float, session_id: str,
                                     embedding_model: str, now_iso: str,
                                     trigger_signals: list[str] | None = None,
                                     capture_source: str | None = None,
                                     evidence_ref: str | None = None,
                                     idempotency_key: str | None = None,
                                     workspace_id: str = "local") -> str | None:
    """Create a Lesson and connect it to the Plan when |valence| is strong.

    B312: `capture_source`/`evidence_ref` populate provenance when this is
    called from the primary capture path (capture.py's notify_turn). Other
    callers (e.g. quests.py's report_outcome) omit them and the Lesson's
    provenance columns stay NULL, matching prior behavior.

    B320: dedup-on-write, same scope rule as `_create_plan_graph` — only
    activates when `capture_source` or `idempotency_key` is supplied, so
    callers that pass neither (quests.py) are unaffected: `dedupe_key`
    stays None, content_hash stays NULL, every call inserts, exactly as
    before this card. On a dedup hit the freshly-computed embedding is
    skipped entirely (no CREATE happens) and the function falls through to
    reuse the *existing* lesson's id for the PRODUCED_PLAN_LESSON/LEARNED
    edge writes and the SOLVED_BY derivation below — those are MERGE-based
    and therefore idempotent, so re-running them against a retry is safe
    and in fact desirable (a first attempt that created the Lesson but
    died before linking it gets the link on the retry).
    """
    if abs(valence) <= 0.7:
        return None

    gw = _gateway(db)
    lesson_text = f"Plan outcome ({'success' if valence > 0 else 'failure'}): {outcome.strip()}"
    # B301: record which signal(s) drove the polarity so a system-labeled
    # outcome is auditable from the Lesson node itself.
    if trigger_signals:
        lesson_text += f"\n[valence_trigger: {', '.join(trigger_signals)}]"

    dedupe_key: str | None = None
    existing_lesson_id: str | None = None
    if capture_source or idempotency_key:
        dedupe_key = resolve_dedupe_key(
            table="Lesson",
            text=lesson_text,
            source=capture_source or "",
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        # B320: fails open on lookup error — see the matching comment in
        # _create_plan_graph above.
        try:
            existing_lesson_id = await find_live_by_dedupe_key(
                db, table="Lesson", pk_column="lesson_id", dedupe_key=dedupe_key
            )
        except Exception:
            _logger.exception("B320: dedup lookup failed for Lesson; proceeding with insert")
            existing_lesson_id = None

    prov = (
        provenance_fields(source=capture_source, evidence_ref=evidence_ref)
        if capture_source
        else {"source": None, "source_version": None, "observed_at": None, "evidence_ref": None}
    )

    if existing_lesson_id:
        lesson_id = existing_lesson_id
    else:
        lesson_id = str(uuid.uuid4())
        vec = emb.embed(lesson_text, model_name=embedding_model)
        await gw.run(
            "lessons.create_plan_outcome_lesson",
            lesson_id=lesson_id,
            text_raw=lesson_text,
            embedding=vec,
            embedding_model=embedding_model,
            embedding_dim=len(vec),
            created_at=now_iso,
            prov_source=prov["source"],
            prov_source_version=prov["source_version"],
            prov_observed_at=prov["observed_at"],
            prov_evidence_ref=prov["evidence_ref"],
            # B320: NULL unless capture_source/idempotency_key made
            # this call dedup-eligible (see the docstring above).
            content_hash=dedupe_key,
        )

    await gw.run("lessons.link_plan_to_lesson", pid=plan_id, lid=lesson_id)

    if session_id and session_id != "unknown":
        await gw.run("lessons.link_session_learned_lesson", sid=session_id, lid=lesson_id)

    # B323: derive AgentWorker + SOLVED_BY in the same write that set this
    # Lesson's B312 provenance (prov["source"]) — never as a separate pass.
    # No-ops when capture_source is None/"user:direct" (see
    # upsert_agent_worker_and_link's docstring).
    try:
        await upsert_agent_worker_and_link(
            db,
            worker_id=prov["source"],
            node_table="Lesson",
            node_id=lesson_id,
            observed_at=prov["observed_at"],
        )
    except Exception:
        _logger.exception("B323: SOLVED_BY link failed for lesson %s", lesson_id)

    return lesson_id


async def _synthesize_lesson(quest_id: str, db, config: dict) -> None:
    """
    Background coroutine: synthesize a Lesson node from quest artifacts.

    1. Query the top confirmed artifacts linked to this quest
    2. Ask LLM to synthesize the hardest obstacle and key lesson
    3. Store as Lesson node (confidence_low=true) + PRODUCED_LESSON edge
    """
    try:
        from campy.brain.llm.provider import create_llm_client
        from campy.brain.hippocampus.graph import embeddings as emb

        gw = _gateway(db)
        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )

        # Gather up to 10 confirmed artifacts from this quest. Table names
        # aren't parameterizable in Cypher, so this is three separate
        # static named queries (one per table) rather than one templated
        # by `table` — see gateway.py's brace-validation docstring for why
        # an f-string-interpolated table name would fail NamedQuery
        # registration outright.
        artifact_queries = [
            ("Decision", "lessons.list_confirmed_decisions"),
            ("Constraint", "lessons.list_confirmed_constraints"),
            ("Requirement", "lessons.list_confirmed_requirements"),
        ]
        artifact_rows = []
        for table, query_name in artifact_queries:
            try:
                rows = await gw.run(query_name)
                for row in rows:
                    artifact_rows.append(f"[{table}] {row['text_raw']}")
            except Exception:
                pass

        if not artifact_rows:
            _logger.info("_synthesize_lesson: no confirmed artifacts for quest %s", quest_id)
            return

        artifacts_text = "\n".join(artifact_rows[:10])

        # Create LLM client — skip if unavailable
        llm = create_llm_client(config)
        if llm is None:
            _logger.warning("_synthesize_lesson: LLM unavailable for quest %s", quest_id)
            return

        prompt = (
            "Given these artifacts from a completed project quest:\n\n"
            f"{artifacts_text}\n\n"
            "Synthesize in 1-2 sentences:\n"
            "1. The hardest obstacle overcome\n"
            "2. The key lesson learned that would help someone doing similar work\n\n"
            'Return JSON only: {"lesson": "...", "obstacle": "..."}'
        )

        import json as _json
        response_text = await asyncio.to_thread(llm.chat, prompt)

        try:
            data = _json.loads(response_text)
            lesson_text    = data.get("lesson", "").strip()
            obstacle_text  = data.get("obstacle", "").strip()
        except Exception:
            lesson_text   = response_text.strip()[:500]
            obstacle_text = ""

        if not lesson_text:
            return

        # Embed, store Lesson node, link PRODUCED_LESSON
        vector    = await asyncio.to_thread(emb.embed, lesson_text, embedding_model)
        lesson_id = str(uuid.uuid4())
        now       = datetime.now(timezone.utc).isoformat()

        await gw.run(
            "lessons.create_quest_synthesis_lesson",
            lesson_id=lesson_id,
            text_raw=lesson_text,
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            created_at=now,
        )

        # Link MainQuest → Lesson
        try:
            await gw.run("lessons.link_quest_to_lesson", qid=quest_id, lid=lesson_id)
        except Exception:
            pass  # Quest may be a SideQuest — no PRODUCED_LESSON for SideQuest yet

        _logger.info("_synthesize_lesson: stored lesson %s for quest %s", lesson_id, quest_id)

    except Exception as e:
        _logger.exception("_synthesize_lesson error for quest %s: %s", quest_id, e)


async def upsert_lesson(params: dict, db: KuzuClient, config: dict, *,
                         principal: "Principal | None" = None) -> dict:
    """
    Explicitly add or update a Lesson node.

    params: {text, domain, lesson_type, session_id?, lesson_id?, scene_wl_hash?, scene_graph_vector?, archetype?, progress_score?, valence?, trigger?, idempotency_key?}
    trigger is an optional dict: {pattern, hook_type, tool, project_scope}

    B320: when the caller omits `lesson_id` (the common case — most callers
    have no durable id to pass, which is exactly what makes a retry mint a
    second node under the pre-B320 `str(uuid.uuid4())` fallback), this
    function dedupes on content_hash (or `idempotency_key`, if supplied)
    before minting a new id — see the dedup block below. An explicit
    `lesson_id` bypasses content-hash dedup entirely and keeps its
    pre-B320 match-by-id semantics (including the existing
    pathway_strength += 0.1 reinforcement on update), because a caller
    that names its own id has already declared its intent; silently
    routing that call to a different node because the content happens to
    match would violate it.

    B315: `workspace_id` used to be an optional request param here (B320's
    content-hash discriminator, default "local"). B315's forbidden-key
    guard now rejects any request whose `params` contains `workspace_id`
    before this handler ever runs (see brain_daemon.py::_dispatch) — the
    transport-derived `principal.workspace_id` is the only source now,
    defaulting to "local" when no principal was threaded in.
    """
    text        = params.get("text", "").strip()
    domain      = params.get("domain", "generic").strip()
    lesson_type = params.get("lesson_type", "optimization").strip()
    session_id  = params.get("session_id", "unknown")
    explicit_lesson_id = (params.get("lesson_id") or "").strip() or None
    idempotency_key = (params.get("idempotency_key") or "").strip() or None
    workspace_id = principal.workspace_id if principal is not None else "local"
    scene_wl_hash = (params.get("scene_wl_hash") or "").strip() or None
    scene_graph_vector = params.get("scene_graph_vector")
    if scene_graph_vector is not None and not isinstance(scene_graph_vector, str):
        scene_graph_vector = str(scene_graph_vector)
    archetype = (params.get("archetype") or "").strip() or None

    # Phase 2: Associative Hooks — trigger metadata
    trigger_meta = params.get("trigger") or {}
    trigger_pattern = (trigger_meta.get("pattern") or "").strip() or None
    trigger_hook_type = (trigger_meta.get("hook_type") or "").strip() or None
    trigger_tool = (trigger_meta.get("tool") or "").strip() or None
    trigger_project_scope = (trigger_meta.get("project_scope") or "").strip() or None
    try:
        progress_score = None if params.get("progress_score") is None else float(params.get("progress_score"))
    except Exception:
        progress_score = None
    try:
        valence = None if params.get("valence") is None else float(params.get("valence"))
    except Exception:
        valence = None

    if not text:
        return {"error": "text is required"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    gw = _gateway(db)
    vector = emb.embed(text, model_name=embedding_model)
    now = datetime.now(timezone.utc).isoformat()

    # B312: upsert_lesson is one of the two named primary-capture-path
    # write sites (the other is capture.py's notify_turn). `source`
    # defaults from the caller's agent_source using the same "agent:<id>"
    # convention already used elsewhere (see capture.py / work_summary.py);
    # `evidence_ref` defaults to the session_id being processed. Explicit
    # params always win.
    #
    # B315: when a principal has been threaded in, "<client>:<subject_id>"
    # is the authoritative default source — it composes B312 and B315, so
    # facts become attributable to a real transport-derived principal
    # rather than a caller-declared agent_source string. An explicit
    # `params["source"]` still wins over either default (a caller that
    # names its own source has a reason to).
    agent_source = (params.get("agent_source") or "mcp").strip()
    _default_source = (
        f"{principal.client}:{principal.subject_id}"
        if principal is not None else f"agent:{agent_source}"
    )
    prov_source = (params.get("source") or _default_source).strip()
    prov_source_version = params.get("source_version")
    prov_evidence_ref = params.get("evidence_ref") or (
        session_id if session_id != "unknown" else None
    )
    prov = provenance_fields(
        source=prov_source,
        source_version=prov_source_version,
        evidence_ref=prov_evidence_ref,
    )

    # B320: content_hash is always computed from what's about to be
    # written — even on an explicit-lesson_id call — so a *future* retry
    # that omits lesson_id can still find and dedupe against this row.
    content_hash_value = resolve_dedupe_key(
        table="Lesson",
        text=text,
        source=prov_source,
        workspace_id=workspace_id,
        extra={"domain": domain, "lesson_type": lesson_type},
        idempotency_key=idempotency_key,
    )

    # B320 Task 3/4: dedupe-on-write, only when no explicit lesson_id was
    # given (see the docstring above for why an explicit id bypasses this).
    content_dedup_hit = False
    lesson_id = explicit_lesson_id
    if lesson_id is None:
        lesson_id = await find_live_by_dedupe_key(
            db, table="Lesson", pk_column="lesson_id", dedupe_key=content_hash_value
        )
        if lesson_id is not None:
            content_dedup_hit = True
        else:
            lesson_id = str(uuid.uuid4())

    # KuzuDB 0.11.3: MERGE is incompatible with vector-indexed tables.
    # Use SELECT→CREATE-or-UPDATE instead.
    existing = await gw.run("lessons.find_lesson_by_id", lid=lesson_id)
    if not existing:
        await gw.run(
            "lessons.create_lesson",
            lid=lesson_id,
            text=text,
            emb=vector,
            model=embedding_model,
            dim=len(vector),
            domain=domain,
            type=lesson_type,
            scene_wl_hash=scene_wl_hash,
            scene_graph_vector=scene_graph_vector,
            archetype=archetype,
            progress_score=progress_score,
            valence=valence,
            now=now,
            trig_pattern=trigger_pattern,
            trig_hook_type=trigger_hook_type,
            trig_tool=trigger_tool,
            trig_scope=trigger_project_scope,
            prov_source=prov["source"],
            prov_source_version=prov["source_version"],
            prov_observed_at=prov["observed_at"],
            prov_evidence_ref=prov["evidence_ref"],
            content_hash=content_hash_value,
        )
    elif content_dedup_hit:
        # B320 Task 3: a content-hash (or idempotency_key) dedup hit is a
        # retry, not a reinforcement — default to NOT bumping
        # pathway_strength (under-counting reinforcement is recoverable;
        # inflating it from a network retry poisons ranking in a way
        # nothing later can undo). Deliberately skip the
        # `pathway_strength = pathway_strength + 0.1` branch below, which
        # is reserved for a caller-supplied `lesson_id` (a deliberate
        # re-upsert-by-id predating this card, not a retry) — the matched
        # row's content already equals what we were about to write (that's
        # what made the hash match), so there is nothing else to update.
        pass
    else:
        # Update non-embedding fields only (embedding cannot be SET on indexed property)
        await gw.run(
            "lessons.update_lesson",
            lid=lesson_id,
            text=text,
            domain=domain,
            type=lesson_type,
            scene_wl_hash=scene_wl_hash,
            scene_graph_vector=scene_graph_vector,
            archetype=archetype,
            progress_score=progress_score,
            valence=valence,
            trig_pattern=trigger_pattern,
            trig_hook_type=trigger_hook_type,
            trig_tool=trigger_tool,
            trig_scope=trigger_project_scope,
            prov_source=prov["source"],
            prov_source_version=prov["source_version"],
            prov_observed_at=prov["observed_at"],
            prov_evidence_ref=prov["evidence_ref"],
            content_hash=content_hash_value,
        )

    if session_id != "unknown":
        await gw.run("lessons.link_session_learned_lesson", sid=session_id, lid=lesson_id)

    # B323: derive AgentWorker + SOLVED_BY in the same write that set this
    # Lesson's B312 provenance (prov_source, which defaults to
    # "agent:<agent_source>" above) — never as a separate capture pass.
    try:
        await upsert_agent_worker_and_link(
            db,
            worker_id=prov["source"],
            node_table="Lesson",
            node_id=lesson_id,
            observed_at=prov["observed_at"],
        )
    except Exception:
        _logger.exception("B323: SOLVED_BY link failed for lesson %s", lesson_id)

    return {"lesson_id": lesson_id, "status": "upserted"}


async def recall_relevant_lessons(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Fetch lessons matching a domain or similarity to a query.
    
    params: {query?, domain?, limit}
    """
    query  = params.get("query", "")
    domain = params.get("domain", "")
    limit  = int(params.get("limit", 5))

    lessons = []

    if query:
        embedding_model = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        vector = emb.embed(query, model_name=embedding_model)
        rows = db.vector_search("Lesson", _LESSON_INDEX, vector, limit)
        for row in rows:
            node = row["node"]
            if node.get("archived"): continue
            lessons.append({
                "lesson_id": node["lesson_id"],
                "text": node["text_raw"],
                "domain": node.get("domain", "generic"),
                "type": node.get("lesson_type", "optimization"),
                "scene_wl_hash": node.get("scene_wl_hash"),
                "progress_score": node.get("progress_score"),
                "valence": node.get("valence"),
                "similarity": row["score"]
            })
    elif domain:
        gw = _gateway(db)
        rows = await gw.run("lessons.list_lessons_by_domain", domain=domain, limit=limit)
        for r in rows:
            lessons.append({
                "lesson_id": r["lesson_id"],
                "text": r["text_raw"],
                "domain": domain,
                "type": r["lesson_type"],
            })

    return {"lessons": lessons}


async def recall_scene_graph_priors(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Return evidence-weighted priors for a scene graph signature.

    params: {wl_hash, archetype?, min_valence?, limit?}
    """
    wl_hash = (params.get("wl_hash") or "").strip()
    archetype = (params.get("archetype") or "").strip()
    if not wl_hash:
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    try:
        min_valence = float(params.get("min_valence", 0.0))
    except Exception:
        min_valence = 0.0
    try:
        limit = max(1, int(params.get("limit", 50)))
    except Exception:
        limit = 50

    rows: list[dict] = []
    try:
        gw = _gateway(db)
        raw_rows = await gw.run(
            "lessons.list_scene_graph_priors",
            wl_hash=wl_hash,
            min_valence=min_valence,
            archetype=archetype,
            limit=limit,
        )
        for r in raw_rows:
            try:
                progress = float(r["progress_score"])
            except Exception:
                continue
            progress = max(0.0, min(1.0, progress))
            val = r["valence"]
            try:
                val = float(val) if val is not None else None
            except Exception:
                val = None
            rows.append(
                {
                    "lesson_id": r["lesson_id"],
                    "progress_score": progress,
                    "valence": val,
                    "archetype": r["archetype"] or "",
                    "text": r["text"] or "",
                }
            )
    except Exception:
        _logger.exception("recall_scene_graph_priors failed")
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    if not rows:
        return {"expected_progress": 0.0, "median_progress": 0.0, "evidence_count": 0, "priors": []}

    progresses = sorted(r["progress_score"] for r in rows)
    expected = sum(progresses) / len(progresses)
    mid = len(progresses) // 2
    median = progresses[mid] if len(progresses) % 2 == 1 else (progresses[mid - 1] + progresses[mid]) / 2.0

    return {
        "expected_progress": round(expected, 4),
        "median_progress": round(median, 4),
        "evidence_count": len(rows),
        "priors": rows,
    }
