#!/usr/bin/env python3
"""
Drift report: is recent work moving the benchmark score?

Reads `git log` on origin/main (falls back to main/HEAD) for the last N days and
prints a compact Markdown report: commits by kind, commits touching
retrieval/answering paths, recent commits that mention a gate result, and (if
`gh` is installed) open PRs lacking a filled `## Score effect` section.

B521 adds outcome sections: the score trend parsed from merged PRs' `## Score effect`
tables, the docs-only share of commits, graph structure of a store copy (`--store`,
object-linked share is the principle-8 target) and regex call sites added/removed under
campy/brain/thalamus/ (principle 2 watch item). The verdict combines them.

Usage:
    python scripts/drift_report.py [--days 7] [--ref origin/main] [--store PATH]
                                   [--score-threshold 0.01] [--merged-prs-json FILE]
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Keep in sync with .github/scripts/check_pr_score_effect.py (a test enforces it).
RELEVANT_PATHS = (
    "campy/brain/thalamus/",
    "campy/brain/hippocampus/",  # graph store, schema and capture (incl. graph/, observations.py)
    "campy/brain/temporal_lobe/",  # capture: what gets written decides what can be answered
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


DOCS_SHARE_LIMIT = 0.40
SCORE_THRESHOLD = 0.01
_NUM = r"(\d*\.\d+|\d+)"
_SUITE_FAMILIES = (("locomo", "LoCoMo"), ("longmemeval", "LongMemEval"), ("dmr", "DMR"))
_PROSE_RE = re.compile(_NUM + r"\s*(?:→|->|to)\s*" + _NUM)
_GAIN_LOST_RE = re.compile(r"(\d+)\s*gained\s*(?:/|,|and)?\s*(\d+)\s*lost", re.IGNORECASE)
REGEX_USE_RE = re.compile(r"\bre\.(?:compile|search|match|findall|sub|finditer)\(")


def _score_section(body):
    m = re.search(r"^##[ \t]+Score effect[ \t]*$", body or "", re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    rest = (body or "")[m.end():]
    nxt = re.search(r"^#{1,6}[ \t]+\S", rest, re.MULTILINE)
    return re.sub(r"<!--.*?-->", "", rest[: nxt.start()] if nxt else rest, flags=re.DOTALL)


def _num(cell):
    m = re.fullmatch(_NUM, cell.strip().strip("*`"))
    return float(m.group(1)) if m else None


def _int(cell):
    m = re.match(r"\s*(\d+)", cell)
    return int(m.group(1)) if m else None


def _table_rows(lines, context):
    """Rows of one markdown table. The header decides the columns: a baseline column (named
    baseline or main, or holding a number in its title), a branch column (branch or score), and
    gained/lost either as two columns or as one "7 gained / 14 lost" cell."""
    header = [c.strip().lower() for c in lines[0].strip("|").split("|")]

    def col(*names):
        return next((i for i, h in enumerate(header) if any(n in h for n in names)), None)

    i_branch = col("branch", "score")
    i_base = col("baseline", "main")
    i_gain, i_lost = col("gained"), col("lost")
    if i_branch is None:
        return []
    header_base = re.search(r"\d*\.\d+", header[i_base]) if i_base is not None and i_base != i_branch else None
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) <= i_branch or set("".join(cells)) <= set("-: "):
            continue
        base = _num(cells[i_base]) if i_base is not None and i_base < len(cells) and i_base != i_branch else None
        if base is None and header_base:
            base = float(header_base.group(0))
        gained = lost = None
        if i_gain is not None and i_gain < len(cells):
            gl = _GAIN_LOST_RE.search(cells[i_gain])
            gained, lost = (int(gl.group(1)), int(gl.group(2))) if gl else (_int(cells[i_gain]), None)
        if i_lost is not None and i_lost < len(cells):
            lost = _int(cells[i_lost])
        if gained is None and lost is None:
            for c in cells:
                gl = _GAIN_LOST_RE.search(c)
                if gl:
                    gained, lost = int(gl.group(1)), int(gl.group(2))
        suite = cells[0] if suite_family(cells[0]) != cells[0] else f"{cells[0]} ({context})"
        rows.append({"suite": suite, "baseline": base, "branch": _num(cells[i_branch]),
                     "gained": gained, "lost": lost})
    return rows


def parse_score_rows(body):
    """Rows from a PR body's `## Score effect`: dicts suite/baseline/branch/gained/lost.

    Three formats are in use: a table (suite | baseline or main | branch | gained | lost, `-`
    for unknown), a table with a combined cell (run | flags | score | vs main (R88 0.525) with
    "7 gained / 14 lost"), and bullets ("suite: 0.30 -> 0.567, 10 gained / 2 lost"). Rows
    without a branch score are dropped.
    """
    text = _score_section(body)
    family = next((n for k, n in _SUITE_FAMILIES if k in text.lower()), "gate")
    rows, table = [], []
    for line in text.splitlines() + [""]:
        line = line.strip()
        if line.startswith("|"):
            table.append(line)
            continue
        if table:
            rows += _table_rows(table, family)
            table = []
        if line[:1] in ("-", "*") and line[:1]:
            m = _PROSE_RE.search(line)
            if not m:
                continue
            head = line[1:m.start()].strip().rstrip(":").strip()
            gl = _GAIN_LOST_RE.search(line)
            rows.append({"suite": head, "baseline": float(m.group(1)), "branch": float(m.group(2)),
                         "gained": int(gl.group(1)) if gl else None, "lost": int(gl.group(2)) if gl else None})
    return [r for r in rows if r["branch"] is not None]


def suite_family(suite):
    low = suite.lower()
    for key, name in _SUITE_FAMILIES:
        if key in low:
            return name
    return suite


def is_headline(suite):
    """The published metrics (principle 1): LoCoMo cat 1-4, LongMemEval overall, DMR accuracy.
    Slices such as a LongMemEval question type or LoCoMo adversarial are listed, not trended."""
    low = suite.lower()
    fam = suite_family(suite)
    if fam == "LoCoMo":
        return "adversarial" not in low
    if fam == "LongMemEval":
        return "overall" in low
    return fam == "DMR"


def merged_prs(days):
    """Merged PRs in the window (number,title,body,mergedAt), or None without gh."""
    if not shutil.which("gh"):
        return None
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--search", f"merged:>={since}", "--limit", "200",
             "--json", "number,title,body,mergedAt"],
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def score_trend(prs):
    """Per-PR rows (oldest first) and per-suite-family (earliest baseline, latest branch)."""
    per_pr, families = [], {}
    for pr in sorted(prs or [], key=lambda p: p.get("mergedAt") or ""):
        rows = parse_score_rows(pr.get("body") or "")
        if rows:
            per_pr.append({"number": pr["number"], "title": pr.get("title", ""), "rows": rows})
        for r in (r for r in rows if is_headline(r["suite"])):
            fam = families.setdefault(suite_family(r["suite"]), {"first": None, "last": None})
            if fam["first"] is None and r["baseline"] is not None:
                fam["first"] = r["baseline"]
            fam["last"] = r["branch"]
    return per_pr, {k: v for k, v in families.items() if v["first"] is not None and v["last"] is not None}


def score_flat(families, threshold):
    """True when no suite family rose by more than `threshold` over the window."""
    return not any(v["last"] - v["first"] > threshold for v in families.values())


def docs_share(commits):
    return sum(classify(c["files"]) == "docs" for c in commits) / len(commits) if commits else 0.0


def regex_churn(days, ref, cwd=None):
    """(added, removed) regex call sites under campy/brain/thalamus/ in the window."""
    out = run_git(["log", ref, f"--since={days} days ago", "-p", "--format=", "-U0", "--",
                   "campy/brain/thalamus/"], cwd)
    added = sum(1 for l in out.splitlines() if l.startswith("+") and not l.startswith("+++") and REGEX_USE_RE.search(l))
    removed = sum(1 for l in out.splitlines() if l.startswith("-") and not l.startswith("---") and REGEX_USE_RE.search(l))
    return added, removed


_NS = "PREFIX campy: <https://campy.dev/ns#> "
GRAPH_QUERIES = {   # read-only SPARQL, one COUNT each
    "observations": "?x a campy:Observation",
    "with_subject_id": "?x a campy:Observation ; campy:subject_id ?s",
    "with_object_id": "?x a campy:Observation ; campy:object_id ?o",
    "link_preds": '?x a campy:Observation ; campy:predicate ?p . FILTER(?p IN ("owns", "relates_to"))',
    "link_preds_with_object": '?x a campy:Observation ; campy:predicate ?p ; campy:object_id ?o . '
                              'FILTER(?p IN ("owns", "relates_to"))',
}


def graph_structure(store_path):
    """Counts from a read-only open of a store COPY, via graph_structure_report's helpers."""
    import graph_structure_report as gsr

    store = gsr.open_store(store_path)
    return {k: gsr._count(store, f"{_NS}SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {{ {body} }}")
            for k, body in GRAPH_QUERIES.items()}


def _pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


def verdict_for(commits, kinds, gated, flat, docs_high, days=7):
    """drift: score flat AND (docs share high OR no gate results); watch: score flat only."""
    if not commits:
        return "no commits in window"
    if flat is None:   # no merged-PR data (no gh): fall back to the paperwork signals
        if not gated:
            return f"drift risk: no gate result in {days} days (score trend unknown, no gh)"
        return "watch: score trend unknown (no gh)" if docs_high else "ok: score trend unknown (no gh)"
    flat = flat and kinds["code"] > 0
    if flat and (docs_high or not gated):
        return "drift: score flat" + (", docs share high" if docs_high else "") + ("" if gated else ", no gate results")
    if flat:
        return "watch: score flat while code landed"
    return "ok: a suite rose over the window"


def build_report(commits, days, missing_prs=None, merged=None, threshold=SCORE_THRESHOLD,
                 graph=None, regex=None, store_given=False):
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
    share = docs_share(commits)
    docs_high = share > DOCS_SHARE_LIMIT
    lines.append("## Score trend")
    per_pr, families = score_trend(merged)
    if merged is None:
        lines += ["- gh unavailable: score trend unknown", ""]
        flat = None
    else:
        for p in per_pr:
            for r in p["rows"]:
                b = "-" if r["baseline"] is None else f"{r['baseline']:.3f}"
                gl = "" if r["gained"] is None else f", +{r['gained']}/-{r['lost'] if r['lost'] is not None else '?'}"
                tag = "" if is_headline(r["suite"]) else " (slice, not trended)"
                lines.append(f"- #{p['number']} {r['suite']}: {b} -> {r['branch']:.3f}{gl}{tag}")
        if not per_pr:
            lines.append(f"- no merged PR reported a gate table in {days} days")
        for name, v in sorted(families.items()):
            lines.append(f"- **{name}**: earliest baseline {v['first']:.3f} -> latest branch {v['last']:.3f} ({v['last'] - v['first']:+.3f})")
        flat = score_flat(families, threshold)
        lines.append(f"- {'score flat' if flat else 'score rose'} (threshold {threshold})")
        lines.append("")
    lines.append("## Docs share")
    lines.append(f"- docs-only commits: {kinds['docs']}/{len(commits)} = {_pct(kinds['docs'], len(commits))}"
                 + (f" (above {int(DOCS_SHARE_LIMIT * 100)}%)" if docs_high else ""))
    lines.append("")
    lines.append("## Graph structure")
    if graph:
        o = graph["observations"]
        lines.append(f"- Observations: {o}")
        lines.append(f"- with subject_id: {graph['with_subject_id']} ({_pct(graph['with_subject_id'], o)})")
        lines.append(f"- object-linked (object_id): {graph['with_object_id']} ({_pct(graph['with_object_id'], o)})  <- principle-8 target, should go up")
        lines.append(f"- owns/relates_to with an entity object: {graph['link_preds_with_object']}/{graph['link_preds']} ({_pct(graph['link_preds_with_object'], graph['link_preds'])})")
    elif store_given:
        lines.append("- store could not be read")
    else:
        lines.append("- pass --store PATH (a COPY of a store) to report subject/object-linked shares")
    lines.append("")
    if regex is not None:
        lines.append("## Graph computes (watch)")
        lines.append(f"- regex call sites under campy/brain/thalamus/: +{regex[0]} / -{regex[1]} (net {regex[0] - regex[1]:+d}); "
                     "a net rise is Python parsing what the graph should compute")
        lines.append("")
    verdict = verdict_for(commits, kinds, gated, flat, docs_high, days)
    lines.append(f"**Verdict: {verdict}**")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--store", help="a COPY of a store directory, opened read-only, for graph structure")
    ap.add_argument("--score-threshold", type=float, default=SCORE_THRESHOLD,
                    help="minimum rise in a suite's score over the window to call the score not flat")
    ap.add_argument("--merged-prs-json", help="read merged PRs from this JSON file instead of gh")
    args = ap.parse_args(argv)
    ref = resolve_ref(args.ref)
    commits = get_commits(args.days, ref)
    if args.merged_prs_json:
        with open(args.merged_prs_json) as fh:
            merged = json.load(fh)
    else:
        merged = merged_prs(args.days)
    graph = None
    if args.store:
        try:
            graph = graph_structure(args.store)
        except Exception as exc:   # report, do not fail the whole report
            print(f"warning: --store failed: {exc}", file=sys.stderr)
    print(build_report(commits, args.days, open_prs_missing_score_effect(), merged=merged,
                       threshold=args.score_threshold, graph=graph, regex=regex_churn(args.days, ref),
                       store_given=bool(args.store)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
