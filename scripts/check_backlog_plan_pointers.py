#!/usr/bin/env python3
"""
scripts/check_backlog_plan_pointers.py — backlog `Plan:` pointer guard.

Every backlog card carries a `Plan:` header. Most cards are self-contained
and say so inline (`Plan: (inline — this card is self-contained)`), or admit
that no plan exists yet (`Plan: none yet — needs a design pass first.`).
Both of those are fine and this script ignores them.

What is NOT fine is a `Plan:` line that names a concrete
`backlog/plans/*.md` file which does not exist. That points the next reader
(human or agent) at a file they cannot open, and the failure is silent —
nothing in CI noticed that 17 cards had accumulated pointers to plan files
that were never written. This script closes that gap: it resolves every
plan path named on a `Plan:` line and fails if the target is missing.

Fixing a failure means one of:
  * the card body already carries the scope/constraints/acceptance criteria
    — replace the pointer with `Plan: (inline — this card is self-contained)`;
  * the card genuinely needs a design pass — say so
    (`Plan: none yet — needs a design pass before an implementation plan.`);
  * the plan really should exist — write it at the named path.

Do NOT "fix" this by inventing a plan file full of design decisions nobody
has actually made.

Usage:
    python3 scripts/check_backlog_plan_pointers.py   # check (CI / make check-plan-pointers)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A `Plan:` header line, at the start of a line.
PLAN_LINE_RE = re.compile(r"^Plan:(.*)$", re.MULTILINE)

# A path to a plan file, with or without the leading `backlog/`. Stops at
# whitespace and at the markdown/punctuation characters that would wrap an
# inline reference (backticks, brackets, parens, commas).
PLAN_PATH_RE = re.compile(r"(?:backlog/)?plans/[^\s`'\"()\[\],]+\.md")


def _resolve(root: Path, raw: str) -> Path:
    """Resolve a plan path from a card to a real filesystem path."""
    rel = raw if raw.startswith("backlog/") else f"backlog/{raw}"
    return root / rel


def scan(root: Path) -> tuple[list[tuple[str, int, str]], int, int]:
    """Scan backlog cards for `Plan:` pointers.

    Returns (dangling, pointer_count, card_count) where `dangling` is a list
    of (card path, 1-indexed line number, plan path as written).
    """
    dangling: list[tuple[str, int, str]] = []
    pointers = 0
    cards = sorted((root / "backlog").glob("*.md"))

    for card in cards:
        text = card.read_text(encoding="utf-8")
        for match in PLAN_LINE_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            for raw in PLAN_PATH_RE.findall(match.group(1)):
                pointers += 1
                if not _resolve(root, raw).is_file():
                    dangling.append((str(card.relative_to(root)), line_no, raw))

    return dangling, pointers, len(cards)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repo root to scan (default: this repo)"
    )
    args = parser.parse_args(argv)

    dangling, pointers, cards = scan(args.root)

    if dangling:
        print(f"FAIL: {len(dangling)} backlog card(s) point at a plan file that does not exist:")
        for card, line_no, raw in dangling:
            print(f"  {card}:{line_no}  ->  {raw}")
        print(
            "\nFix each card by replacing the pointer with the inline note style used "
            "elsewhere in backlog/ (`Plan: (inline — this card is self-contained)`) when the "
            "card body already carries enough scope to act on, or by stating that a plan is "
            "still needed (`Plan: none yet — ...`). Write the plan file only if the plan "
            "genuinely exists — do not invent design decisions to satisfy this check."
        )
        return 1

    print(
        f"Backlog plan pointers OK: {pointers} pointer(s) across {cards} card(s) all resolve."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
