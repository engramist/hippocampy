#!/usr/bin/env python3
"""
scripts/check_principal_ratchet.py — B315 principal-adoption ratchet.

B315 built the `Principal`/`TransportContext`/`PrincipalResolver` seam
(`campy/brain/auth.py`) and converted the two primary-capture-path
handlers (`campy/brain/thalamus/tools/capture.py`'s `notify_turn`,
`campy/brain/thalamus/tools/lessons.py`'s `upsert_lesson`) to accept it.
Updating every handler registered in `TOOL_HANDLERS` in one card would be
a large mechanical diff with real regression risk (~40 handlers across
~14 modules) — see `brain_daemon.py`'s `_WANTS_PRINCIPAL` comment for the
signature-inspection tradeoff that makes incremental adoption possible.

This script is what makes that direction durable instead of aspirational,
matching `scripts/check_cypher_ratchet.py`'s (B314) shape and CLI: it
counts how many `TOOL_HANDLERS` entries do NOT declare a `principal`
parameter, compares that count against a checked-in baseline, and fails
if it goes up. Follow-up cards convert more handlers and lower the
baseline; once it reaches zero, `_WANTS_PRINCIPAL`'s inspection branch in
`brain_daemon.py` should be deleted and `principal` should become a
normal required parameter on every handler instead of an opt-in one.

Usage:
    python3 scripts/check_principal_ratchet.py            # check (CI / make check-principal)
    python3 scripts/check_principal_ratchet.py --update    # rewrite the baseline (deliberate, reviewable)
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "principal_baseline.json"


def _load_baseline() -> int:
    if not BASELINE_PATH.exists():
        return 0
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return int(data.get("handlers_without_principal", 0))


def _write_baseline(count: int, total: int) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {"handlers_without_principal": count, "total_handlers": total}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


def count_handlers_without_principal(root: Path) -> tuple[int, int, list[str]]:
    """Import `TOOL_HANDLERS` and count entries whose signature does not
    declare a `principal` parameter.

    Returns `(without_count, total_count, sorted_missing_names)`. Mirrors
    `brain_daemon.py`'s `_WANTS_PRINCIPAL` computation exactly (same
    `inspect.signature(fn).parameters` check) so this script's count and
    the daemon's actual dispatch behavior can never silently drift apart.
    """
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from campy.brain.thalamus.tools import TOOL_HANDLERS

    missing: list[str] = []
    for name, fn in TOOL_HANDLERS.items():
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            # A signature that can't be introspected certainly doesn't
            # declare `principal` — count it as missing rather than
            # silently skipping it.
            missing.append(name)
            continue
        if "principal" not in params:
            missing.append(name)

    return len(missing), len(TOOL_HANDLERS), sorted(missing)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite scripts/principal_baseline.json to match the current tree (deliberate, reviewable)",
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repo root to import from (default: this repo)"
    )
    args = parser.parse_args(argv)

    without, total, missing = count_handlers_without_principal(args.root)

    if args.update:
        _write_baseline(without, total)
        print(f"Baseline updated: handlers_without_principal={without} (of {total} total)")
        return 0

    baseline = _load_baseline()

    ok = True
    if without > baseline:
        ok = False
        print(
            f"FAIL: handlers missing `principal` increased: "
            f"{baseline} -> {without} (+{without - baseline})"
        )
        print(
            "A handler that used to declare `*, principal: Principal` no longer does, "
            "or a new handler was registered without it. Add `*, principal: Principal "
            "| None = None` to its signature (see capture.py's notify_turn / "
            "lessons.py's upsert_lesson for the pattern) — or, if this is a genuinely "
            "new handler that legitimately isn't converted yet, run with --update to "
            "raise the baseline deliberately (reviewable in the diff)."
        )
        print(f"\n{total - without} of {total} handlers declare `principal`. Missing:")
        for name in missing:
            print(f"  {name}")
    elif without < baseline:
        print(
            f"handlers missing `principal` decreased: {baseline} -> {without} "
            f"(-{baseline - without}). Run with --update to lower the baseline."
        )
    else:
        print(f"handlers missing `principal` unchanged: {without} (of {total} total)")

    if not ok:
        return 1

    print("Principal ratchet OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
