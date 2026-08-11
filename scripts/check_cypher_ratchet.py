#!/usr/bin/env python3
"""
scripts/check_cypher_ratchet.py — B314 Cypher ratchet.

`campy/brain/hippocampus/graph/kuzu_client.py` claims migrating storage
engines means "rewrite this file only." That's only true once inline
Cypher stops leaking into every other module. B314 built the seam
(`GraphGateway` + `NamedQuery` + `QueryRegistry`,
`campy/brain/hippocampus/graph/gateway.py`) and proved it on one vertical
slice (`campy/brain/thalamus/tools/lessons.py`) — this script is what
makes that direction durable instead of aspirational: it counts inline
Cypher outside the sanctioned locations and the number of
`GraphGateway.execute_raw()` escape-hatch call sites, compares both
against a checked-in baseline, and fails if either count goes up.

Usage:
    python3 scripts/check_cypher_ratchet.py            # check (CI / make check-cypher)
    python3 scripts/check_cypher_ratchet.py --update    # rewrite the baseline (deliberate, reviewable)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "cypher_baseline.json"

# Files allowlisted for raw Cypher — every entry needs a reason (B314 Task 3):
ALLOWLIST_FILES = {
    # DDL (CREATE NODE TABLE, ALTER TABLE, ...) is inherently engine-specific
    # and correctly lives next to the engine adapter, not behind a
    # portability seam meant for application-level queries.
    "campy/brain/hippocampus/schema.py",
    # The one file that imports kuzu. Its Cypher is engine plumbing
    # (vector/FTS index CALL statements, schema introspection) that
    # GraphGateway itself is built on top of — routing it back through the
    # gateway would be circular.
    "campy/brain/hippocampus/graph/kuzu_client.py",
}

# Directory prefixes allowlisted wholesale:
ALLOWLIST_DIR_PREFIXES = (
    # The named-query registry itself — this is where migrated Cypher is
    # SUPPOSED to live.
    "campy/brain/hippocampus/graph/queries/",
)

# Only these top-level directories are scanned at all. In particular this
# excludes tests/ — fakes/mocks and real-KuzuClient integration tests
# legitimately contain Cypher text and are not part of the "~500+ call
# sites to migrate" problem this ratchet tracks.
SCANNED_PREFIXES = ("campy/", "scripts/")

# Files that talk *about* execute_raw() (this script's own regex source
# text, and gateway.py's own def/docstring/messages) but contain no actual
# call sites — scanning them would be a self-referential false positive,
# not migration debt.
NOT_A_CALL_SITE = {
    "scripts/check_cypher_ratchet.py",
    "campy/brain/hippocampus/graph/gateway.py",
}

CYPHER_LINE_RE = re.compile(r"\b(MATCH|CREATE|MERGE)\s")
EXECUTE_RAW_RE = re.compile(r"\bexecute_raw\s*\(")


def _is_allowlisted(rel_path: str) -> bool:
    if rel_path in ALLOWLIST_FILES:
        return True
    return any(rel_path.startswith(prefix) for prefix in ALLOWLIST_DIR_PREFIXES)


def scan(root: Path) -> tuple[int, int, dict[str, int]]:
    """Scan `root` for inline Cypher lines and `execute_raw()` call sites.

    Returns (cypher_line_count, execute_raw_count, per_file_cypher_counts).
    Only `.py` files under `SCANNED_PREFIXES` (relative to `root`) are
    scanned; files/dirs in the allowlist are skipped for the Cypher count
    (but still contribute to the execute_raw count — the escape hatch is
    tracked everywhere it's used, allowlisted file or not).
    """
    cypher_total = 0
    raw_total = 0
    per_file: dict[str, int] = {}

    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel:
            continue
        if not any(rel.startswith(prefix) for prefix in SCANNED_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if rel not in NOT_A_CALL_SITE:
            raw_total += len(EXECUTE_RAW_RE.findall(text))

        if _is_allowlisted(rel):
            continue

        count = sum(1 for line in text.splitlines() if CYPHER_LINE_RE.search(line))
        if count:
            per_file[rel] = count
            cypher_total += count

    return cypher_total, raw_total, per_file


def _load_baseline() -> dict[str, int]:
    if not BASELINE_PATH.exists():
        return {"cypher_lines": 0, "execute_raw_calls": 0}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline(cypher_total: int, raw_total: int) -> None:
    BASELINE_PATH.write_text(
        json.dumps({"cypher_lines": cypher_total, "execute_raw_calls": raw_total}, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--update", action="store_true",
        help="rewrite scripts/cypher_baseline.json to match the current tree (deliberate, reviewable)",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repo root to scan (default: this repo)")
    args = parser.parse_args(argv)

    cypher_total, raw_total, per_file = scan(args.root)

    if args.update:
        _write_baseline(cypher_total, raw_total)
        print(f"Baseline updated: cypher_lines={cypher_total} execute_raw_calls={raw_total}")
        return 0

    baseline = _load_baseline()
    baseline_cypher = int(baseline.get("cypher_lines", 0))
    baseline_raw = int(baseline.get("execute_raw_calls", 0))

    ok = True

    if cypher_total > baseline_cypher:
        ok = False
        print(
            f"FAIL: inline Cypher line count increased: "
            f"{baseline_cypher} -> {cypher_total} (+{cypher_total - baseline_cypher})"
        )
        print("Offending files (outside the allowlist), highest count first:")
        for rel, count in sorted(per_file.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {rel}")
        print(
            "\nMove this Cypher into a NamedQuery under "
            "campy/brain/hippocampus/graph/queries/ and call it through "
            "GraphGateway.run(). See B314."
        )
    elif cypher_total < baseline_cypher:
        print(
            f"Cypher line count decreased: {baseline_cypher} -> {cypher_total} "
            f"(-{baseline_cypher - cypher_total}). Run with --update to lower the baseline."
        )
    else:
        print(f"Cypher line count unchanged: {cypher_total}")

    if raw_total > baseline_raw:
        ok = False
        print(
            f"FAIL: GraphGateway.execute_raw() call count increased: "
            f"{baseline_raw} -> {raw_total} (+{raw_total - baseline_raw})"
        )
        print("Every execute_raw() call is migration debt — prefer a NamedQuery + gateway.run().")
    elif raw_total < baseline_raw:
        print(
            f"execute_raw() call count decreased: {baseline_raw} -> {raw_total}. "
            f"Run with --update to lower the baseline."
        )
    else:
        print(f"execute_raw() call count unchanged: {raw_total}")

    if not ok:
        return 1

    print("Cypher ratchet OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
