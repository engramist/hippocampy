"""Turn capture and ingestion path handlers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING
import uuid

from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.schema import upsert_agent_worker_and_link
from campy.brain.brainstem.secret_scrubber import scrub_before_ingest

from ._shared import (
    _CONCEPT_INDEX,
    _LESSON_INDEX,
    _PLAN_INDEX,
    _PROCEDURE_INDEX,
    detect_ordered_plan_steps,
    has_plan_signal,
    _logger,
    _safe_result_dict,
    _session_active_plan_id,
    get_loop_queue,
    get_or_create_main_quest,
    get_or_create_session,
    infer_outcome_valence_detail,
)
from .lessons import _create_plan_graph, _store_plan_outcome_lesson
from .quests import report_outcome

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.auth import Principal



async def _maybe_create_passive_plan_from_turn(
    *,
    db,
    content: str,
    session_id: str,
    embedding_model: str,
    now_iso: str,
    capture_source: str | None = None,
    evidence_ref: str | None = None,
    idempotency_key: str | None = None,
    workspace_id: str = "local",
) -> dict | None:
    """B68 Layer B fallback: infer plan from structured text if not actively declared.

    B320: `idempotency_key`/`workspace_id` thread straight through to
    `_create_plan_graph`'s content-hash dedup — see that function's
    docstring. Note this function already had its own B279 near-duplicate
    guard (embedding cosine similarity > 0.90 against recent Plans, just
    below) before this card; that is a *different*, fuzzier mechanism
    (semantic near-duplicate detection) than B320's exact-content dedup,
    and the two are complementary, not redundant — B279 catches "a
    differently-worded restatement of the same plan", B320 catches "the
    exact same capture, retried".
    """
    if not has_plan_signal(content):
        return None

    steps = detect_ordered_plan_steps(content)
    if len(steps) < 3:
        return None

    goal = content.split("\n", 1)[0].strip()[:240] or "Passively detected plan"
    goal_vec = emb.embed(goal, model_name=embedding_model)

    # B279: dedup against existing plans by true cosine similarity > 0.90.
    try:
        existing = db.vector_search("Plan", _PLAN_INDEX, goal_vec, 6)
        for row in existing:
            if float(row.get("score", 0.0) or 0.0) > 0.90:
                return None
    except Exception:
        pass

    plan_id, step_ids, quest_id = await _create_plan_graph(
        db=db,
        goal=goal,
        steps=steps,
        session_id=session_id,
        embedding_model=embedding_model,
        now_iso=now_iso,
        source="passive",
        confidence=0.70,
        confidence_low=True,
        capture_source=capture_source,
        evidence_ref=evidence_ref,
        idempotency_key=idempotency_key,
        workspace_id=workspace_id,
    )
    return {"plan_id": plan_id, "step_ids": step_ids, "quest_id": quest_id}


from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


async def notify_turn(params: dict, db: KuzuClient, config: dict, *,
                       principal: "Principal | None" = None) -> dict:
    """
    Receive a conversation turn from the adapter and store it as a Message node.
    M5: also resolves/creates the MainQuest from git context, upserts Session.

    params: {role, content, session_id, repo_root?, git_branch?, idempotency_key?}

    B320: `idempotency_key`, when supplied, replaces content-hash dedup as
    the identity key for any Tier-1 fact-bearing node this turn causes to
    be written (passive plan detection, outcome-sense lesson) — see
    provenance.resolve_dedupe_key(). A well-behaved client that retries
    this exact call should pass the same `idempotency_key` on every
    attempt; a client that does nothing still gets exact-content dedup for
    free via content_hash(). Neither parameter affects the Message node
    this call also writes — Message is a structural/runtime-record table
    (B312's PROVENANCE_TABLES scope excludes it), not a fact-bearing one,
    so it carries no content_hash column and is out of this card's scope
    by design.

    B315: `workspace_id` used to be read from `params` here (with a
    "local" default) purely as a content-hash discriminator — it never
    routed to a different database, since B316 (per-workspace DB) had not
    landed yet. B315's forbidden-key guard now rejects any request whose
    `params` contains `workspace_id` before this handler ever runs (see
    brain_daemon.py::_dispatch), so that path is gone: workspace identity
    for the content hash now comes from `principal.workspace_id` — the
    transport-derived value, never the request body — defaulting to
    "local" only when no principal was threaded in (an un-converted
    caller path; see the `_WANTS_PRINCIPAL` ratchet).
    """
    role       = params.get("role", "user")
    content    = params.get("content", "")
    session_id = params.get("session_id", "unknown")
    repo_root  = params.get("repo_root", "")
    git_branch = params.get("git_branch", "main")
    idempotency_key = (params.get("idempotency_key") or "").strip() or None
    workspace_id = principal.workspace_id if principal is not None else "local"

    # B321: the platform's App id/session id, for cross-session continuity
    # (app_continuity() / bundle_compiler._stage_app_continuity). Unlike
    # workspace_id above, an App id is NOT a security boundary — B315
    # forbids workspace_id from request params specifically because it
    # controls *which database* a request routes to; external_app_id is
    # just an opaque label the caller attaches to its own Session row, so
    # it is fine as ordinary tool input (see backlog/B321.md Task 5).
    external_app_id = (params.get("external_app_id") or "").strip() or None
    external_session_id = (params.get("external_session_id") or "").strip() or None

    # B312: provenance identifier for any Tier-1 facts this turn causes to be
    # written (passive plan detection, outcome-sense lessons). B315: when a
    # principal has been threaded in, it is the authoritative identity for
    # this write — "<client>:<subject_id>" — rather than the guessed
    # "agent:<agent_source>" string, so facts become attributable to a real
    # transport-derived principal instead of a caller-declared label.
    # Without a principal (an un-converted caller path), fall back to the
    # pre-B315 "agent:<id>" / "user:direct" convention documented in
    # schema.py's PROVENANCE_TABLES comment. agent_source follows the same
    # params.get("agent_source", "mcp") convention already used below for
    # WorkSummary (B290).
    _capture_agent_source = params.get("agent_source", "mcp")
    if principal is not None:
        capture_source = f"{principal.client}:{principal.subject_id}"
    else:
        capture_source = "user:direct" if role == "user" else f"agent:{_capture_agent_source}"

    max_chars = config.get("ingestion", {}).get("max_ingest_chars", 4000)
    if len(content) > max_chars:
        # D5 fix: fall back to word boundary if no sentence period found.
        truncated = content[:max_chars]
        idx = truncated.rfind(".")
        if idx > 0:
            content = truncated[:idx + 1]
        else:
            idx = truncated.rfind(" ")
            content = (truncated[:idx] if idx > 0 else truncated) + "…"

    if not content.strip():
        return {"status": "skipped", "reason": "empty content"}

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # B338/B365-verification-round3: scrub BEFORE embedding, not after. The
    # embedding vector is queryable via semantic recall -- if it were derived
    # from unscrubbed content, a secret redacted out of text_raw could still
    # be retrieved by (near-variants of) that same secret, defeating part of
    # the scrubber's purpose. Order matters here: content must be fully
    # scrubbed before anything derived from it (the vector) is computed or
    # persisted.
    content, scrub_metadata = await scrub_before_ingest(content)
    if scrub_metadata.get("was_scrubbed"):
        _logger.warning(
            "B338: Content scrubbed before ingest. Detected %d secrets (types: %s) "
            "in session %s. Secrets redacted as [REDACTED:secret_type].",
            scrub_metadata["secrets_found"],
            ", ".join(scrub_metadata["secret_types"]),
            session_id,
        )

    vector     = emb.embed(content, model_name=embedding_model)
    message_id = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()

    # Route session via Hippocampus (all sessions, not just git)
    quest_id = ""
    if repo_root:
        # Legacy git path — fast and deterministic
        quest_id = await get_or_create_main_quest(
            db, repo_root, git_branch, embedding_model, now
        )
        await get_or_create_session(db, session_id, quest_id, now)
    else:
        # Semantic routing — no git context available
        from campy.brain.hippocampus.hippocampus import route_session
        try:
            result = await route_session(
                db, session_id, content, embedding_model,
                workspace_path=params.get("workspace_path", ""),
                config=config,
            )
            quest_id = result.quest_id
        except Exception:
            _logger.exception("hippocampus.route_session failed")
    token_limit = params.get("token_limit", 0)
    if token_limit and session_id != "unknown":
        try:
            gw = _gateway(db)
            await gw.run("capture.set_session_token_limit", sid=session_id, limit=int(token_limit))
        except Exception:
            pass

    # B321: best-effort — never blocks capture, never overwrites a value
    # already recorded from an earlier turn (see the NamedQuery's
    # COALESCE). Routed through GraphGateway/NamedQuery (B314), not raw
    # Cypher here, per the card.
    if (external_app_id or external_session_id) and session_id != "unknown":
        try:
            gw = _gateway(db)
            await gw.run(
                "app_continuity.set_session_external_ids",
                session_id=session_id,
                external_app_id=external_app_id,
                external_session_id=external_session_id,
            )
        except Exception:
            _logger.exception(
                "B321: failed to set external_app_id/external_session_id for session %s",
                session_id,
            )

    # B298: upsert semantics for piggybacked Claude auto-memory. The hook sends
    # a stable source_memory_key (hash of the memory's `name:` frontmatter) and
    # embeds the same key in the content as a "memory_key: <hash>" line. Editing
    # the same memory file must supersede, not append — so archive any earlier
    # live Message carrying the same key before writing the new version. The
    # marker match is on text content because Message has no dedicated key
    # column; the marker line is machine-generated and collision-safe.
    source_memory_key = (params.get("source_memory_key") or "").strip()
    if source_memory_key:
        try:
            gw = _gateway(db)
            await gw.run("capture.archive_earlier_message_version", marker=f"memory_key: {source_memory_key}")
        except Exception:
            _logger.exception("B298 auto-memory supersede failed for key %s", source_memory_key)

    # Write Message node
    gw = _gateway(db)
    await gw.run(
        "capture.create_message",
        message_id=message_id,
        text_raw=content,
        embedding=vector,
        embedding_model=embedding_model,
        embedding_dim=len(vector),
        role=role,
        byte_end=len(content.encode()),
        created_at=now,
    )

    # B18: Update token estimate for this message
    if session_id != "unknown":
        from campy.brain.thalamus.working_memory import update_token_estimate, estimate_tokens
        try:
            msg_tokens = estimate_tokens(content)
            await update_token_estimate(db, session_id, msg_tokens)
        except Exception:
            pass

    # B91: Passive Graph Pre-Activation (Warm Frontier)
    if session_id != "unknown":
        from campy.brain.temporal_lobe.warm_frontier import compute_warm_frontier
        try:
            await compute_warm_frontier(db, session_id, vector, config)
        except Exception:
            _logger.debug("compute_warm_frontier failed for session %s", session_id)

    # Link Message → Session
    if session_id != "unknown":
        gw = _gateway(db)
        await gw.run(
            "capture.link_message_sent_in_session",
            session_id=session_id,
            message_id=message_id,
        )

    # B192: Create FOLLOWED_BY edge from the previous message in the same session
    if session_id != "unknown":
        try:
            gw = _gateway(db)
            prev_r = gw.run_sync(
                "capture.find_previous_message_in_session",
                sid=session_id,
                mid=message_id,
            )
            if prev_r:
                prow = prev_r[0]
                prev_id = prow.get("m.message_id") if hasattr(prow, "get") else prow[0]
                prev_created = prow.get("m.created_at") if hasattr(prow, "get") else prow[1]
                gap_seconds = 0.0
                try:
                    prev_dt = datetime.fromisoformat(str(prev_created))
                    now_dt = datetime.fromisoformat(now)
                    gap_seconds = (now_dt - prev_dt).total_seconds()
                except Exception:
                    gap_seconds = 0.0

                await gw.run(
                    "capture.merge_followed_by",
                    prev=prev_id,
                    curr=message_id,
                    gap=gap_seconds,
                )
        except Exception:
            _logger.exception("Failed to write FOLLOWED_BY for message %s", message_id)

    # Update routing strength for subsequent messages (not the first)
    if quest_id and not repo_root:
        from campy.brain.hippocampus.hippocampus import update_routing_strength, get_active_quests_with_embeddings
        try:
            quests = get_active_quests_with_embeddings(db)
            quest_emb = next((q["purpose_embedding"] for q in quests
                              if q["quest_id"] == quest_id), None)
            if quest_emb:
                await update_routing_strength(db, session_id, vector, quest_emb)
        except Exception:
            pass

    # Enqueue for Gated Consolidation Loop (M3+)
    loop_queue = get_loop_queue()
    if loop_queue is not None:
        precomputed = params.get("precomputed")
        await loop_queue.put((message_id, content, role, session_id, precomputed))

    # B14: Read previous loop summary (completed by the time this fires)
    insights = None
    mc_base = (config.get("mission_control", {}) or {}).get("base_url", "http://127.0.0.1:8001")
    if session_id != "unknown":
        import json as _json
        try:
            gw = _gateway(db)
            r = gw.run_sync("capture.get_last_loop_summary", sid=session_id)
            if r:
                row = r[0]
                raw = row.get("s.last_loop_summary") if hasattr(row, "get") else row[0]
                if raw:
                    insights = _json.loads(raw)
                    # B15: Inject memory links into insights for easy auditing
                    if isinstance(insights, dict) and "new_entities" in insights:
                        for ent in insights["new_entities"]:
                            if "id" in ent:
                                ent["memory_link"] = f"{mc_base}/memory/node/{ent['id']}"
        except Exception:
            pass  # Non-critical

    passive_plan = None
    response_outcome_lesson_id = None
    # B68: passive structural plan detection from natural-language ordered steps.
    try:
        if session_id != "unknown":
            passive_plan = await _maybe_create_passive_plan_from_turn(
                db=db,
                content=content,
                session_id=session_id,
                embedding_model=embedding_model,
                now_iso=now,
                capture_source=capture_source,
                evidence_ref=message_id,
                idempotency_key=idempotency_key,
                workspace_id=workspace_id,
            )
    except Exception:
        _logger.exception("passive plan detection failed")

    # B69: outcome sense (success/failure language) can auto-report outcome.
    # B301: restricted to user turns. Outcome valence is meant as a reward
    # signal from the user/environment ("perfect", "that broke", "revert it"),
    # not a grade an assistant gives its own work — an assistant summarizing
    # its own passing test run must not be able to mint a "failure" Lesson.
    # Mirrors the ISSUE-024 precedent in classify_artifact (step4_pattern.py),
    # which caps assistant-role artifact confidence for the same self-report-
    # poisoning reason. Explicit report_outcome MCP calls are unaffected —
    # agents can still self-report deliberately via that path.
    try:
        if role == "user":
            inferred_valence, trigger_signals = infer_outcome_valence_detail(content)
            if inferred_valence is not None and session_id != "unknown":
                active_plan_id = _session_active_plan_id(db, session_id)
                if active_plan_id:
                    await report_outcome(
                        {
                            "plan_id": active_plan_id,
                            "outcome": content,
                            "valence": inferred_valence,
                            "session_id": session_id,
                            "valence_source": "system",
                            "trigger_signals": trigger_signals,
                        },
                        db,
                        config,
                    )
                elif abs(inferred_valence) > 0.7:
                    outcome_lesson_id = await _store_plan_outcome_lesson(
                        db,
                        plan_id="",
                        outcome=content,
                        valence=inferred_valence,
                        session_id=session_id,
                        embedding_model=embedding_model,
                        now_iso=now,
                        trigger_signals=trigger_signals,
                        capture_source=capture_source,
                        evidence_ref=message_id,
                        idempotency_key=idempotency_key,
                        workspace_id=workspace_id,
                    )
                    if outcome_lesson_id:
                        # B323: derive AgentWorker + SOLVED_BY in the same
                        # write that set this Lesson's B312 provenance
                        # (capture_source), never as a separate pass. No-ops
                        # for "user:direct" (this branch is user-turn-only —
                        # see the B301 note above) since there is no
                        # AgentWorker for a human source; kept here so the
                        # derivation lives alongside notify_turn's other
                        # capture_source-driven writes.
                        await upsert_agent_worker_and_link(
                            db,
                            worker_id=capture_source,
                            node_table="Lesson",
                            node_id=outcome_lesson_id,
                            observed_at=now,
                        )
                        response_outcome_lesson_id = outcome_lesson_id
    except Exception:
        _logger.exception("outcome sense auto-report failed")

    # -----------------------------------------------------------------------
    # B195: Active Context Push (proactive_context)
    # - Match high-confidence negative Lessons, Procedures, and KnowledgeGaps
    # - Rate-limit pushes to one per `min_turns_between_pushes` (default 5)
    # - Record pushed nodes with LOADED edges source="proactive_push"
    proactive_context = None
    try:
        if session_id != "unknown":
            from campy.brain.thalamus.working_memory import get_session_token_state, track_loaded

            state = get_session_token_state(db, session_id) or {}
            current_msg_count = int(state.get("message_count", 0) or 0)

            # Read last push count from Session node
            last_push_count = None
            try:
                gw = _gateway(db)
                lr = gw.run_sync("capture.get_last_proactive_push_count", sid=session_id)
                if lr:
                    row = lr[0]
                    val = row.get("s.last_proactive_push_msg_count") if hasattr(row, "get") else row[0]
                    if val is not None:
                        try:
                            last_push_count = int(val)
                        except Exception:
                            last_push_count = None
            except Exception:
                last_push_count = None

            window = int((config.get("proactive_push", {}) or {}).get("min_turns_between_pushes", 5))
            allowed = False
            if last_push_count is None:
                allowed = True
            else:
                allowed = (current_msg_count - last_push_count) >= window

            if allowed:
                embedding_model = config.get("embeddings", {}).get(
                    "model", "sentence-transformers/all-MiniLM-L6-v2"
                )
                try:
                    qvec = emb.embed(content, model_name=embedding_model)
                except Exception:
                    qvec = None

                candidates: list[dict] = []

                # 1) High-confidence negative Lessons by semantic similarity
                try:
                    if qvec is not None:
                        lessons = db.vector_search("Lesson", _LESSON_INDEX, qvec, 5)
                        for it in lessons:
                            node = _safe_result_dict(it.get("node", {}))
                            conf = float(node.get("confidence") or 0.0)
                            text = (node.get("text_raw") or "")
                            if conf >= 0.8 and "failure" in text.lower():
                                candidates.append({
                                    "node_id": node.get("lesson_id"),
                                    "node_type": "Lesson",
                                    "text_raw": text,
                                    "lesson_id": node.get("lesson_id"),
                                    "text": text,
                                    "type": node.get("lesson_type") or "lesson",
                                    "domain": node.get("domain") or "generic",
                                })
                except Exception:
                    _logger.debug("proactive: lesson search failed")

                # 2) Relevant Procedures via semantic search
                try:
                    if qvec is not None:
                        procs = db.vector_search("Procedure", _PROCEDURE_INDEX, qvec, 3)
                        for it in procs:
                            node = _safe_result_dict(it.get("node", {}))
                            text = node.get("description", "") or ""
                            candidates.append({
                                "node_id": node.get("procedure_id"),
                                "node_type": "Procedure",
                                "text_raw": text,
                                "procedure_id": node.get("procedure_id"),
                                "text": text,
                                "type": "procedure",
                                "domain": node.get("archetype") or node.get("domain") or "generic",
                            })
                except Exception:
                    _logger.debug("proactive: procedure search failed")

                # 3) KnowledgeGaps by simple text-match on description/domain
                try:
                    snippet = (content or "")[:120]
                    gw = _gateway(db)
                    kgq = gw.run_sync(
                        "capture.find_knowledge_gaps_for_content",
                        snippet=snippet,
                        lim=3,
                    )
                    for row in kgq:
                        gid = row.get("g.gap_id") if hasattr(row, "get") else row[0]
                        text = (row.get("g.description") if hasattr(row, "get") else row[1]) or ""
                        candidates.append({
                            "node_id": gid,
                            "node_type": "KnowledgeGap",
                            "text_raw": text,
                            "gap_id": gid,
                            "text": text,
                            "type": "knowledge_gap",
                            "domain": "generic",
                        })
                except Exception:
                    _logger.debug("proactive: knowledge gap lookup failed")

                if candidates:
                    try:
                        # Record LOADED edges so the LLM is aware these nodes were injected
                        await track_loaded(db, session_id, candidates, source="proactive_push")
                        # Persist last push marker on Session
                        try:
                            gw = _gateway(db)
                            await gw.run(
                                "capture.set_last_proactive_push_count",
                                sid=session_id,
                                count=current_msg_count,
                            )
                        except Exception:
                            _logger.debug("proactive: failed to persist last_proactive_push_msg_count")
                        proactive_context = {"pushed": True, "items": candidates}
                    except Exception:
                        _logger.exception("proactive: track_loaded failed")
                else:
                    proactive_context = {"pushed": False, "reason": "no_matches"}
            else:
                next_allowed = window - (current_msg_count - (last_push_count or 0))
                proactive_context = {"pushed": False, "reason": "rate_limited", "next_allowed_in_turns": max(next_allowed, 0)}
    except Exception:
        _logger.exception("proactive push failed")

    response = {
        "status": "ingested",
        "message_id": message_id,
        "quest_id": quest_id,
    }
    if insights:
        response["insights"] = insights
    if passive_plan:
        response["passive_plan"] = passive_plan
    if response_outcome_lesson_id:
        response["outcome_lesson_id"] = response_outcome_lesson_id
    # Always include proactive_context (B195) for caller to inspect
    response["proactive_context"] = proactive_context if proactive_context is not None else {"pushed": False, "reason": "disabled"}

    # B290: Continuous Work State — fire non-blocking WorkSummary update.
    # Use module-level attribute access (_cws.update_work_summary) so that
    # tests can patch the function via patch("...work_summary.update_work_summary")
    # without the `from ... import` reference-copy defeating the mock.
    # Note: bare create_task (no retention set) matches the existing pattern in
    # this file (line 2207). The event loop is long-lived so GC is not a concern here.
    if session_id != "unknown":
        try:
            from campy.brain.thalamus.tools import work_summary as _cws
            _agent_source = params.get("agent_source", "mcp")
            asyncio.create_task(
                _cws.update_work_summary(session_id, db, config, _agent_source, repo_root)
            )
        except Exception:
            pass  # Never block the response path

    return response
