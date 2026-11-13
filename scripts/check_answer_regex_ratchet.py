#!/usr/bin/env python3
"""
Answer-code regex ratchet (PRINCIPLES.md, Principle 2: graph first).

"Python never counts, filters or joins what a query could." The usual way that rule is
broken is a new regular expression over question or answer text in the answering code.
This check counts regex call sites under campy/brain/thalamus/ and fails when the count
rises above scripts/answer_regex_baseline.json.

A new regex that is not answer logic (a path check, a parser for a fixed format) is
allowed: raise the baseline in the same PR with --update, where the reviewer sees it.

Usage:
    python scripts/check_answer_regex_ratchet.py            # check
    python scripts/check_answer_regex_ratchet.py --update   # rewrite the baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "answer_regex_baseline.json"
SCANNED = "campy/brain/thalamus"

REGEX_USE_RE = re.compile(r"\bre\.(?:compile|search|match|fullmatch|findall|finditer|sub|subn|split)\(")


def scan(root: Path) -> tuple[int, dict[str, int]]:
    """Return (total regex call sites, per-file counts) under SCANNED."""
    per_file: dict[str, int] = {}
    for path in sorted((root / SCANNED).rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = sum(len(REGEX_USE_RE.findall(line)) for line in text.splitlines()
                if not line.lstrip().startswith("#"))
        if n:
            per_file[rel] = n
    return sum(per_file.values()), per_file


def check(total: int, baseline: int) -> tuple[bool, str]:
    if total > baseline:
        return False, (f"FAIL: regex call sites under {SCANNED}/ increased: {baseline} -> {total} "
                       f"(+{total - baseline}).")
    if total < baseline:
        return True, (f"Regex call sites decreased: {baseline} -> {total}. "
                      "Run with --update to lower the baseline.")
    return True, f"Regex call sites unchanged: {total}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the baseline to match the tree")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    args = ap.parse_args(argv)

    total, per_file = scan(args.root)
    if args.update:
        BASELINE_PATH.write_text(json.dumps({"regex_call_sites": total}, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline updated: regex_call_sites={total}")
        return 0

    baseline = int(json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("regex_call_sites", 0))
    ok, msg = check(total, baseline)
    print(msg)
    if not ok:
        for rel, n in sorted(per_file.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {rel}")
        print("\nIf the new regex counts, filters or picks an answer from text, compute it with a "
              "NamedQuery anchored on the subject instead (skills/campy-graph/SKILL.md). If it is not "
              "answer logic, run with --update and say why in the PR.")
        return 1
    print("Answer-code regex ratchet OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
