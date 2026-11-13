#!/usr/bin/env python3
"""
PR score-effect check for hippocampy.

A PR that changes retrieval, answering or config code must say what it did to
the benchmark score: a `## Score effect` section with a gate table, or
`None — <reason>`. PRs that touch none of those paths pass without it.

Since step 0e (2026-11-13) the Score effect section of those PRs must also carry a prediction made before the
run: a line `Prediction: <expected measure and size>`, or `Prediction: none — <reason>` when the change cannot
move a measure.

The same PRs also need a `## Graph design` section (B518): the edge(s) the change
reads or writes and the query that reads them (SPARQL or a NamedQuery name), or
`None — <reason>`. See skills/campy-graph/SKILL.md, "Design-review checklist".

Usage (called by .github/workflows/pr-score-effect.yml):
    python check_pr_score_effect.py --base main

Environment:
    GITHUB_EVENT_PATH   — pull_request event payload (PR body is read from it)

Exit codes:
    0 — check passed
    1 — relevant paths changed and the Score effect or Graph design section is missing/empty
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
    "campy/brain/hippocampus/",  # graph store, schema and capture (incl. graph/, observations.py)
    "campy/brain/temporal_lobe/",  # capture: what gets written decides what can be answered
    "campy/brain/llm/",
    "campy/brain/brainstem/config.py",
)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}[ \t]+\S", re.MULTILINE)


def relevant_files(changed):
    """Return the changed files that fall under RELEVANT_PATHS."""
    return [f for f in changed if any(f == p or f.startswith(p) for p in RELEVANT_PATHS)]


def section_text(body, title):
    """Return the `## <title>` section text with HTML comments removed, or None if absent."""
    body = (body or "").replace("\r\n", "\n")
    m = re.search(rf"^##[ \t]+{re.escape(title)}[ \t]*$", body, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    rest = body[m.end():]
    nxt = _NEXT_HEADING_RE.search(_COMMENT_RE.sub("", rest))
    text = _COMMENT_RE.sub("", rest)
    if nxt:
        text = text[: nxt.start()]
    return text.strip()


def score_effect_section(body):
    return section_text(body, "Score effect")


# A filled Graph design section names a SPARQL form or a NamedQuery (`domain.verb_subject`),
# or says `None — <reason>`.
_SPARQL_RE = re.compile(r"\b(SELECT|ASK|CONSTRUCT)\b")
_NAMED_QUERY_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*_[a-z0-9_]+\b")
_NONE_RE = re.compile(r"^\W*None\s*[—–-]\s*\S")


def graph_design_ok(section):
    if not section:
        return False
    return bool(_NONE_RE.match(section) or _SPARQL_RE.search(section) or _NAMED_QUERY_RE.search(section))


# A gate table (a markdown row with the gained/lost counts) must say how many of the lever's target
# questions the gate holds (B520): `Targets in gate: N` (N >= 10), `all`, or `none — <reason>`.
_GATE_ROW_RE = re.compile(r"^\s*\|.*\b(gained|lost)\b", re.IGNORECASE | re.MULTILINE)
_TARGETS_RE = re.compile(r"^\W*Targets in gate:[ \t]*(\d+|all|none[ \t]*[—–-][ \t]*\S.*)$", re.IGNORECASE | re.MULTILINE)
MIN_TARGETS = 10


def targets_in_gate_ok(section):
    """Return (ok, problem). Sections without a gate table (`None — <reason>`) need no line."""
    if not _GATE_ROW_RE.search(section or ""):
        return True, ""
    m = _TARGETS_RE.search(section)
    if not m:
        return False, "the gate table has no 'Targets in gate: N' line"
    v = m.group(1).strip().lower()
    if v.isdigit() and int(v) < MIN_TARGETS:
        return False, f"'Targets in gate: {v}' is below {MIN_TARGETS}"
    return True, ""


# Step 0e: a prediction (expected measure and size) stated before the result, or `none — <reason>`.
_PREDICTION_RE = re.compile(r"^\W*Prediction:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_PREDICTION_NONE_RE = re.compile(r"^none\b", re.IGNORECASE)
_PREDICTION_NONE_REASON_RE = re.compile(r"^none[ \t]*[—–-][ \t]*\S", re.IGNORECASE)


def prediction_ok(section):
    """Return (ok, problem) for the Score effect section's `Prediction:` line."""
    m = _PREDICTION_RE.search(section or "")
    if not m:
        return False, "it has no 'Prediction:' line"
    value = m.group(1).strip().lstrip("*_` ").strip()
    if not value:
        return False, "its 'Prediction:' line is empty"
    if _PREDICTION_NONE_RE.match(value) and not _PREDICTION_NONE_REASON_RE.match(value):
        return False, "'Prediction: none' needs a reason ('Prediction: none — <reason>')"
    return True, ""


def check(body, changed):
    """Return (ok, message)."""
    hits = relevant_files(changed)
    if not hits:
        return True, "No retrieval/answering/config paths changed; score effect not required."
    section = score_effect_section(body)
    shown = "\n".join(f"  - {f}" for f in hits[:10])
    if section:
        t_ok, t_problem = targets_in_gate_ok(section)
        if not t_ok:
            return False, (
                f"The '## Score effect' gate is not shown to hold enough of the lever's target questions: "
                f"{t_problem}.\n\nAdd 'Targets in gate: N' (N >= {MIN_TARGETS}, or 'all', or "
                "'Targets in gate: none — <reason>'). Count the lever's target construction in the gate "
                "slice, or pick a slice, with scripts/gate_slice.py (B520)."
            )
        if graph_design_ok(section_text(body, "Graph design")):
            p_ok, p_problem = prediction_ok(section)
            if not p_ok:
                return False, (
                    f"The '## Score effect' section states no prediction: {p_problem}.\n\n"
                    "Add a line 'Prediction: <expected measure and size>' written before the run (for example "
                    "'Prediction: query hits +20 to +40 of 809'), or 'Prediction: none — <reason>' when the change "
                    "cannot move a measure. Plan step 0e, learnings/e2e-improvement-plan.md."
                )
            return True, "Score effect (with a prediction) and Graph design sections present."
        return False, (
            f"The '## Graph design' section is missing or empty, but this PR changes retrieval, "
            f"answering, capture or config code:\n{shown}\n\n"
            "Name the edge(s) the change reads or writes and the query that reads them (SPARQL or a "
            "NamedQuery name), or write 'None — <reason>'. "
            "See skills/campy-graph/SKILL.md, \"Design-review checklist\"."
        )
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
