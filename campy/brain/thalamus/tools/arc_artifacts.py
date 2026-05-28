"""ARC artifact ingestion tools for graph-backed memory.

B225 imports evidence files produced by the sibling ARC_AGI repository into
KuzuDB. Raw JSON remains evidence/provenance; durable memory lives in graph
nodes and the wiki projects from those nodes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_FILES = {
    "master_timeline": "master_timeline.json",
    "agent_execution_trace": "agent_execution_trace.json",
    "submission_arc_server": "submission_results_arcServer.json",
    "submission_single": "submission_results_single.json",
    "submission_single_live": "submission_results_single.live.jsonl",
    "submission_single_world_model_live": "submission_results_single.world_model.live.jsonl",
}

ARC_DOMAINS = "arc,arc_agi,benchmark,evaluation,puzzle,agent-learning"
SUMMARY_LIMIT = 1200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(value: Any) -> str:
    return hashlib.sha256(_normalized_json(value).encode("utf-8")).hexdigest()


def _compact(value: Any, limit: int = SUMMARY_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = _normalized_json(value)
    text = " ".join(text.split())
    return text[:limit]


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _resolve_artifact_root(params: dict) -> tuple[Path | None, str | None]:
    explicit = params.get("artifact_root")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return (root, None) if root.exists() else (None, f"artifact_root does not exist: {root}")

    default_root = (Path.cwd().parent / "ARC_AGI").resolve()
    if default_root.exists():
        return default_root, None
    return None, "artifact_root is required unless ../ARC_AGI exists"


def _load_json_file(path: Path) -> tuple[Any, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, len(data)
    if isinstance(data, dict):
        for key in ("results", "tasks", "events", "timeline"):
            if isinstance(data.get(key), list):
                return data, len(data[key])
    return data, 1


def _load_jsonl_file(path: Path) -> tuple[list[dict], int, int]:
    records: list[dict] = []
    malformed = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
                else:
                    records.append({"value": value})
            except json.JSONDecodeError:
                malformed += 1
    return records, len(records), malformed


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _first_present(mapping: dict, keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def _extract_task_results(artifact_payloads: dict[str, Any]) -> list[dict]:
    task_results: dict[str, dict] = {}
    for kind in ("submission_single", "submission_arc_server"):
        payload = artifact_payloads.get(kind)
        if payload is None:
            continue
        for item in _iter_dicts(payload):
            task_id = _first_present(item, ("task_id", "task", "id"))
            puzzle_id = _first_present(item, ("puzzle_id", "game_id", "dataset_id"))
            looks_like_result = any(k in item for k in ("correct", "status", "final_state", "failure_class", "steps"))
            if not (task_id or puzzle_id) or not looks_like_result:
                continue

            tokens = item.get("tokens") if isinstance(item.get("tokens"), dict) else {}
            correct = item.get("correct")
            if correct is None and item.get("status"):
                correct = str(item.get("status")).lower() in {"correct", "solved", "success", "passed"}
            steps = _safe_int(_first_present(item, ("steps", "step_count", "num_steps")))
            result_hash = _record_hash({"kind": kind, "task_id": task_id, "puzzle_id": puzzle_id, "item": item})
            stable_key = f"{task_id or puzzle_id or result_hash}:{result_hash[:12]}"
            task_results[stable_key] = {
                "task_result_id": f"arc-task-{hashlib.sha256(stable_key.encode()).hexdigest()[:24]}",
                "task_id": str(task_id or ""),
                "puzzle_id": str(puzzle_id or ""),
                "status": str(_first_present(item, ("status", "final_state"), "solved" if correct else "failed")),
                "correct": bool(correct),
                "steps": steps,
                "tokens_input": _safe_int(_first_present(item, ("tokens_input", "input_tokens"), tokens.get("input"))),
                "tokens_output": _safe_int(_first_present(item, ("tokens_output", "output_tokens"), tokens.get("output"))),
                "failure_class": str(_first_present(item, ("failure_class", "error_class", "error_message"), "")),
                "trajectory_score": _safe_float(_first_present(item, ("trajectory_score", "score"))),
                "summary": _summarize_task(item),
            }
    return list(task_results.values())


def _event_like(item: dict) -> bool:
    keys = {
        "event",
        "event_type",
        "snapshot_type",
        "call_type",
        "tool_name",
        "name",
        "action_id",
        "action_name",
        "phase",
        "outcome",
        "state_after",
    }
    return bool(keys.intersection(item.keys()))


def _extract_events(artifact_payloads: dict[str, Any], max_events: int) -> list[dict]:
    events: list[dict] = []
    event_sources = ("master_timeline", "agent_execution_trace", "submission_single_live")
    for kind in event_sources:
        payload = artifact_payloads.get(kind)
        if payload is None:
            continue
        for item in _iter_dicts(payload):
            if not _event_like(item):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            event_hash = _record_hash({"kind": kind, "idx": len(events), "item": item})
            task_id = str(_first_present(item, ("task_id", "task"), data.get("task_id", "")) or "")
            events.append(
                {
                    "event_id": f"arc-event-{event_hash[:24]}",
                    "task_id": task_id,
                    "event_type": str(_first_present(item, ("event_type", "snapshot_type", "event", "call_type"), data.get("call_type", kind))),
                    "timestamp": str(_first_present(item, ("timestamp_iso", "timestamp", "created_at"), data.get("timestamp_iso", "")) or ""),
                    "step_index": _safe_int(_first_present(item, ("step", "step_index", "step_num"), data.get("step"))),
                    "actor": str(_first_present(item, ("source", "actor", "role"), "")),
                    "tool_name": str(_first_present(item, ("tool_name", "name", "call_type"), data.get("call_type", "")) or ""),
                    "action_name": str(_first_present(item, ("action_name", "action_id"), "")),
                    "outcome": str(_first_present(item, ("outcome", "state_after", "phase_answer"), data.get("result_summary", "")) or ""),
                    "summary": _summarize_event(item),
                    "artifact_kind": kind,
                }
            )
            if len(events) >= max_events:
                return events
    return events


def _summarize_task(item: dict) -> str:
    parts = []
    for key in ("game_id", "task_id", "correct", "steps", "final_state", "failure_class", "error_message"):
        if key in item and item[key] not in (None, ""):
            parts.append(f"{key}={item[key]}")
    return "; ".join(parts) or _compact(item, 500)


def _summarize_event(item: dict) -> str:
    parts = []
    for key in ("source", "name", "event", "snapshot_type", "phase", "action_id", "state_after", "guard_status", "what"):
        if key in item and item[key] not in (None, ""):
            parts.append(f"{key}={item[key]}")
    if item.get("phase_answer"):
        parts.append(f"phase_answer={_compact(item['phase_answer'], 240)}")
    if item.get("rationale"):
        parts.append(f"rationale={_compact(item['rationale'], 240)}")
    return "; ".join(parts) or _compact(item, 500)


def _extract_world_model_steps(artifact_payloads: dict[str, Any]) -> list[dict]:
    steps: list[dict] = []
    payload = artifact_payloads.get("submission_single_world_model_live")
    if not isinstance(payload, list):
        return []
    for item in payload:
        if item.get("kind") != "world_model_step":
            continue
        data = item.get("data", {})
        step_hash = _record_hash(item)
        steps.append({
            "world_model_step_id": f"arc-wm-step-{step_hash[:24]}",
            "task_id": str(item.get("task_id", "")),
            "step_index": _safe_int(item.get("step")),
            "node_count": _safe_int(data.get("node_count")),
            "edge_count": _safe_int(data.get("edge_count")),
            "compiled_claim_count": _safe_int(data.get("compiled_claim_count")),
            "action_effect_class": str(data.get("action_effect_class", "")),
            "reasoning_mode": str(data.get("reasoning_mode", "")),
            "planner_candidate_count": _safe_int(data.get("planner_candidate_count")),
            "single_action_stall_detected": bool(data.get("single_action_stall_detected")),
            "summary": _compact(item, 500),
            "created_at": str(item.get("timestamp_iso", "")),
        })
    return steps


def _extract_world_model_summaries(artifact_payloads: dict[str, Any]) -> list[dict]:
    summaries: list[dict] = []
    payload = artifact_payloads.get("submission_single_world_model_live")
    if not isinstance(payload, list):
        return []
    for item in payload:
        if item.get("kind") != "world_model_summary":
            continue
        data = item.get("data", {})
        summary_hash = _record_hash(item)
        summaries.append({
            "world_model_summary_id": f"arc-wm-sum-{summary_hash[:24]}",
            "task_id": str(item.get("task_id", "")),
            "graph_bounded": bool(data.get("graph_bounded")),
            "compiler_active": bool(data.get("compiler_active")),
            "falsification_active": bool(data.get("falsification_active")),
            "reasoning_gated": bool(data.get("reasoning_gated")),
            "planner_grounded": bool(data.get("planner_grounded")),
            "memory_transfer_active": bool(data.get("memory_transfer_active")),
            "single_action_stall_detected": bool(data.get("single_action_stall_detected")),
            "full_reasoning_cycles_avoided": _safe_int(data.get("full_reasoning_cycles_avoided")),
            "summary": _compact(item, 500),
            "created_at": str(item.get("timestamp_iso", "")),
        })
    return summaries


def _build_run(root: Path, artifacts: list[dict], task_results: list[dict], events: list[dict]) -> dict:
    combined_hash = hashlib.sha256("".join(a["content_hash"] for a in artifacts).encode("utf-8")).hexdigest()
    task_count = len(task_results)
    solved_count = sum(1 for t in task_results if t["correct"])
    failed_count = max(task_count - solved_count, 0)
    step_count = sum((t.get("steps") or 0) for t in task_results)
    timestamps = [e["timestamp"] for e in events if e.get("timestamp")]
    source_files = [a["path"] for a in artifacts]
    status = "solved" if task_count and solved_count == task_count else ("failed" if task_count else "observed")
    summary = (
        f"ARC run from {root}. tasks={task_count}, solved={solved_count}, "
        f"failed={failed_count}, steps={step_count}, events={len(events)}."
    )
    return {
        "run_id": f"arc-run-{combined_hash[:24]}",
        "artifact_hash": combined_hash,
        "source_root": str(root),
        "source_files": json.dumps(source_files, sort_keys=True),
        "started_at": min(timestamps) if timestamps else "",
        "completed_at": max(timestamps) if timestamps else "",
        "status": status,
        "variant": "sidequests",
        "task_count": task_count,
        "solved_count": solved_count,
        "failed_count": failed_count,
        "step_count": step_count,
        "domain": ARC_DOMAINS,
        "summary": summary,
    }


async def _upsert_artifact(db, artifact: dict, now: str) -> None:
    await db.execute_write(
        """
        MERGE (a:ArcArtifact {artifact_id: $artifact_id})
        SET a.artifact_kind = $artifact_kind,
            a.path = $path,
            a.content_hash = $content_hash,
            a.record_count = $record_count,
            a.captured_at = $captured_at,
            a.ingested_at = timestamp($now),
            a.domain = $domain,
            a.summary = $summary
        """,
        {**artifact, "now": now},
    )


async def _upsert_run(db, run: dict, now: str) -> None:
    await db.execute_write(
        """
        MERGE (r:ArcRun {run_id: $run_id})
        SET r.artifact_hash = $artifact_hash,
            r.source_root = $source_root,
            r.source_files = $source_files,
            r.started_at = $started_at,
            r.completed_at = $completed_at,
            r.status = $status,
            r.variant = $variant,
            r.task_count = $task_count,
            r.solved_count = $solved_count,
            r.failed_count = $failed_count,
            r.step_count = $step_count,
            r.domain = $domain,
            r.summary = $summary,
            r.created_at = timestamp($now),
            r.updated_at = timestamp($now)
        """,
        {**run, "now": now},
    )


async def _upsert_task(db, run_id: str, task: dict, now: str) -> None:
    await db.execute_write(
        """
        MERGE (t:ArcTaskResult {task_result_id: $task_result_id})
        SET t.run_id = $run_id,
            t.task_id = $task_id,
            t.puzzle_id = $puzzle_id,
            t.status = $status,
            t.correct = $correct,
            t.steps = $steps,
            t.tokens_input = $tokens_input,
            t.tokens_output = $tokens_output,
            t.failure_class = $failure_class,
            t.trajectory_score = $trajectory_score,
            t.domain = $domain,
            t.summary = $summary,
            t.created_at = timestamp($now),
            t.updated_at = timestamp($now)
        """,
        {**task, "run_id": run_id, "domain": ARC_DOMAINS, "now": now},
    )
    await db.execute_write(
        """
        MATCH (r:ArcRun {run_id: $run_id})
        MATCH (t:ArcTaskResult {task_result_id: $task_result_id})
        MERGE (r)-[:ARC_RUN_HAS_TASK]->(t)
        """,
        {"run_id": run_id, "task_result_id": task["task_result_id"]},
    )


async def _upsert_event(db, run_id: str, event: dict, now: str) -> None:
    event_params = {k: v for k, v in event.items() if k != "artifact_kind"}
    await db.execute_write(
        """
        MERGE (e:ArcEvent {event_id: $event_id})
        SET e.run_id = $run_id,
            e.task_id = $task_id,
            e.event_type = $event_type,
            e.timestamp = $timestamp,
            e.step_index = $step_index,
            e.actor = $actor,
            e.tool_name = $tool_name,
            e.action_name = $action_name,
            e.outcome = $outcome,
            e.domain = $domain,
            e.summary = $summary
        """,
        {**event_params, "run_id": run_id, "domain": ARC_DOMAINS},
    )
    if event.get("task_id"):
        await db.execute_write(
            """
            MATCH (t:ArcTaskResult {task_id: $task_id})
            MATCH (e:ArcEvent {event_id: $event_id})
            MERGE (t)-[:ARC_TASK_HAS_EVENT]->(e)
            """,
            {"task_id": event["task_id"], "event_id": event["event_id"]},
        )


async def _link_run_artifact(db, run_id: str, artifact_id: str) -> None:
    await db.execute_write(
        """
        MATCH (r:ArcRun {run_id: $run_id})
        MATCH (a:ArcArtifact {artifact_id: $artifact_id})
        MERGE (r)-[:ARC_RUN_HAS_ARTIFACT]->(a)
        """,
        {"run_id": run_id, "artifact_id": artifact_id},
    )


async def _link_event_artifact(db, event_id: str, artifact_id: str) -> None:
    await db.execute_write(
        """
        MATCH (e:ArcEvent {event_id: $event_id})
        MATCH (a:ArcArtifact {artifact_id: $artifact_id})
        MERGE (e)-[:ARC_EVENT_FROM_ARTIFACT]->(a)
        """,
        {"event_id": event_id, "artifact_id": artifact_id},
    )


async def _upsert_wm_step(db, run_id: str, step: dict) -> None:
    await db.execute_write(
        """
        MERGE (s:ArcWorldModelStep {world_model_step_id: $world_model_step_id})
        SET s.run_id = $run_id,
            s.task_id = $task_id,
            s.step_index = $step_index,
            s.node_count = $node_count,
            s.edge_count = $edge_count,
            s.compiled_claim_count = $compiled_claim_count,
            s.action_effect_class = $action_effect_class,
            s.reasoning_mode = $reasoning_mode,
            s.planner_candidate_count = $planner_candidate_count,
            s.single_action_stall_detected = $single_action_stall_detected,
            s.summary = $summary,
            s.created_at = $created_at
        """,
        {**step, "run_id": run_id},
    )
    await db.execute_write(
        """
        MATCH (r:ArcRun {run_id: $run_id})
        MATCH (s:ArcWorldModelStep {world_model_step_id: $world_model_step_id})
        MERGE (r)-[:ARC_RUN_HAS_WORLD_MODEL_STEP]->(s)
        """,
        {"run_id": run_id, "world_model_step_id": step["world_model_step_id"]},
    )


async def _upsert_wm_summary(db, run_id: str, summary: dict) -> None:
    await db.execute_write(
        """
        MERGE (s:ArcWorldModelSummary {world_model_summary_id: $world_model_summary_id})
        SET s.run_id = $run_id,
            s.task_id = $task_id,
            s.graph_bounded = $graph_bounded,
            s.compiler_active = $compiler_active,
            s.falsification_active = $falsification_active,
            s.reasoning_gated = $reasoning_gated,
            s.planner_grounded = $planner_grounded,
            s.memory_transfer_active = $memory_transfer_active,
            s.single_action_stall_detected = $single_action_stall_detected,
            s.full_reasoning_cycles_avoided = $full_reasoning_cycles_avoided,
            s.summary = $summary,
            s.created_at = $created_at
        """,
        {**summary, "run_id": run_id},
    )
    await db.execute_write(
        """
        MATCH (r:ArcRun {run_id: $run_id})
        MATCH (s:ArcWorldModelSummary {world_model_summary_id: $world_model_summary_id})
        MERGE (r)-[:ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(s)
        """,
        {"run_id": run_id, "world_model_summary_id": summary["world_model_summary_id"]},
    )


async def _link_wm_artifact(db, step_id: str, artifact_id: str, kind: str) -> None:
    table = "ArcWorldModelStep" if kind == "step" else "ArcWorldModelSummary"
    id_field = "world_model_step_id" if kind == "step" else "world_model_summary_id"
    rel = "ARC_WORLD_MODEL_FROM_ARTIFACT" if kind == "step" else "ARC_WORLD_MODEL_SUMMARY_FROM_ARTIFACT"
    await db.execute_write(
        f"""
        MATCH (s:{table} {{{id_field}: $step_id}})
        MATCH (a:ArcArtifact {{artifact_id: $artifact_id}})
        MERGE (s)-[:{rel}]->(a)
        """,
        {"step_id": step_id, "artifact_id": artifact_id},
    )


async def ingest_arc_artifacts(params: dict, db, config: dict) -> dict:
    """Import ARC_AGI run artifacts into SideQuests graph memory."""
    root, error = _resolve_artifact_root(params or {})
    if error:
        return {"ok": False, "error": error}

    include_live_jsonl = bool((params or {}).get("include_live_jsonl", True))
    dry_run = bool((params or {}).get("dry_run", False))
    max_events = int((params or {}).get("max_events", 5000) or 5000)
    now = _now_iso()

    artifacts: list[dict] = []
    payloads: dict[str, Any] = {}
    skipped_missing: list[str] = []
    malformed_records = 0

    for kind, filename in ARTIFACT_FILES.items():
        if kind == "submission_single_live" and not include_live_jsonl:
            continue
        path = root / filename
        if not path.exists():
            skipped_missing.append(filename)
            continue
        raw = path.read_bytes()
        content_hash = _sha256_bytes(raw)
        try:
            if path.suffix == ".jsonl":
                payload, record_count, malformed = _load_jsonl_file(path)
                malformed_records += malformed
            else:
                payload, record_count = _load_json_file(path)
        except Exception:
            malformed_records += 1
            continue

        payloads[kind] = payload
        artifacts.append(
            {
                "artifact_id": f"arc-artifact-{kind}-{content_hash[:16]}",
                "artifact_kind": kind,
                "path": str(path),
                "content_hash": content_hash,
                "record_count": record_count,
                "captured_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "domain": ARC_DOMAINS,
                "summary": f"{kind} artifact with {record_count} record(s) from {path.name}",
            }
        )

    task_results = _extract_task_results(payloads)
    events = _extract_events(payloads, max_events=max_events)
    wm_steps = _extract_world_model_steps(payloads)
    wm_summaries = _extract_world_model_summaries(payloads)
    run = _build_run(root, artifacts, task_results, events) if artifacts else None

    summary = {
        "ok": True,
        "artifact_root": str(root),
        "artifacts_scanned": len([k for k in ARTIFACT_FILES if include_live_jsonl or k != "submission_single_live"]),
        "artifacts_ingested": len(artifacts),
        "runs_upserted": 1 if run else 0,
        "task_results_upserted": len(task_results),
        "events_upserted": len(events),
        "wm_steps_upserted": len(wm_steps),
        "wm_summaries_upserted": len(wm_summaries),
        "malformed_records_skipped": malformed_records,
        "missing_files": skipped_missing,
        "dry_run": dry_run,
    }

    if dry_run or not run:
        return summary

    await _upsert_run(db, run, now)
    artifact_by_kind = {a["artifact_kind"]: a for a in artifacts}
    for artifact in artifacts:
        await _upsert_artifact(db, artifact, now)
        await _link_run_artifact(db, run["run_id"], artifact["artifact_id"])
    for task in task_results:
        await _upsert_task(db, run["run_id"], task, now)
    for event in events:
        await _upsert_event(db, run["run_id"], event, now)
        artifact = artifact_by_kind.get(event.get("artifact_kind"))
        if artifact:
            await _link_event_artifact(db, event["event_id"], artifact["artifact_id"])
    
    wm_artifact = artifact_by_kind.get("submission_single_world_model_live")
    for step in wm_steps:
        await _upsert_wm_step(db, run["run_id"], step)
        if wm_artifact:
            await _link_wm_artifact(db, step["world_model_step_id"], wm_artifact["artifact_id"], "step")
    for wm_sum in wm_summaries:
        await _upsert_wm_summary(db, run["run_id"], wm_sum)
        if wm_artifact:
            await _link_wm_artifact(db, wm_sum["world_model_summary_id"], wm_artifact["artifact_id"], "summary")

    return summary
