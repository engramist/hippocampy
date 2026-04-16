#!/usr/bin/env python3
"""Fetch recent Phoenix traces into repo-local JSON files for review."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "sidequests.toml"
OBSERVABILITY_DIR = REPO_ROOT / "observability"
EXPORTS_DIR = OBSERVABILITY_DIR / "exports"
LATEST_JSON_PATH = OBSERVABILITY_DIR / "latest_traces.json"


def load_toml(path: Path) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    with path.open("rb") as f:
        return tomllib.load(f)


def resolve_cli_command() -> list[str]:
    if shutil.which("px"):
        return ["px"]
    if shutil.which("npx"):
        return ["npx", "@arizeai/phoenix-cli"]
    raise RuntimeError("Phoenix CLI not found. Install `px` or make `npx` available.")


def run_command(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def aggregate_trace_files(export_dir: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for path in sorted(export_dir.glob("*.json")):
        try:
            traces.append(json.loads(path.read_text()))
        except Exception as exc:
            traces.append(
                {
                    "traceId": path.stem,
                    "load_error": str(exc),
                    "source_file": str(path.relative_to(REPO_ROOT)),
                }
            )
    return traces


def build_summary(trace: dict[str, Any]) -> dict[str, Any]:
    spans = trace.get("spans") or []
    root_span = trace.get("rootSpan") or {}
    return {
        "trace_id": trace.get("traceId"),
        "status": trace.get("status"),
        "duration_ms": trace.get("duration"),
        "span_count": len(spans),
        "root_span_name": root_span.get("name"),
        "source_file": trace.get("_source_file"),
    }


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def derive_quality_metrics(traces: list[dict[str, Any]]) -> dict[str, Any]:
    task_spans: list[dict[str, Any]] = []
    retrieval_ops = 0
    replan_ops = 0
    total_invalid_actions = 0
    total_steps = 0

    for trace in traces:
        spans = trace.get("spans") or []
        for span in spans:
            name = str(span.get("name") or "")
            attrs = span.get("attributes") or {}
            events = span.get("events") or []

            if name in {"arc.task", "sidequests.task"}:
                task_spans.append(attrs)
                invalid = _as_int(attrs.get("invalid_action_count")) or 0
                steps = _as_int(attrs.get("step_count")) or _as_int(attrs.get("steps")) or 0
                total_invalid_actions += max(0, invalid)
                total_steps += max(0, steps)

            if name in {"brain.current_truth", "sidequests.current_truth"}:
                retrieval_ops += 1

            for event in events:
                event_name = str(event.get("name") or "")
                event_attrs = event.get("attributes") or {}
                if event_name in {"brain.current_truth", "sidequests.current_truth"}:
                    retrieval_ops += 1
                to_phase = str(event_attrs.get("details.to_phase") or event_attrs.get("to_phase") or "").lower()
                op = str(event_attrs.get("operation") or "")
                if to_phase == "replan" or op == "agent.phase.transition" and str(event_attrs.get("details.to_phase") or "").lower() == "replan":
                    replan_ops += 1

    solved = 0
    failures: dict[str, int] = {}
    steps_values: list[int] = []
    token_in_values: list[int] = []
    token_out_values: list[int] = []
    cost_values: list[float] = []
    no_progress = 0
    supervisor_interventions = 0
    strategy_race_wins = 0
    strategy_race_total = 0

    for attrs in task_spans:
        correct = bool(attrs.get("correct", False))
        if correct:
            solved += 1
        failure_class = str(attrs.get("failure_class") or "none")
        failures[failure_class] = failures.get(failure_class, 0) + 1
        step_count = _as_int(attrs.get("step_count")) or _as_int(attrs.get("steps"))
        if step_count is not None:
            steps_values.append(step_count)
        tin = _as_int(attrs.get("tokens_in"))
        tout = _as_int(attrs.get("tokens_out"))
        if tin is not None:
            token_in_values.append(tin)
        if tout is not None:
            token_out_values.append(tout)
        cost = _as_float(attrs.get("cost_usd"))
        if cost is not None:
            cost_values.append(cost)
        if (_as_int(attrs.get("no_progress_streak")) or 0) > 0:
            no_progress += 1
        if str(attrs.get("supervisor_verdict") or "none") not in {"none", "", "null"}:
            supervisor_interventions += 1
        if attrs.get("strategy_race_winner") is not None:
            strategy_race_total += 1
            if bool(attrs.get("strategy_race_winner")):
                strategy_race_wins += 1

    task_count = len(task_spans)
    return {
        "task_count": task_count,
        "solve_rate": (solved / task_count) if task_count else None,
        "failure_class_frequency": failures,
        "avg_steps_per_puzzle": (sum(steps_values) / len(steps_values)) if steps_values else None,
        "avg_tokens_in_per_puzzle": (sum(token_in_values) / len(token_in_values)) if token_in_values else None,
        "avg_tokens_out_per_puzzle": (sum(token_out_values) / len(token_out_values)) if token_out_values else None,
        "avg_cost_usd_per_puzzle": (sum(cost_values) / len(cost_values)) if cost_values else None,
        "retrieval_frequency_per_task": (retrieval_ops / task_count) if task_count else None,
        "replan_frequency_per_task": (replan_ops / task_count) if task_count else None,
        "supervisor_intervention_rate": (supervisor_interventions / task_count) if task_count else None,
        "invalid_action_rate": (total_invalid_actions / total_steps) if total_steps else None,
        "no_progress_or_loop_stall_rate": (no_progress / task_count) if task_count else None,
        "strategy_racing_win_rate": (strategy_race_wins / strategy_race_total) if strategy_race_total else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull Phoenix traces into observability/latest_traces.json")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to sidequests.toml")
    parser.add_argument("--limit", type=int, default=10, help="Maximum traces to fetch")
    parser.add_argument("--since", type=str, default=None, help="Optional ISO-8601 lower time bound")
    parser.add_argument("--last-n-minutes", type=int, default=None, help="Only fetch traces from the last N minutes")
    parser.add_argument("--project", type=str, default=None, help="Override Phoenix project name")
    parser.add_argument("--host", type=str, default=None, help="Override Phoenix host, e.g. http://127.0.0.1:6006")
    parser.add_argument("--include-annotations", action="store_true", help="Include Phoenix annotations in exported traces")
    args = parser.parse_args()

    config = load_toml(args.config)
    obs_cfg = config.get("observability", {}) if isinstance(config, dict) else {}

    endpoint = args.host or os.environ.get("PHOENIX_HOST")
    if not endpoint:
        endpoint = str(obs_cfg.get("endpoint") or "http://127.0.0.1:6006/v1/traces")
        endpoint = endpoint.replace("/v1/traces", "")

    project = args.project or os.environ.get("PHOENIX_PROJECT") or str(obs_cfg.get("project_name") or "default")

    export_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_dir = EXPORTS_DIR / export_stamp
    export_dir.mkdir(parents=True, exist_ok=True)
    OBSERVABILITY_DIR.mkdir(parents=True, exist_ok=True)

    cli = resolve_cli_command()
    cmd = [*cli, "trace", "list", str(export_dir), "--limit", str(args.limit), "--project", project, "--endpoint", endpoint, "--format", "json", "--no-progress"]
    if args.since:
        cmd.extend(["--since", args.since])
    if args.last_n_minutes is not None:
        cmd.extend(["--last-n-minutes", str(args.last_n_minutes)])
    if args.include_annotations:
        cmd.append("--include-annotations")

    env = dict(os.environ)
    env["PHOENIX_HOST"] = endpoint
    env["PHOENIX_PROJECT"] = project

    result = run_command(cmd, env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout or "Phoenix trace export failed\n")
        return result.returncode

    traces = aggregate_trace_files(export_dir)
    for trace, path in zip(traces, sorted(export_dir.glob("*.json"))):
        if isinstance(trace, dict):
            trace["_source_file"] = str(path.relative_to(REPO_ROOT))

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "phoenix_host": endpoint,
        "phoenix_project": project,
        "limit": args.limit,
        "source_command": cmd,
        "export_dir": str(export_dir.relative_to(REPO_ROOT)),
        "trace_count": len(traces),
        "trace_summaries": [build_summary(trace) for trace in traces if isinstance(trace, dict)],
        "quality_metrics": derive_quality_metrics([t for t in traces if isinstance(t, dict)]),
        "traces": traces,
    }
    LATEST_JSON_PATH.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
    print(f"Raw trace files: {export_dir.relative_to(REPO_ROOT)}")
    print(f"Project: {project}")
    print(f"Host: {endpoint}")
    print(f"Trace count: {len(traces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
