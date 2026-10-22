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
