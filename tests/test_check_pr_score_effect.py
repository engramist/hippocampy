"""Tests for .github/scripts/check_pr_score_effect.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"))

from check_pr_score_effect import RELEVANT_PATHS, check

RELEVANT = ["campy/brain/thalamus/ask.py", "README.md"]
IRRELEVANT = ["README.md", "docs/x.md", "tests/test_a.py"]
TEMPLATE_ONLY = (
    "## Description\nx\n\n## Score effect\n\n"
    "<!-- Gate table (suite | main | branch | gained | lost), or \"None — <reason>\". -->\n\n"
    "## Test Plan\nfoo\n"
)


def test_no_relevant_paths_passes_without_section():
    assert check("no sections here", IRRELEVANT)[0]


def test_relevant_with_filled_section_passes():
    body = "## Score effect\n\n| suite | main | branch | gained | lost |\n|---|---|---|---|---|\n| LoCoMo | 60 | 62 | 3 | 1 |\n\n## Test Plan\n"
    assert check(body, RELEVANT)[0]


def test_relevant_with_none_reason_passes():
    assert check("## Score effect\nNone — docs only\n", RELEVANT)[0]


def test_relevant_missing_section_fails():
    ok, msg = check("## Description\nstuff\n", RELEVANT)
    assert not ok and "Score effect" in msg and "thalamus" in msg


def test_relevant_template_comment_only_fails():
    assert not check(TEMPLATE_ONLY, RELEVANT)[0]


def test_empty_body_fails_and_none_body_ok():
    assert not check(None, RELEVANT)[0]
    assert check(None, IRRELEVANT)[0]


def test_drift_report_paths_in_sync():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import drift_report
    assert drift_report.RELEVANT_PATHS == RELEVANT_PATHS
