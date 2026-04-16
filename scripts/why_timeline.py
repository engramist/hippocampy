#!/usr/bin/env python3
"""Print a human-readable WHY timeline from Phoenix-exported traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LATEST_TRACES_PATH = REPO_ROOT / "observability" / "latest_traces.json"


def _compact(text: Any, limit: int = 180) -> str:
    raw = "" if text is None else str(text)
    one_line = " ".join(raw.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def _pick_trace(payload: dict[str, Any], trace_id: str | None, latest: bool) -> dict[str, Any] | None:
    traces = payload.get("traces") or []
    if not traces:
        return None
    if trace_id:
        for trace in traces:
            if trace.get("traceId") == trace_id:
                return trace
        return None
    if latest:
        return traces[0]
    # Default: choose trace with most spans/events as likely richest run.
    def richness(trace: dict[str, Any]) -> tuple[int, int]:
        spans = trace.get("spans") or []
        events = sum(len(span.get("events") or []) for span in spans)
        return (len(spans), events)

    return sorted(traces, key=richness, reverse=True)[0]


def _extract_steps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    steps: dict[int, dict[str, Any]] = {}
    spans = trace.get("spans") or []
    for span in spans:
        for event in span.get("events") or []:
            attrs = event.get("attributes") or {}
            op = attrs.get("operation")
            if op not in {"agent.policy.decision", "agent.phase.outcome"}:
                continue
            step_val = attrs.get("details.step")
            if step_val is None:
                continue
            try:
                step = int(step_val)
            except Exception:
                continue
            slot = steps.setdefault(step, {"step": step})
            if op == "agent.policy.decision":
                slot["prompt"] = attrs.get("details.prompt")
                slot["input_observation"] = attrs.get("details.input_observation")
                slot["available_actions"] = attrs.get("details.available_actions")
                slot["action_id"] = attrs.get("result.action_id")
                slot["decision_source"] = attrs.get("result.decision_source")
                slot["guard_status"] = attrs.get("result.guard_status")
                slot["rationale"] = attrs.get("result.rationale")
                slot["thinking_trace"] = attrs.get("result.thinking_trace")
            elif op == "agent.phase.outcome":
                slot["reward"] = attrs.get("result.reward")
                slot["done"] = attrs.get("result.done")
                slot["state_after"] = attrs.get("result.state_after")
                slot["output_observation"] = attrs.get("result.output_observation")
    return [steps[k] for k in sorted(steps.keys())]


def main() -> int:
    parser = argparse.ArgumentParser(description="Print WHY timeline from observability/latest_traces.json")
    parser.add_argument("--input", type=Path, default=LATEST_TRACES_PATH, help="Path to latest_traces.json")
    parser.add_argument("--trace-id", type=str, default=None, help="Specific traceId to inspect")
    parser.add_argument("--latest", action="store_true", help="Use first trace from file rather than richest")
    parser.add_argument("--max-steps", type=int, default=50, help="Maximum steps to print")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input file not found: {args.input}")
        return 1

    payload = json.loads(args.input.read_text())
    trace = _pick_trace(payload, args.trace_id, args.latest)
    if not trace:
        print("No trace found for the requested selection.")
        return 1

    steps = _extract_steps(trace)
    print(f"trace_id: {trace.get('traceId')}")
    print(f"span_count: {len(trace.get('spans') or [])}")
    print(f"why_steps: {len(steps)}")
    if not steps:
        print("No 'agent.policy.decision' events found. Run a fresh puzzle after instrumentation.")
        return 0

    for row in steps[: max(1, args.max_steps)]:
        print("")
        print(f"STEP {row.get('step')}")
        print(f"prompt: {_compact(row.get('prompt'))}")
        print(f"input: {_compact(row.get('input_observation'))}")
        print(f"actions: {_compact(row.get('available_actions'))}")
        print(
            f"decision: action={row.get('action_id')} source={row.get('decision_source')} guard={row.get('guard_status')}"
        )
        print(f"why: {_compact(row.get('rationale'))}")
        print(f"outcome: state={row.get('state_after')} reward={row.get('reward')} done={row.get('done')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

