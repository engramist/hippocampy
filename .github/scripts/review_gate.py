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
CAMPY_ESCALATION_MARKER = "<!-- campy-security-escalation -->"
_BOT_LOGIN = "github-actions[bot]"
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


def build_comment_body(findings, phase, blocking=True):
    """Build the full PR comment body, including hidden rule IDs for escalation.

    Args:
        findings: list of finding dicts (may be empty).
        phase: gate phase label shown in the comment header.
        blocking: True  → findings are blocking (status BLOCKED, "fix and push again" footer).
                  False → findings are advisory (status ADVISORY when non-empty, gentle footer).
                  Ignored when findings is empty; empty always yields PASSED.
    """
    table, rule_ids = format_findings_table(findings)
    if not findings:
        status = "PASSED"
    elif blocking:
        status = "BLOCKED"
    else:
        status = "ADVISORY"
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
        ]
        if blocking:
            parts.append(
                f"**Fix the above and push again. The {phase.lower()} gate re-runs automatically.**"
            )
        else:
            parts.append(
                "**These are advisory findings (MEDIUM/LOW). They do not block this PR.**"
            )
    else:
        parts.append("All checks passed. ✓")
    return "\n".join(parts)


def find_bot_comment(comments):
    """Return the most recent bot findings comment dict, or None.

    Only considers comments posted by _BOT_LOGIN to prevent marker spoofing or
    accidental PATCH of a contributor's comment.
    """
    for c in reversed(comments):
        if (
            CAMPY_BOT_MARKER in c.get("body", "")
            and c.get("user", {}).get("login") == _BOT_LOGIN
        ):
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
    comments = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}"
        batch = _api_request("GET", url)
        if not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


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
    # Ensure the label exists (ignore "already exists" errors), then attach it.
    try:
        _api_request("POST", f"https://api.github.com/repos/{repo}/labels",
                     {"name": label, "color": "B60205",
                      "description": "Flagged by the Campy security gate for maintainer review"})
    except Exception:
        pass  # label probably already exists
    try:
        _api_request("POST", f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels",
                     {"labels": [label]})
    except Exception:
        pass  # never let labeling break escalation


def _post_escalation_comment(repo, pr_number, overlapping_ids):
    rule_str = ", ".join(f"`{r}`" for r in sorted(overlapping_ids))
    body = (
        f"{CAMPY_ESCALATION_MARKER}\n"
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
    if blocking:
        body = build_comment_body(blocking, args.phase, blocking=True)
    else:
        body = build_comment_body(advisory[:3], args.phase, blocking=False)
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
