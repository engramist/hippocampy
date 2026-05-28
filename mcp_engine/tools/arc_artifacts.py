"""
mcp_engine/tools/arc_artifacts.py — compatibility shim

Canonical implementation has moved to:
    campy.brain.thalamus.tools.arc_artifacts
"""
# ruff: noqa: F401

from campy.brain.thalamus.tools.arc_artifacts import (
    ARTIFACT_FILES,
    ARC_DOMAINS,
    SUMMARY_LIMIT,
    ingest_arc_artifacts,
    # Private helpers that may be imported by tests
    _now_iso,
    _sha256_bytes,
    _normalized_json,
    _record_hash,
    _compact,
    _safe_int,
    _safe_float,
    _resolve_artifact_root,
    _load_json_file,
    _load_jsonl_file,
    _iter_dicts,
    _first_present,
    _extract_task_results,
    _event_like,
    _extract_events,
    _summarize_task,
    _summarize_event,
    _extract_world_model_steps,
    _extract_world_model_summaries,
    _build_run,
    _upsert_artifact,
    _upsert_run,
    _upsert_task,
    _upsert_event,
    _link_run_artifact,
    _link_event_artifact,
    _upsert_wm_step,
    _upsert_wm_summary,
    _link_wm_artifact,
)
