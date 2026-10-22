#!/usr/bin/env python3
"""
Drift report: is recent work moving the benchmark score?

Reads `git log` on origin/main (falls back to main/HEAD) for the last N days and
prints a compact Markdown report: commits by kind, commits touching
retrieval/answering paths, recent commits that mention a gate result, and (if
`gh` is installed) open PRs lacking a filled `## Score effect` section.

Usage:
    python scripts/drift_report.py [--days 7] [--ref origin/main]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

# Keep in sync with .github/scripts/check_pr_score_effect.py (a test enforces it).
RELEVANT_PATHS = (
    "campy/brain/thalamus/",
    "campy/brain/hippocampus/graph/",
    "campy/brain/hippocampus/observations.py",
    "campy/brain/llm/",
    "campy/brain/brainstem/config.py",
)

GATE_RE = re.compile(r"\bgained\b|\blost\b|cat(?:egories)?\s*1-4|\bgate\b", re.IGNORECASE)
_COMMIT_MARK = "\x1e"
_FIELD_SEP = "\x1f"


def run_git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def resolve_ref(ref, cwd=None):
    for cand in (ref, "main", "HEAD"):
        try:
            run_git(["rev-parse", "--verify", "--quiet", cand], cwd)
            return cand
        except subprocess.CalledProcessError:
            continue
    return "HEAD"


def get_commits(days, ref, cwd=None):
    fmt = f"{_COMMIT_MARK}%h{_FIELD_SEP}%s{_FIELD_SEP}%b{_FIELD_SEP}"
    out = run_git(["log", ref, f"--since={days} days ago", f"--format={fmt}", "--name-only"], cwd)
    commits = []
    for chunk in out.split(_COMMIT_MARK):
        if not chunk.strip():
            continue
        sha, subject, body, files = (chunk.split(_FIELD_SEP, 3) + [""] * 4)[:4]
        commits.append({
            "sha": sha.strip(),
            "subject": subject.strip(),
            "body": body.strip(),
            "files": [f for f in files.splitlines() if f.strip()],
        })
    return commits


def is_doc_file(path):
    return path.endswith(".md") or path.startswith(("learnings/", "backlog/", "docs/"))


def is_test_file(path):
    return path.startswith("tests/")


def classify(files):
    """Return 'docs', 'tests' or 'code' for a commit's changed files."""
    if not files:
        return "code"
    if all(is_doc_file(f) for f in files):
        return "docs"
    if all(is_test_file(f) or is_doc_file(f) for f in files) and any(is_test_file(f) for f in files):
        return "tests"
    return "code"


def touches_relevant(files):
    return any(f == p or f.startswith(p) for f in files for p in RELEVANT_PATHS)


def mentions_gate(commit):
    return bool(GATE_RE.search(commit["subject"] + "\n" + commit["body"]))


def has_score_effect(body):
    m = re.search(r"^##[ \t]+Score effect[ \t]*$", body or "", re.IGNORECASE | re.MULTILINE)
    if not m:
        return False
    rest = re.sub(r"<!--.*?-->", "", (body or "")[m.end():], flags=re.DOTALL)
    nxt = re.search(r"^#{1,6}[ \t]+\S", rest, re.MULTILINE)
    return bool((rest[: nxt.start()] if nxt else rest).strip())


def open_prs_missing_score_effect():
    if not shutil.which("gh"):
        return None
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,body"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout
        return [pr for pr in json.loads(out) if not has_score_effect(pr.get("body") or "")]
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def build_report(commits, days, missing_prs=None):
    kinds = {"docs": 0, "tests": 0, "code": 0}
    for c in commits:
        kinds[classify(c["files"])] += 1
    relevant = [c for c in commits if touches_relevant(c["files"])]
    gated = [c for c in commits if mentions_gate(c)]
    lines = [f"# Drift report (last {days} days)", ""]
    lines.append(f"- Commits: {len(commits)} (docs-only {kinds['docs']}, tests-only {kinds['tests']}, code {kinds['code']})")
    lines.append(f"- Touching retrieval/answering/config paths: {len(relevant)}")
    lines.append(f"- Mentioning a gate result: {len(gated)}")
    lines.append("")
    if gated:
        lines.append("## Recent gate mentions")
        lines += [f"- {c['sha']} {c['subject']}" for c in gated[:5]]
        lines.append("")
    if missing_prs is not None:
        lines.append("## Open PRs without a filled Score effect")
        lines += [f"- #{p['number']} {p['title']}" for p in missing_prs] or ["- none"]
        lines.append("")
    if not commits:
        verdict = f"no commits in {days} days"
    elif not gated:
        verdict = f"drift risk: no gate result in {days} days"
    elif relevant and kinds["docs"] > kinds["code"] + kinds["tests"]:
        verdict = "watch: mostly docs-only commits"
    else:
        verdict = "ok: gate results are being reported"
    lines.append(f"**Verdict: {verdict}**")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--ref", default="origin/main")
    args = ap.parse_args(argv)
    commits = get_commits(args.days, resolve_ref(args.ref))
    print(build_report(commits, args.days, open_prs_missing_score_effect()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
