"""Tests for scripts/drift_report.py git-parsing helpers."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import drift_report as dr


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo, path, msg):
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(msg)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", msg)


def test_classify_and_relevance():
    assert dr.classify(["learnings/a.md", "backlog/B1.md"]) == "docs"
    assert dr.classify(["tests/test_a.py"]) == "tests"
    assert dr.classify(["campy/x.py", "README.md"]) == "code"
    assert dr.touches_relevant(["campy/brain/llm/provider.py"])
    assert not dr.touches_relevant(["campy/brain/other.py"])


def test_has_score_effect():
    assert dr.has_score_effect("## Score effect\nNone — infra\n")
    assert not dr.has_score_effect("## Score effect\n<!-- x -->\n## Test Plan\n")
    assert not dr.has_score_effect("nothing")


def test_get_commits_from_temp_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "docs/a.md", "docs: note")
    _commit(tmp_path, "campy/brain/thalamus/ask.py", "ask: fix, gained 3 lost 1 on cat 1-4")
    _commit(tmp_path, "tests/test_a.py", "tests: add")
    commits = dr.get_commits(7, "HEAD", cwd=str(tmp_path))
    assert len(commits) == 3
    kinds = sorted(dr.classify(c["files"]) for c in commits)
    assert kinds == ["code", "docs", "tests"]
    assert sum(dr.touches_relevant(c["files"]) for c in commits) == 1
    assert [c["subject"] for c in commits if dr.mentions_gate(c)] == ["ask: fix, gained 3 lost 1 on cat 1-4"]
    report = dr.build_report(commits, 7, [])
    assert "Verdict: ok" in report


def test_verdict_no_gate():
    commits = [{"sha": "a", "subject": "docs", "body": "", "files": ["x.md"]}]
    assert "drift risk: no gate result in 7 days" in dr.build_report(commits, 7)


# --- B521: outcome sections -------------------------------------------------

BODY_TABLE = """## Score effect

| suite | main | branch | gained | lost |
|---|---|---|---|---|
| LongMemEval oracle preference (B501 alone) | 0.30 | 0.567 | 10 | 2 |
| LoCoMo fresh ingest, R96 | 0.525 | 0.517 | 8 | 7 |
| LoCoMo, R93 (SHACL gate) | - | - | 1 | 1 |

Prose after.
## Safety
| a | b | c |
"""

BODY_BULLETS = """## Score effect
- LongMemEval oracle single-session-preference, 30 q (R74 vs R73): 0.30 → 0.567, 10 gained / 2 lost; recall 0.22 → 0.88.
- LoCoMo-10 cat 1-4 T0 replay, pooled (R75): 0.526 → 0.548, 22 gained / 10 lost, up on 3 of 4.

## Part A
"""

BODY_RUNS = """## Score effect
Fresh-ingest LoCoMo-10, conv-30 + conv-44:

| Run | Flags | Score | vs main (R88 0.525) |
|---|---|---|---|
| R95 | walk on | 0.467 | 7 gained / 14 lost |
| R96 | walk off | 0.517 | 7 gained / 8 lost |
"""


def test_parse_table_format():
    rows = dr.parse_score_rows(BODY_TABLE)
    assert [(r["baseline"], r["branch"], r["gained"], r["lost"]) for r in rows] == [
        (0.30, 0.567, 10, 2), (0.525, 0.517, 8, 7)]   # the "-" row has no branch and is dropped


def test_parse_bullet_format():
    rows = dr.parse_score_rows(BODY_BULLETS)
    assert [(r["baseline"], r["branch"], r["gained"], r["lost"]) for r in rows] == [
        (0.30, 0.567, 10, 2), (0.526, 0.548, 22, 10)]


def test_parse_runs_table_takes_baseline_from_header():
    rows = dr.parse_score_rows(BODY_RUNS)
    assert [(r["baseline"], r["branch"], r["gained"], r["lost"]) for r in rows] == [
        (0.525, 0.467, 7, 14), (0.525, 0.517, 7, 8)]
    assert all(dr.suite_family(r["suite"]) == "LoCoMo" for r in rows)


def test_parse_no_section_or_none():
    assert dr.parse_score_rows("nothing") == []
    assert dr.parse_score_rows("## Score effect\nNone — reporting tooling only\n") == []


def _pr(n, at, body):
    return {"number": n, "title": f"pr{n}", "mergedAt": at, "body": body}


def test_trend_flat_and_rising():
    flat = [_pr(1, "2026-10-01", BODY_TABLE), _pr(2, "2026-10-02", BODY_RUNS)]
    _, fams = dr.score_trend(flat)
    assert set(fams) == {"LoCoMo"}                      # the LongMemEval preference slice is not trended
    assert dr.score_flat(fams, 0.01)
    rising = flat + [_pr(3, "2026-10-03", "## Score effect\n- LoCoMo-10 cat 1-4: 0.52 → 0.60, 9 gained / 1 lost\n")]
    assert not dr.score_flat(dr.score_trend(rising)[1], 0.01)


def test_docs_share():
    cs = [{"files": ["a.md"]}, {"files": ["backlog/B1.md"]}, {"files": ["campy/x.py"]}]
    assert abs(dr.docs_share(cs) - 2 / 3) < 1e-9
    assert dr.docs_share([]) == 0.0


KINDS = {"docs": 1, "tests": 0, "code": 3}
C = [{"files": ["x"]}]


def test_verdict_logic():
    assert dr.verdict_for(C, KINDS, gated=[1], flat=True, docs_high=True).startswith("drift")
    assert dr.verdict_for(C, KINDS, gated=[], flat=True, docs_high=False).startswith("drift")
    assert dr.verdict_for(C, KINDS, gated=[1], flat=True, docs_high=False).startswith("watch")
    assert dr.verdict_for(C, KINDS, gated=[], flat=False, docs_high=True).startswith("ok")
    assert dr.verdict_for(C, {"docs": 2, "tests": 0, "code": 0}, [1], True, True).startswith("ok")  # no code landed
    assert dr.verdict_for(C, KINDS, gated=[1], flat=None, docs_high=False).startswith("ok")
    assert dr.verdict_for([], KINDS, [], True, True) == "no commits in window"


def test_regex_churn(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "campy/brain/thalamus/a.py", "import re\nre.compile('x')\n")
    (tmp_path / "campy/brain/thalamus/a.py").write_text("import re\nre.search('y', s)\nre.sub('a', 'b', s)\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "edit")
    assert dr.regex_churn(7, "HEAD", cwd=str(tmp_path)) == (3, 1)


def test_report_sections_without_store_or_gh():
    commits = [{"sha": "a", "subject": "x", "body": "", "files": ["x.md"]}]
    report = dr.build_report(commits, 7, merged=None)
    assert "gh unavailable" in report and "--store" in report
    graph = {"observations": 10, "with_subject_id": 8, "with_object_id": 2, "link_preds": 4, "link_preds_with_object": 1}
    report = dr.build_report(commits, 7, merged=[], graph=graph, regex=(1, 3))
    assert "object-linked (object_id): 2 (20.0%)" in report and "+1 / -3" in report
