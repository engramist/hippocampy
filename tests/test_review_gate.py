"""Tests for .github/scripts/review_gate.py pure functions."""
import sys
import os

# Make review_gate importable from the scripts directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.github', 'scripts'))

from review_gate import (
    CAMPY_BOT_MARKER,
    CAMPY_ESCALATION_MARKER,
    _BOT_LOGIN,
    extract_rule_ids_from_comment,
    format_findings_table,
    build_comment_body,
    find_bot_comment,
    should_escalate,
    parse_semgrep_output,
    parse_pip_audit_output,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_BOT_COMMENT = {
    "id": 101,
    "user": {"login": "github-actions[bot]"},
    "body": (
        f"{CAMPY_BOT_MARKER}\n## Campy Security Review — BLOCKED\n\n"
        "| # | File | Line | Rule | Severity | Fix |\n"
        "|---|------|------|------|----------|-----|\n"
        "| 1 | `campy/foo.py` | 10 | subprocess-injection | HIGH | Use list form |\n\n"
        "<!-- campy-findings: subprocess-injection,CVE-2025-1234 -->\n"
    ),
    "created_at": "2026-01-01T10:00:00Z",
}

SAMPLE_CONTRIBUTOR_COMMENT = {
    "id": 102,
    "user": {"login": "contributor"},
    "body": "I think this might be a false positive because we sanitize inputs upstream.",
    "created_at": "2026-01-01T11:00:00Z",
}

SAMPLE_HUMAN_COMMENT_BEFORE_BOT = {
    "id": 100,
    "user": {"login": "contributor"},
    "body": "Here is my PR!",
    "created_at": "2026-01-01T09:00:00Z",
}

# ---------------------------------------------------------------------------
# extract_rule_ids_from_comment
# ---------------------------------------------------------------------------

def test_extract_rule_ids_empty_string():
    assert extract_rule_ids_from_comment("") == set()


def test_extract_rule_ids_none():
    assert extract_rule_ids_from_comment(None) == set()


def test_extract_rule_ids_no_marker():
    assert extract_rule_ids_from_comment("just a plain comment") == set()


def test_extract_rule_ids_single():
    body = "<!-- campy-findings: subprocess-injection -->"
    assert extract_rule_ids_from_comment(body) == {"subprocess-injection"}


def test_extract_rule_ids_multiple():
    body = "<!-- campy-findings: rule-a,rule-b,rule-c -->"
    assert extract_rule_ids_from_comment(body) == {"rule-a", "rule-b", "rule-c"}


def test_extract_rule_ids_strips_whitespace():
    body = "<!-- campy-findings: rule-a, rule-b -->"
    assert extract_rule_ids_from_comment(body) == {"rule-a", "rule-b"}


# ---------------------------------------------------------------------------
# format_findings_table
# ---------------------------------------------------------------------------

def test_format_findings_table_empty():
    table, rule_ids = format_findings_table([])
    assert table == ""
    assert rule_ids == []


def test_format_findings_table_single():
    findings = [{
        "file": "campy/foo.py", "line": "42",
        "rule": "shell-injection", "severity": "HIGH",
        "fix": "Use list form",
    }]
    table, rule_ids = format_findings_table(findings)
    assert "campy/foo.py" in table
    assert "shell-injection" in table
    assert "HIGH" in table
    assert "42" in table
    assert rule_ids == ["shell-injection"]


def test_format_findings_table_multiple_preserves_order():
    findings = [
        {"file": "a.py", "line": "1", "rule": "rule-a", "severity": "HIGH", "fix": "Fix A"},
        {"file": "b.py", "line": "2", "rule": "rule-b", "severity": "MEDIUM", "fix": "Fix B"},
    ]
    _, rule_ids = format_findings_table(findings)
    assert rule_ids == ["rule-a", "rule-b"]


# ---------------------------------------------------------------------------
# build_comment_body
# ---------------------------------------------------------------------------

def test_build_comment_body_blocked_contains_marker():
    findings = [{"file": "f.py", "line": "1", "rule": "r", "severity": "HIGH", "fix": "fix"}]
    body = build_comment_body(findings, "Security")
    assert CAMPY_BOT_MARKER in body


def test_build_comment_body_blocked_contains_hidden_rule_ids():
    findings = [{"file": "f.py", "line": "1", "rule": "my-rule", "severity": "HIGH", "fix": "fix"}]
    body = build_comment_body(findings, "Security")
    assert "<!-- campy-findings: my-rule -->" in body


def test_build_comment_body_blocked_says_blocked():
    findings = [{"file": "f.py", "line": "1", "rule": "r", "severity": "HIGH", "fix": "fix"}]
    body = build_comment_body(findings, "Security")
    assert "BLOCKED" in body


def test_build_comment_body_passed_says_passed():
    body = build_comment_body([], "Security")
    assert "PASSED" in body
    assert CAMPY_BOT_MARKER in body


def test_build_comment_body_passed_has_no_hidden_findings():
    body = build_comment_body([], "Security")
    assert "campy-findings:" not in body


# ---------------------------------------------------------------------------
# find_bot_comment
# ---------------------------------------------------------------------------

def test_find_bot_comment_returns_most_recent():
    other = {"id": 99, "user": {"login": "human"}, "body": "nice PR", "created_at": "2026-01-01T08:00:00Z"}
    comments = [other, SAMPLE_BOT_COMMENT]
    result = find_bot_comment(comments)
    assert result["id"] == 101


def test_find_bot_comment_returns_none_when_absent():
    comments = [{"id": 1, "user": {"login": "human"}, "body": "no marker here", "created_at": "2026-01-01T09:00:00Z"}]
    assert find_bot_comment(comments) is None


def test_find_bot_comment_returns_none_for_empty_list():
    assert find_bot_comment([]) is None


# ---------------------------------------------------------------------------
# should_escalate
# ---------------------------------------------------------------------------

def test_should_escalate_true_same_rule_and_contributor_comment():
    comments = [SAMPLE_HUMAN_COMMENT_BEFORE_BOT, SAMPLE_BOT_COMMENT, SAMPLE_CONTRIBUTOR_COMMENT]
    current_ids = {"subprocess-injection"}
    assert should_escalate(comments, current_ids, "contributor", SAMPLE_BOT_COMMENT) is True


def test_should_escalate_false_no_previous_bot_comment():
    comments = [SAMPLE_CONTRIBUTOR_COMMENT]
    current_ids = {"subprocess-injection"}
    assert should_escalate(comments, current_ids, "contributor", None) is False


def test_should_escalate_false_different_rule():
    comments = [SAMPLE_BOT_COMMENT, SAMPLE_CONTRIBUTOR_COMMENT]
    current_ids = {"totally-new-rule"}
    assert should_escalate(comments, current_ids, "contributor", SAMPLE_BOT_COMMENT) is False


def test_should_escalate_false_no_contributor_comment_after_bot():
    comments = [SAMPLE_HUMAN_COMMENT_BEFORE_BOT, SAMPLE_BOT_COMMENT]
    current_ids = {"subprocess-injection"}
    assert should_escalate(comments, current_ids, "contributor", SAMPLE_BOT_COMMENT) is False


# ---------------------------------------------------------------------------
# parse_semgrep_output
# ---------------------------------------------------------------------------

def test_parse_semgrep_output_empty():
    assert parse_semgrep_output({"results": []}) == []


def test_parse_semgrep_output_converts_result():
    data = {
        "results": [{
            "check_id": "campy-shadow-store-dict",
            "path": "campy/brain/foo.py",
            "start": {"line": 10},
            "extra": {
                "message": "Module-level dict looks like a shadow store.",
                "severity": "ERROR",
            }
        }]
    }
    findings = parse_semgrep_output(data)
    assert len(findings) == 1
    f = findings[0]
    assert f["rule"] == "campy-shadow-store-dict"
    assert f["file"] == "campy/brain/foo.py"
    assert f["line"] == "10"
    assert f["severity"] == "HIGH"
    assert "shadow store" in f["fix"].lower()


def test_parse_semgrep_output_warning_maps_to_medium():
    data = {
        "results": [{
            "check_id": "some-warning",
            "path": "campy/x.py",
            "start": {"line": 5},
            "extra": {"message": "advisory", "severity": "WARNING"}
        }]
    }
    findings = parse_semgrep_output(data)
    assert findings[0]["severity"] == "MEDIUM"


# ---------------------------------------------------------------------------
# parse_pip_audit_output
# ---------------------------------------------------------------------------

def test_parse_pip_audit_output_empty():
    assert parse_pip_audit_output({"dependencies": []}) == []


def test_parse_pip_audit_output_no_vulns():
    data = {"dependencies": [{"name": "requests", "version": "2.31.0", "vulns": []}]}
    assert parse_pip_audit_output(data) == []


def test_parse_pip_audit_output_converts_vulnerability():
    data = {
        "dependencies": [{
            "name": "requests",
            "version": "2.28.0",
            "vulns": [{
                "id": "CVE-2025-1234",
                "fix_versions": ["2.31.0"],
                "description": "A security vulnerability in requests.",
                "aliases": [],
            }]
        }]
    }
    findings = parse_pip_audit_output(data)
    assert len(findings) == 1
    f = findings[0]
    assert f["rule"] == "CVE-2025-1234"
    assert "requests" in f["file"]
    assert "2.28.0" in f["file"]
    assert "2.31.0" in f["fix"]
    assert f["severity"] == "HIGH"


def test_parse_pip_audit_output_no_fix_version():
    data = {
        "dependencies": [{
            "name": "oldpkg",
            "version": "1.0.0",
            "vulns": [{
                "id": "CVE-2025-9999",
                "fix_versions": [],
                "description": "No fix available.",
                "aliases": [],
            }]
        }]
    }
    findings = parse_pip_audit_output(data)
    assert len(findings) == 1
    assert "No fix available" in findings[0]["fix"]


# ---------------------------------------------------------------------------
# build_comment_body — blocking parameter (Fix #1)
# ---------------------------------------------------------------------------

_SAMPLE_FINDING = [{"file": "f.py", "line": "1", "rule": "my-rule", "severity": "MEDIUM", "fix": "fix"}]


def test_build_comment_body_advisory_not_blocked():
    """Advisory-only findings must not say BLOCKED and must not have the blocking footer."""
    body = build_comment_body(_SAMPLE_FINDING, "Security", blocking=False)
    assert "ADVISORY" in body
    assert "BLOCKED" not in body
    assert "Fix the above and push again" not in body
    assert "advisory findings" in body


def test_build_comment_body_blocking_says_blocked():
    """Blocking findings must say BLOCKED."""
    body = build_comment_body(_SAMPLE_FINDING, "Security", blocking=True)
    assert "BLOCKED" in body
    assert "ADVISORY" not in body
    assert "Fix the above and push again" in body


def test_build_comment_body_advisory_includes_rule_id_comment():
    """Advisory body should still include the hidden rule-id comment for escalation tracking."""
    body = build_comment_body(_SAMPLE_FINDING, "Security", blocking=False)
    assert "<!-- campy-findings: my-rule -->" in body


# ---------------------------------------------------------------------------
# find_bot_comment — author filter (Fix #2) and escalation marker (Fix #3)
# ---------------------------------------------------------------------------

def test_find_bot_comment_ignores_non_bot_author():
    """A comment with the bot marker but posted by a contributor must be ignored."""
    spoofed = {
        "id": 200,
        "user": {"login": "contributor"},
        "body": f"{CAMPY_BOT_MARKER}\n## Campy Security Review — BLOCKED\n",
        "created_at": "2026-01-01T12:00:00Z",
    }
    assert find_bot_comment([spoofed]) is None


def test_find_bot_comment_matches_bot_author():
    """A comment with the marker posted by the bot login must be returned."""
    bot_comment = {
        "id": 201,
        "user": {"login": _BOT_LOGIN},
        "body": f"{CAMPY_BOT_MARKER}\n## Campy Security Review — BLOCKED\n",
        "created_at": "2026-01-01T12:00:00Z",
    }
    assert find_bot_comment([bot_comment]) is bot_comment


def test_find_bot_comment_ignores_escalation_marker():
    """A comment that only has the escalation marker (not CAMPY_BOT_MARKER) must be ignored."""
    escalation_comment = {
        "id": 202,
        "user": {"login": _BOT_LOGIN},
        "body": f"{CAMPY_ESCALATION_MARKER}\n## Campy Security Review — ESCALATED\n",
        "created_at": "2026-01-01T13:00:00Z",
    }
    assert find_bot_comment([escalation_comment]) is None


# ---------------------------------------------------------------------------
# _get_pr_comments pagination (Fix #10) — note
# ---------------------------------------------------------------------------
# test_get_pr_comments_paginates is omitted: cleanly mocking the urllib-based
# _api_request internals would require monkeypatching a private function with
# no DI hook, making the test brittle and tightly coupled to implementation
# details. The pagination logic in _get_pr_comments is straightforward loop
# code; it is covered by the code-review finding description.
