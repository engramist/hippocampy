# B291 — OSS Release & Agent PR Review Pipeline Implementation Plan

> **Update (2026-06-28):** Phase 2 (the AI ecosystem reviewer) now uses **GitHub Copilot code
> review**, not Codex. Codex would require a separate paid OpenAI subscription the maintainer
> doesn't have; Copilot ships with the maintainer's existing plan. The ecosystem checklist lives
> in `.github/copilot-instructions.md` (and mirrored in `AGENTS.md`). References to "Codex" below
> are historical — see the updated spec for the current design. Task 5 (the AGENTS.md checklist)
> still applies as written; the same content was also added to `.github/copilot-instructions.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-gate automated PR review pipeline (security + ecosystem) to the hippocampy OSS repo, with structured findings, escalation on repeat failures, and OSS release hygiene files.

**Architecture:** Phase 1 (GitHub Actions) runs CodeQL + Semgrep + pip-audit on every PR push and posts structured findings via `review_gate.py`. Phase 2 (Codex GitHub App, configured via AGENTS.md) reviews ecosystem placement after Phase 1 passes. Phase 3 is maintainer-triggered via `/code-review ultra`. OSS hygiene files (LICENSE, CODEOWNERS, CONTRIBUTING.md, PR template) gate the public release.

**Tech Stack:** GitHub Actions, CodeQL (github/codeql-action), Semgrep OSS, pip-audit, Python 3.11 (stdlib only — no third-party deps in scripts), GitHub REST API v2022-11-28.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `LICENSE` | Create | MIT license text |
| `CODEOWNERS` | Create | `* @engramist` — only maintainer can merge |
| `CONTRIBUTING.md` | Create | Contributor guide explaining three-gate pipeline |
| `.github/PULL_REQUEST_TEMPLATE.md` | Create | PR checklist for contributors |
| `.semgrep/campy-no-shadow-stores.yaml` | Create | Semgrep rule: detect module-level shadow stores in `campy/` |
| `.semgrep/tests/campy-no-shadow-stores.py` | Create | Semgrep `--test` fixtures (ok + ruleid annotations) |
| `.github/scripts/review_gate.py` | Create | Parse Semgrep + pip-audit JSON, post/replace PR comment, handle escalation |
| `tests/test_review_gate.py` | Create | Unit tests for all pure functions in review_gate.py |
| `.github/workflows/security-gate.yml` | Create | Orchestrates CodeQL + Semgrep + pip-audit jobs |
| `.github/codeql/codeql-config.yml` | Create | CodeQL Python query suite, excludes test fixtures |
| `AGENTS.md` | Modify (append) | Add `## PR Review Checklist` section for Codex ecosystem gate |

---

## Task 1: OSS Release Hygiene Files

**Files:**
- Create: `LICENSE`
- Create: `CODEOWNERS`
- Create: `CONTRIBUTING.md`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

No unit tests for these — they are content files verified by inspection.

- [ ] **Step 1: Create LICENSE**

Create `LICENSE` at the repo root:

```
MIT License

Copyright (c) 2026 engramist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Create CODEOWNERS**

Create `CODEOWNERS` at the repo root:

```
# All files require review from the maintainer.
* @engramist
```

- [ ] **Step 3: Create CONTRIBUTING.md**

Create `CONTRIBUTING.md` at the repo root:

```markdown
# Contributing to HippoCampy

Thank you for your interest in contributing!

## Before You Start

Read [`docs/ecosystem-rules.md`](docs/ecosystem-rules.md) — it defines the layer boundaries
every contributor must follow. The automated review pipeline enforces these rules on every PR.

## The Three-Gate Pipeline

Every PR goes through three gates before it can be merged:

### Gate 1 — Security (automatic, runs on push)

GitHub Actions runs:
- **CodeQL** — detects injection, path traversal, unsafe subprocess use
- **Semgrep** — detects Campy-specific anti-patterns (shadow stores, etc.) + Python security rules
- **pip-audit** — scans for CVEs in Python dependencies

If any HIGH/CRITICAL finding is detected, the PR is blocked and a bot comment lists the findings
with specific fix instructions. Fix the issues and push — the gate re-runs automatically.

### Gate 2 — Ecosystem Alignment (automatic, Codex review)

After Gate 1 passes, Codex reviews the PR for ecosystem compliance:
- Code goes in the right directory per `docs/ecosystem-rules.md`
- No shadow stores (persistent state must go through KuzuDB)
- New MCP tools are registered in `TOOL_HANDLERS`
- Schema changes include a migration entry

### Gate 3 — Deep Review (maintainer-triggered before merge)

The maintainer runs `/code-review ultra` for a final multi-agent review before approving.

## Running the Security Check Locally

```bash
pip install semgrep pip-audit
semgrep --config .semgrep/ campy/
pip-audit -r requirements.txt
```

## Commit Style

Follow the existing commit message style: `type(scope): description`
Examples: `feat(thalamus): add work_summary tool`, `fix(schema): add migration for WorkArtifact`
```

- [ ] **Step 4: Create PR template**

Create `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Description

<!-- What does this PR do? Why? -->

## Test Plan

<!-- How did you verify this works? -->

## Checklist

- [ ] I ran the existing test suite: `pytest tests/ -q`
- [ ] No new module-level dicts/lists in `campy/` used as persistent stores (use KuzuDB)
- [ ] New code is in the right directory per `docs/ecosystem-rules.md`
- [ ] New MCP tools are added to `TOOL_HANDLERS` in `campy/brain/thalamus/tools/__init__.py`
- [ ] Schema changes include an entry in the `_MIGRATIONS` list inside `init_schema()` in `campy/brain/hippocampus/schema.py`
```

- [ ] **Step 5: Verify files exist**

```bash
ls LICENSE CODEOWNERS CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md
```

Expected: all four files listed with no errors.

- [ ] **Step 6: Commit**

```bash
git add LICENSE CODEOWNERS CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md
git commit -m "feat(oss): add OSS release hygiene files — LICENSE, CODEOWNERS, CONTRIBUTING, PR template"
```

---

## Task 2: Campy Semgrep Shadow Store Rule

**Files:**
- Create: `.semgrep/campy-no-shadow-stores.yaml`
- Create: `.semgrep/tests/campy-no-shadow-stores.py`

- [ ] **Step 1: Create the Semgrep rule**

Create `.semgrep/campy-no-shadow-stores.yaml`:

```yaml
rules:
  - id: campy-shadow-store-dict
    patterns:
      - pattern-either:
          - pattern: $NAME = {}
          - pattern: $NAME = dict()
          - pattern: $NAME: $TYPE = {}
          - pattern: $NAME: $TYPE = dict()
      - pattern-not-inside: |
          def $FUNC(...):
            ...
      - pattern-not-inside: |
          class $CLASS:
            ...
      - pattern-not-inside: |
          if ...:
            ...
      - metavariable-regex:
          metavariable: $NAME
          regex: "^_?(store|cache|state|registry|db).*"
    message: >
      Module-level dict `$NAME` looks like a shadow store.
      Persistent state must go through KuzuDB. See docs/ecosystem-rules.md "No Shadow Stores rule."
    severity: ERROR
    languages: [python]
    paths:
      include:
        - "campy/**"

  - id: campy-shadow-store-list
    patterns:
      - pattern-either:
          - pattern: $NAME = []
          - pattern: $NAME = list()
          - pattern: $NAME: $TYPE = []
          - pattern: $NAME: $TYPE = list()
      - pattern-not-inside: |
          def $FUNC(...):
            ...
      - pattern-not-inside: |
          class $CLASS:
            ...
      - pattern-not-inside: |
          if ...:
            ...
      - metavariable-regex:
          metavariable: $NAME
          regex: "^_?(store|cache|state|registry|db).*"
    message: >
      Module-level list `$NAME` looks like a shadow store.
      Persistent state must go through KuzuDB. See docs/ecosystem-rules.md "No Shadow Stores rule."
    severity: ERROR
    languages: [python]
    paths:
      include:
        - "campy/**"
```

- [ ] **Step 2: Create Semgrep test fixtures**

Create `.semgrep/tests/campy-no-shadow-stores.py`:

```python
# Test fixtures for campy-no-shadow-stores Semgrep rules.
# ok: lines are clean (should NOT be flagged).
# ruleid: lines should BE flagged by the named rule.

# ok: campy-shadow-store-dict
LOCAL_LOOKUP = {}  # name doesn't match pattern — should not flag


# ruleid: campy-shadow-store-dict
_store = {}

# ruleid: campy-shadow-store-dict
_cache = {}

# ruleid: campy-shadow-store-dict
_cache: dict = {}

# ruleid: campy-shadow-store-dict
_store = dict()

# ruleid: campy-shadow-store-list
_registry = []

# ruleid: campy-shadow-store-list
_state = []

# ruleid: campy-shadow-store-list
_registry: list = []

# ruleid: campy-shadow-store-list
_state = list()


def function_with_local():
    # ok: campy-shadow-store-dict
    local_cache = {}  # inside a function — should not flag
    # ok: campy-shadow-store-list
    local_store = []  # inside a function — should not flag
    return local_cache, local_store


class MyClass:
    # ok: campy-shadow-store-dict
    class_cache = {}  # inside a class — should not flag
```

- [ ] **Step 3: Run Semgrep rule tests (if Semgrep is available)**

If Semgrep is not installed, install it first: `pip install semgrep`. If network access is not available, skip this step and verify rule correctness by inspection.

```bash
semgrep --test .semgrep/
```

Expected output:
```
1 test passed (campy-no-shadow-stores)
0 tests failed
```

If any test fails, the fixture annotations or rule patterns need adjustment. Check that `ruleid:` comments are on the line immediately before the flagged code and `ok:` comments are on the same line as the clean code.

- [ ] **Step 4: Run rule against the actual codebase**

```bash
semgrep --config .semgrep/ campy/
```

Inspect any findings. If legitimate shadow stores exist in the current codebase, they should be fixed before this PR pipeline goes live — or the rule should be narrowed (e.g., exclude specific known-safe patterns with `pattern-not:`).

- [ ] **Step 5: Commit**

```bash
git add .semgrep/
git commit -m "feat(oss): add Semgrep shadow store detection rule for campy/"
```

---

## Task 3: Review Gate Script (TDD)

**Files:**
- Create: `tests/test_review_gate.py`
- Create: `.github/scripts/review_gate.py`

This script is called by the GitHub Actions workflow. It parses Semgrep + pip-audit JSON output,
posts or replaces the bot PR comment with a structured findings table, and handles escalation
when the same rule fires twice with a contributor comment in between.

It uses only Python stdlib (no `requests`, no `httpx`) — the Actions runner has Python 3.11
available. All GitHub API calls use `urllib.request`.

- [ ] **Step 1: Create the test file**

Create `tests/test_review_gate.py`:

```python
"""Tests for .github/scripts/review_gate.py pure functions."""
import sys
import os
import pytest

# Make review_gate importable from the scripts directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.github', 'scripts'))

from review_gate import (
    CAMPY_BOT_MARKER,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_review_gate.py -v
```

Expected: `ImportError: No module named 'review_gate'` — the script doesn't exist yet.

- [ ] **Step 3: Create `.github/scripts/` directory**

```bash
mkdir -p .github/scripts
```

- [ ] **Step 4: Create `review_gate.py`**

Create `.github/scripts/review_gate.py`:

```python
#!/usr/bin/env python3
"""
Security gate review script for hippocampy OSS.

Parses Semgrep and pip-audit JSON output, posts a structured findings table
as a PR comment (replacing the previous bot comment), and handles escalation
when the same rule fires on a re-push after a contributor comment.

Usage (called by .github/workflows/security-gate.yml):
    python review_gate.py --semgrep semgrep-results.json \
                          --pip-audit pip-audit-results.json \
                          --phase Security
    
Environment variables required at runtime (not for tests):
    GITHUB_TOKEN        — GitHub Actions token with pull-requests:write
    GITHUB_REPOSITORY   — e.g. "hippocampy/hippocampy"
    PR_NUMBER           — PR number as a string

Exit codes:
    0 — no blocking findings
    1 — blocking findings found (fails the Actions check)
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

CAMPY_BOT_MARKER = "<!-- campy-security-findings -->"
_SEVERITY_MAP = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
_ESCALATION_MENTION = "@engramist"


# ---------------------------------------------------------------------------
# Pure functions (all testable without mocks)
# ---------------------------------------------------------------------------

def extract_rule_ids_from_comment(body):
    """Return set of rule IDs embedded in a previous bot comment, or empty set."""
    if not body:
        return set()
    m = re.search(r"<!-- campy-findings: ([^>]+?) -->", body)
    if not m:
        return set()
    return {r.strip() for r in m.group(1).split(",") if r.strip()}


def format_findings_table(findings):
    """Return (markdown_table_str, rule_ids_list). Empty input → ('', [])."""
    if not findings:
        return "", []
    header = (
        "| # | File | Line | Rule | Severity | Fix |\n"
        "|---|------|------|------|----------|-----|"
    )
    rows = []
    rule_ids = []
    for i, f in enumerate(findings, 1):
        rows.append(
            f"| {i} | `{f['file']}` | {f.get('line', '-')} "
            f"| {f['rule']} | {f['severity']} | {f['fix']} |"
        )
        rule_ids.append(f["rule"])
    return header + "\n" + "\n".join(rows), rule_ids


def build_comment_body(findings, phase):
    """Build the full PR comment body, including hidden rule IDs for escalation."""
    table, rule_ids = format_findings_table(findings)
    status = "BLOCKED" if findings else "PASSED"
    parts = [
        CAMPY_BOT_MARKER,
        f"## Campy {phase} Review — {status}",
        "",
    ]
    if findings:
        parts += [
            table,
            "",
            f"<!-- campy-findings: {','.join(rule_ids)} -->",
            "",
            f"**Fix the above and push again. The {phase.lower()} gate re-runs automatically.**",
        ]
    else:
        parts.append("All checks passed. ✓")
    return "\n".join(parts)


def find_bot_comment(comments):
    """Return the most recent bot findings comment dict, or None."""
    for c in reversed(comments):
        if CAMPY_BOT_MARKER in c.get("body", ""):
            return c
    return None


def should_escalate(comments, current_rule_ids, pr_author, previous_bot_comment):
    """
    Return True when:
    - previous_bot_comment is not None
    - at least one rule ID overlaps between previous and current findings
    - the PR author posted a comment after the previous bot comment
    """
    if not previous_bot_comment:
        return False
    old_ids = extract_rule_ids_from_comment(previous_bot_comment.get("body", ""))
    if not old_ids.intersection(current_rule_ids):
        return False
    bot_ts = datetime.fromisoformat(
        previous_bot_comment["created_at"].replace("Z", "+00:00")
    )
    return any(
        c["user"]["login"] == pr_author
        and datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")) > bot_ts
        for c in comments
    )


def parse_semgrep_output(data):
    """Convert Semgrep JSON dict to unified findings list."""
    findings = []
    for result in data.get("results", []):
        sev_raw = result.get("extra", {}).get("severity", "WARNING")
        findings.append({
            "file": result.get("path", "unknown"),
            "line": str(result.get("start", {}).get("line", "-")),
            "rule": result.get("check_id", "unknown"),
            "severity": _SEVERITY_MAP.get(sev_raw, "MEDIUM"),
            "fix": result.get("extra", {}).get("message", "See rule documentation")[:100],
        })
    return findings


def parse_pip_audit_output(data):
    """Convert pip-audit JSON dict to unified findings list."""
    findings = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fixes = vuln.get("fix_versions", [])
            fix_str = (
                f"Upgrade to {dep['name']}>={fixes[0]}"
                if fixes
                else "No fix available yet — consider removing this dependency"
            )
            findings.append({
                "file": f"dependency: {dep['name']}=={dep['version']}",
                "line": "-",
                "rule": vuln.get("id", "unknown-cve"),
                "severity": "HIGH",
                "fix": fix_str,
            })
    return findings


# ---------------------------------------------------------------------------
# GitHub API helpers (side effects — not unit tested)
# ---------------------------------------------------------------------------

def _github_headers():
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _api_request(method, url, data=None):
    headers = _github_headers()
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"GitHub API {method} {url}: {e.code} {e.read().decode()}"
        ) from e


def _get_pr_comments(repo, pr_number):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    return _api_request("GET", url)


def _get_pr_author(repo, pr_number):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    return _api_request("GET", url)["user"]["login"]


def _post_or_replace_comment(repo, pr_number, body, previous_bot_comment):
    if previous_bot_comment:
        cid = previous_bot_comment["id"]
        url = f"https://api.github.com/repos/{repo}/issues/comments/{cid}"
        _api_request("PATCH", url, {"body": body})
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        _api_request("POST", url, {"body": body})


def _add_label(repo, pr_number, label):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
    _api_request("POST", url, {"labels": [label]})


def _post_escalation_comment(repo, pr_number, overlapping_ids):
    rule_str = ", ".join(f"`{r}`" for r in sorted(overlapping_ids))
    body = (
        f"{CAMPY_BOT_MARKER}\n"
        f"## Campy Security Review — ESCALATED\n\n"
        f"This PR has the same finding(s) ({rule_str}) after a re-push and a contributor "
        f"comment. Pinging {_ESCALATION_MENTION} for manual review.\n\n"
        f"A maintainer will determine whether this is a false positive."
    )
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    _api_request("POST", url, {"body": body})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Campy OSS security gate review script.")
    parser.add_argument("--semgrep", default="semgrep-results.json",
                        help="Path to Semgrep JSON output file")
    parser.add_argument("--pip-audit", default="pip-audit-results.json",
                        help="Path to pip-audit JSON output file")
    parser.add_argument("--phase", default="Security",
                        help="Gate phase label for the PR comment header")
    args = parser.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]

    # Collect findings from each tool
    all_findings = []
    for path, parser_fn in [
        (args.semgrep, parse_semgrep_output),
        (args.pip_audit, parse_pip_audit_output),
    ]:
        if os.path.exists(path):
            with open(path) as fh:
                all_findings.extend(parser_fn(json.load(fh)))

    # Split into blocking (HIGH/CRITICAL) and advisory
    blocking = [f for f in all_findings if f["severity"] in ("HIGH", "CRITICAL")]
    advisory = [f for f in all_findings if f["severity"] not in ("HIGH", "CRITICAL")]

    # Get existing PR comments before we post (escalation needs the old bot comment)
    comments = _get_pr_comments(repo, pr_number)
    previous_bot_comment = find_bot_comment(comments)

    # Post or replace the findings comment
    display_findings = blocking if blocking else advisory[:3]
    body = build_comment_body(display_findings, args.phase)
    _post_or_replace_comment(repo, pr_number, body, previous_bot_comment)

    # Handle escalation on repeat failures
    if blocking:
        current_rule_ids = {f["rule"] for f in blocking}
        pr_author = _get_pr_author(repo, pr_number)
        if should_escalate(comments, current_rule_ids, pr_author, previous_bot_comment):
            old_ids = extract_rule_ids_from_comment(
                previous_bot_comment.get("body", "") if previous_bot_comment else ""
            )
            overlapping = current_rule_ids.intersection(old_ids)
            _add_label(repo, pr_number, "needs-human-review")
            _post_escalation_comment(repo, pr_number, overlapping)
            print(f"Escalated: same finding(s) on re-push — {overlapping}")

        print(f"BLOCKED: {len(blocking)} blocking finding(s), {len(advisory)} advisory")
        sys.exit(1)

    print(f"PASSED: 0 blocking findings, {len(advisory)} advisory")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_review_gate.py -v
```

Expected: all tests pass. If any fail, fix `review_gate.py` until they do.

- [ ] **Step 6: Commit**

```bash
git add .github/scripts/review_gate.py tests/test_review_gate.py
git commit -m "feat(oss): add review_gate.py with security findings + escalation logic"
```

---

## Task 4: GitHub Actions Security Gate Workflow

**Files:**
- Create: `.github/workflows/security-gate.yml`
- Create: `.github/codeql/codeql-config.yml`

- [ ] **Step 1: Create CodeQL config**

Create `.github/codeql/codeql-config.yml`:

```yaml
name: "Campy CodeQL Config"

queries:
  - uses: security-and-quality

paths-ignore:
  - "tests/"
  - "**/*.md"
  - ".venv/"
  - "benchmarks/arc3/fixtures/"
  - "**/__pycache__/"
```

- [ ] **Step 2: Create the security gate workflow**

Create `.github/workflows/security-gate.yml`:

```yaml
name: Security Gate

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  issues: write
  security-events: write

jobs:
  # -------------------------------------------------------------------------
  # Job 1: CodeQL — static security analysis
  # Reports findings to the GitHub Security tab (not to the structured PR
  # comment — that is Semgrep/pip-audit only). To block PRs on CodeQL alerts,
  # configure branch protection → Code Scanning → alert severity "Error"
  # in repo Settings → Code security → Protection rules.
  # -------------------------------------------------------------------------
  codeql:
    name: CodeQL
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: python
          config-file: .github/codeql/codeql-config.yml

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3

  # -------------------------------------------------------------------------
  # Job 2: Semgrep + pip-audit — pattern checks + dependency CVEs
  # Parses output and posts a structured findings table on the PR.
  # -------------------------------------------------------------------------
  semgrep-pip:
    name: Semgrep + pip-audit
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install review tools
        run: pip install semgrep pip-audit

      - name: Run Semgrep
        # || true: let review_gate.py be the gate, not the Semgrep exit code
        run: |
          semgrep \
            --json \
            --config .semgrep/ \
            --config "p/python" \
            --output semgrep-results.json \
            campy/ || true

      - name: Install package dependencies
        # Install the package so pip-audit covers pyproject.toml deps too.
        # Fall back gracefully if the package isn't directly installable.
        run: pip install -e . --quiet 2>/dev/null || true

      - name: Run pip-audit
        # Audits the full installed environment (covers both requirements.txt
        # and pyproject.toml). || true: let review_gate.py be the gate.
        run: |
          pip-audit \
            --format json \
            --output pip-audit-results.json || true

      - name: Post findings and gate
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          python .github/scripts/review_gate.py \
            --semgrep semgrep-results.json \
            --pip-audit pip-audit-results.json \
            --phase Security
```

- [ ] **Step 3: Validate workflow YAML syntax (if yamllint is available)**

If yamllint is not installed and network access is available: `pip install yamllint`. If network access is not available, skip this step and verify YAML by visual inspection.

```bash
yamllint .github/workflows/security-gate.yml
```

Expected: no errors. If yamllint flags indentation issues, fix them.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/security-gate.yml .github/codeql/codeql-config.yml
git commit -m "feat(oss): add GitHub Actions security gate workflow (CodeQL + Semgrep + pip-audit)"
```

---

## Task 5: AGENTS.md Ecosystem Gate Section

**Files:**
- Modify: `AGENTS.md` (append new section at end of file)

This section tells Codex what to check when it reviews a PR. It is the configuration for the Phase 2 ecosystem gate — no code required.

- [ ] **Step 1: Append the PR Review Checklist section**

Open `AGENTS.md` and append the following at the very end of the file (after the Activity Indicator section):

```markdown

## PR Review Checklist (Codex Ecosystem Gate)

When reviewing a pull request, check each rule below. Post findings in this exact table format:

| File | Line | Rule | Severity | Fix |
|------|------|------|----------|-----|

**Rules:**

**1. Layer placement** — new code must go in the correct directory per `docs/ecosystem-rules.md`.
- Flag: any file under `campy/` that imports from `agents/` or `benchmarks/`
- Flag: any file under `agents/` or `benchmarks/` that imports from `campy/`
- Flag: new files placed in the wrong top-level directory for their responsibility

**2. No shadow stores** — persistent agent state must go through KuzuDB, not in-memory structures.
- Flag: module-level `dict` or `list` in `campy/` whose name contains `store`, `cache`, `state`, `registry`, or `db`
- In-memory caches backed by KuzuDB reads are permitted; standalone in-memory state is not

**3. Tool registration** — every new MCP tool must be registered.
- Flag: a new function in `campy/brain/thalamus/tools/__init__.py` matching `*_tool` or `handle_*`
  that does not appear in the `TOOL_HANDLERS` dict in the same file

**4. Schema migrations** — schema additions need a migration entry.
- Flag: additions to `NODE_TABLES` or `REL_TABLES` in `campy/brain/hippocampus/schema.py`
  (both are module-level, no underscore prefix) that have no corresponding entry added to
  the `_MIGRATIONS` list inside the `init_schema()` function in the same file

**Decision:**
- If all rules pass: approve the PR.
- If any rule fails: request changes with the findings table above. Do not approve until fixed.
```

- [ ] **Step 2: Verify the section was appended correctly**

```bash
tail -40 AGENTS.md
```

Expected: the PR Review Checklist section appears at the end with correct markdown formatting.

- [ ] **Step 3: Run existing tests to confirm no regressions**

```bash
pytest tests/ -q --ignore=tests/test_ab_reproducibility.py -x
```

Expected: same number of tests pass as before this task. `AGENTS.md` changes have no effect on Python tests.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "feat(oss): add Codex PR ecosystem gate checklist to AGENTS.md"
```

---

## Self-Review (for the implementer)

After all tasks are complete, verify against the spec:

```bash
# All files exist
ls LICENSE CODEOWNERS CONTRIBUTING.md \
   .github/PULL_REQUEST_TEMPLATE.md \
   .semgrep/campy-no-shadow-stores.yaml \
   .semgrep/tests/campy-no-shadow-stores.py \
   .github/scripts/review_gate.py \
   .github/workflows/security-gate.yml \
   .github/codeql/codeql-config.yml

# Tests pass
pytest tests/test_review_gate.py -v

# Semgrep rule tests pass
semgrep --test .semgrep/

# No new Python import errors
python -c "import sys; sys.path.insert(0, '.github/scripts'); import review_gate"
```
