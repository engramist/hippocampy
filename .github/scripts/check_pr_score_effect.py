#!/usr/bin/env python3
"""
PR score-effect check for hippocampy.

A PR that changes retrieval, answering or config code must say what it did to
the benchmark score: a `## Score effect` section with a gate table, or
`None — <reason>`. PRs that touch none of those paths pass without it.

Usage (called by .github/workflows/pr-score-effect.yml):
    python check_pr_score_effect.py --base main

Environment:
    GITHUB_EVENT_PATH   — pull_request event payload (PR body is read from it)

Exit codes:
    0 — check passed
    1 — relevant paths changed and the Score effect section is missing/empty
"""
import argparse
import json
import os
import re
import subprocess
import sys

# Retrieval / answering / config code: changes here need a score-effect statement.
RELEVANT_PATHS = (
    "campy/brain/thalamus/",
    "campy/brain/hippocampus/graph/",
    "campy/brain/hippocampus/observations.py",
    "campy/brain/llm/",
    "campy/brain/brainstem/config.py",
)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SECTION_RE = re.compile(r"^##[ \t]+Score effect[ \t]*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}[ \t]+\S", re.MULTILINE)


def relevant_files(changed):
    """Return the changed files that fall under RELEVANT_PATHS."""
    return [f for f in changed if any(f == p or f.startswith(p) for p in RELEVANT_PATHS)]


def score_effect_section(body):
    """Return the Score effect section text with HTML comments removed, or None if absent."""
    body = (body or "").replace("\r\n", "\n")
    m = _SECTION_RE.search(body)
    if not m:
        return None
    rest = body[m.end():]
    nxt = _NEXT_HEADING_RE.search(_COMMENT_RE.sub("", rest))
    text = _COMMENT_RE.sub("", rest)
    if nxt:
        text = text[: nxt.start()]
    return text.strip()


def check(body, changed):
    """Return (ok, message)."""
    hits = relevant_files(changed)
    if not hits:
        return True, "No retrieval/answering/config paths changed; score effect not required."
    section = score_effect_section(body)
    if section:
        return True, "Score effect section present."
    shown = "\n".join(f"  - {f}" for f in hits[:10])
    reason = "is missing" if section is None else "is empty (only the template comment)"
    return False, (
        f"The '## Score effect' section {reason}, but this PR changes retrieval, answering "
        f"or config code:\n{shown}\n\n"
        "Fill it with a gate table (suite | main | branch | gained | lost) on the published "
        "metric, or write 'None — <reason>' if the change cannot move the score. "
        "See the Principles section of AGENTS.md."
    )


def changed_files(base):
    out = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base}...HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="base branch (default: from event payload, else main)")
    args = ap.parse_args(argv)
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    pr = event.get("pull_request") or {}
    base = args.base or (pr.get("base") or {}).get("ref") or "main"
    ok, msg = check(pr.get("body") or "", changed_files(base))
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
