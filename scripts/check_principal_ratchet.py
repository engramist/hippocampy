#!/usr/bin/env python3
"""
scripts/check_principal_ratchet.py — B315 principal-adoption ratchet.

B315 threads a `Principal` (campy/brain/auth.py) to tool handlers via
incremental, signature-inspection-based adoption (`_WANTS_PRINCIPAL` in
campy/brain_daemon.py) rather than rewriting every handler's signature in
one commit — see that module for the tradeoff this ratchet exists to make
durable. This script counts how many `TOOL_HANDLERS` entries do NOT yet
declare a `principal` parameter, compares that count against a checked-in
baseline, and fails if it rises. Follow-up cards convert more handlers and
lower the baseline (`--update`); once the count reaches zero, the
inspection branch in `_dispatch` and the `principal` default become
removable and the parameter becomes required everywhere.

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


def _non_adopting_handlers() -> list[str]:
    """Return TOOL_HANDLERS names whose real signature has no `principal` param.

    Mirrors campy/brain_daemon.py's `_WANTS_PRINCIPAL` computation exactly
    (same `inspect.signature()` call, which follows a wrapper's
    `__wrapped__` — see _shared.py::_with_phase — through to the real
    handler) so this script and the daemon can never silently disagree
    about which handlers have adopted `principal`.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from campy.brain.thalamus.tools import TOOL_HANDLERS

    non_adopting = [
        name for name, fn in TOOL_HANDLERS.items()
        if "principal" not in inspect.signature(fn).parameters
    ]
    return sorted(non_adopting)


def _load_baseline() -> int:
    if not BASELINE_PATH.exists():
        return 0
    return int(json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("non_adopting_count", 0))


def _write_baseline(count: int, names: list[str]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {"non_adopting_count": count, "non_adopting_handlers": names},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--update", action="store_true",
        help="rewrite scripts/principal_baseline.json to match the current tree (deliberate, reviewable)",
    )
    args = parser.parse_args(argv)

    non_adopting = _non_adopting_handlers()
    count = len(non_adopting)

    if args.update:
        _write_baseline(count, non_adopting)
        print(f"Baseline updated: non_adopting_count={count}")
        return 0

    baseline = _load_baseline()

    if count > baseline:
        print(
            f"FAIL: handlers not declaring `principal` increased: "
            f"{baseline} -> {count} (+{count - baseline})"
        )
        print("Newly non-adopting handlers may include:")
        for name in non_adopting:
            print(f"  {name}")
        print(
            "\nEither add `*, principal: Principal` to the new/reverted "
            "handler's signature, or if this is a deliberate new handler "
            "that legitimately can't adopt yet, run --update to move the "
            "baseline (and say why in the PR)."
        )
        return 1

    if count < baseline:
        print(
            f"Handlers declaring `principal` increased: {baseline} -> {count} "
            f"non-adopting (-{baseline - count}). Run with --update to lower the baseline."
        )
    else:
        print(f"Non-adopting handler count unchanged: {count}")

    print("Principal ratchet OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
