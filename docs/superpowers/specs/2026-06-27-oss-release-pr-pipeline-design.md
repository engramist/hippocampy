# OSS Release & Agent PR Review Pipeline
_Spec date: 2026-06-27_

## Problem

Campy is being released as a public OSS project. Without automated gates, external contributors
can submit PRs that introduce security vulnerabilities, inject malicious code, or place code in
the wrong ecosystem layer — breaking the strict Campy/ARC boundary, creating shadow stores, or
registering tools incorrectly. Manual review of every PR by the maintainer is too slow and
error-prone for adversarial content.

## Goal

Every PR is automatically scanned for security issues (primary) and ecosystem alignment
(secondary) before a human ever looks at it. The maintainer (sole merger in v1) runs a deep
heterogeneous review before approving. Contributors get clear, structured, actionable feedback
on failures. Repeat failures with a contributor comment escalate to human review rather than
blocking forever.

## Confirmed Design Decisions

| Decision | Choice |
|----------|--------|
| Merge authority | Maintainer only (enforced by CODEOWNERS + branch protection) |
| Gate ordering | Security first (Phase 1), then ecosystem (Phase 2), then deep review (Phase 3) |
| Phase 1 tooling | GitHub Actions — CodeQL + Semgrep + pip-audit + GitHub Secret Scanning |
| Phase 2 tooling | Codex GitHub App (required reviewer, reads AGENTS.md) |
| Phase 3 tooling | `/code-review ultra` — maintainer-triggered before merge |
| Findings format | Structured table: file, line, rule, severity, fix |
| Block threshold | Phase 1: any CodeQL/secret/HIGH+ CVE finding; Semgrep HIGH/CRITICAL; Phase 2: Codex "Changes requested" |
| Escalation trigger | Same rule fires on 2nd push AND contributor posted a comment since last bot comment |
| OSS org | GitHub org (`campy` or `hippocampy`) — repo transferred from personal account |
| License | MIT |

---

## Architecture

### 1. Pipeline Overview

```
PR opened / new push
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ Phase 1 — Security Gate (GitHub Actions)            │  automatic on every push
│  CodeQL → Semgrep → pip-audit → secret scan        │
│  FAIL → hard block + structured findings comment    │
└─────────────────────────────────────────────────────┘
        │ ALL PASS
        ▼
┌─────────────────────────────────────────────────────┐
│ Phase 2 — Ecosystem Gate (Codex GitHub App)         │  automatic required reviewer
│  Reads AGENTS.md + ecosystem-rules.md               │
│  CHANGES REQUESTED → block + structured findings    │
└─────────────────────────────────────────────────────┘
        │ APPROVED
        ▼
┌─────────────────────────────────────────────────────┐
│ Phase 3 — Deep Gate (/code-review ultra)            │  maintainer-triggered
│  5 parallel Claude reviewers, CLAUDE.md-grounded    │
└─────────────────────────────────────────────────────┘
        │ PASS
        ▼
     Maintainer approves + merges

Escalation: same rule fires on 2nd push + contributor comment
  → bot labels `needs-human-review`, pings maintainer
```

### 2. Phase 1 — Security Gate

**File:** `.github/workflows/security-gate.yml`

Four tools run in parallel as separate jobs. The workflow fails if any job fails.

| Tool | What it catches | Block threshold |
|------|----------------|-----------------|
| CodeQL | Injection, path traversal, deserialization, unsafe subprocess | Any finding |
| Semgrep | Python security patterns + Campy-specific shadow store rules | HIGH/CRITICAL block; MEDIUM advisory only |
| pip-audit | CVEs in Python dependencies (requirements*.txt + pyproject.toml) | Any HIGH or CRITICAL CVE |
| GitHub Secret Scanning | API keys, tokens, credentials committed in code | Any finding (GitHub enforces natively) |

**Campy-specific Semgrep rule** (`.semgrep/campy-no-shadow-stores.yaml`):

Detects module-level mutable collections in `campy/` that match the shadow store pattern:
```yaml
rules:
  - id: campy-shadow-store
    patterns:
      - pattern: $NAME = {}
      - pattern-inside: |
          # ...
      - metavariable-regex:
          metavariable: $NAME
          regex: ".*(store|cache|state|registry|db).*"
    message: >
      Module-level dict/list `$NAME` looks like a shadow store.
      Persistent state must go through KuzuDB. See ecosystem-rules.md.
    severity: ERROR
    languages: [python]
    paths:
      include: ["campy/**"]
```

**Findings comment format** (posted by bot, replaces previous on each push):

```
## Campy Security Review — BLOCKED

| # | File | Line | Rule | Severity | Fix |
|---|------|------|------|----------|-----|
| 1 | campy/brain/thalamus/tools/__init__.py | 142 | subprocess-shell-injection | HIGH | Use `subprocess.run([...])` not `shell=True` |
| 2 | requirements.txt | 7 | CVE-2025-1234 in requests==2.28.0 | HIGH | Upgrade to `requests>=2.31.0` |

<!-- campy-findings: subprocess-shell-injection,CVE-2025-1234 -->

**Fix the above and push again. The security gate re-runs automatically.**
```

The hidden HTML comment `<!-- campy-findings: rule-id-1,rule-id-2 -->` is used by the
escalation logic to detect repeat failures.

### 3. Phase 2 — Ecosystem Gate

**Mechanism:** Codex is installed as a GitHub App on the org and configured as a required
reviewer on the `hippocampy` repo. It reviews automatically when Phase 1 passes.

**AGENTS.md addition** — a new `## PR Review Checklist` section tells Codex exactly what to
check:

```markdown
## PR Review Checklist (Codex ecosystem gate)

When reviewing a PR, check each item and report findings in this format:
| File | Line | Rule | Severity | Fix |

Rules:

1. **Layer placement** — new code must go in the right directory per ecosystem-rules.md.
   Flag: any `campy/` code in `agents/` or `benchmarks/`, or vice versa.
   Flag: any `agents/` or `benchmarks/` file with `from campy` import.

2. **No shadow stores** — persistent state must go through KuzuDB.
   Flag: module-level `_store`, `_cache`, `_state`, `_registry` dicts or lists in `campy/`.

3. **Tool registration** — new MCP tools must appear in `TOOL_HANDLERS` in
   `campy/brain/thalamus/tools/__init__.py`.
   Flag: a new function matching `*_tool` or `handle_*` not present in `TOOL_HANDLERS`.

4. **Schema changes need migrations** — new node/edge types need a `_MIGRATIONS` entry.
   Flag: additions to `_NODE_TABLES` or `_REL_TABLES` in `schema.py` without a
   corresponding entry in `_MIGRATIONS`.

If all checks pass: approve the PR.
If any check fails: request changes with the structured findings table.
```

**Codex verdict:**
- All rules pass → Codex approves (required reviewer satisfied)
- Any rule fails → Codex posts "Changes requested" with structured findings table → PR blocked

### 4. Phase 3 — Deep Gate

The maintainer's personal workflow before merging. After Phase 2 passes:

1. Open the PR in a Claude Code session
2. Run `/code-review ultra` — dispatches 5 parallel Claude reviewers grounded in CLAUDE.md,
   AGENTS.md, and ecosystem-rules.md
3. Review consolidated findings
4. If clean: approve + merge
5. If findings: push back to contributor with comment, or fix inline for trivial issues

No automation needed here — this is maintainer judgment, not a gate.

### 5. Escalation Ladder

**Detection logic** (runs at the end of every Phase 1 or Phase 2 failure):

GitHub Actions script checks two conditions via the GitHub API:
1. The current failing run has at least one rule ID that appeared in the previous bot
   findings comment (parsed from the `<!-- campy-findings: ... -->` hidden comment)
2. The PR author posted at least one comment after the timestamp of the last bot comment

If both are true:
- Bot adds label `needs-human-review` to the PR
- Bot posts: `"This PR has the same finding ([rule-id]) after a re-push and a contributor
  comment. Pinging @maintainer for manual review."`
- Bot does NOT block further — the label is the signal

**What the escalation is NOT:** it does not auto-approve. The maintainer looks at it and
decides whether the finding is a false positive or a real issue.

### 6. OSS Release Hygiene

One-time setup tasks (no code — GitHub web UI + file additions):

| Task | Detail |
|------|--------|
| Create GitHub org | `campy` or `hippocampy` — check availability |
| Transfer repo | Settings → Transfer ownership → org |
| `LICENSE` | MIT |
| `CODEOWNERS` | `* @<maintainer-username>` |
| Branch protection on `main` | Require PR; require CODEOWNERS approval (1); require Phase 1 + Phase 2 status checks to pass; no admin bypass |
| `CONTRIBUTING.md` | Explains the three-gate pipeline to contributors; links to ecosystem-rules.md |
| PR template (`.github/PULL_REQUEST_TEMPLATE.md`) | Short: description, test plan, checklist (ran tests / no shadow stores / code in right layer) |

---

## New Components

| Component | File | Notes |
|-----------|------|-------|
| Security gate workflow | `.github/workflows/security-gate.yml` | CodeQL + Semgrep + pip-audit jobs in parallel |
| Campy shadow-store Semgrep rule | `.semgrep/campy-no-shadow-stores.yaml` | Custom rule for shadow store detection in `campy/` |
| CodeQL config | `.github/codeql/codeql-config.yml` | Python query suite, exclude test fixtures |
| Bot findings script | `.github/scripts/post-findings.py` | Posts/replaces structured findings comment; embeds hidden rule IDs |
| Escalation script | `.github/scripts/check-escalation.py` | Compares rule IDs, checks for contributor comment, labels PR |
| AGENTS.md PR checklist section | `AGENTS.md` | New `## PR Review Checklist` section for Codex |
| License | `LICENSE` | MIT |
| Contributing guide | `CONTRIBUTING.md` | Pipeline explanation + contribution instructions |
| PR template | `.github/PULL_REQUEST_TEMPLATE.md` | Short checklist for contributors |
| CODEOWNERS | `CODEOWNERS` | `* @<maintainer-username>` |

---

## Acceptance Criteria

- [ ] A PR with a subprocess `shell=True` call in `campy/` is blocked by Phase 1 with a structured findings comment
- [ ] A PR with a HIGH CVE in requirements.txt is blocked by Phase 1
- [ ] A PR that passes Phase 1 but puts `campy/` code in `agents/` is blocked by Phase 2 (Codex "Changes requested")
- [ ] A PR that passes both Phase 1 and Phase 2 can be reviewed by the maintainer via `/code-review ultra`
- [ ] Only the maintainer can merge (CODEOWNERS + branch protection enforced)
- [ ] A PR with the same rule failure on 2nd push + a contributor comment gets labeled `needs-human-review`
- [ ] The bot findings comment is replaced (not duplicated) on each push
- [ ] A clean PR (no findings in either gate) passes both automated checks without maintainer intervention beyond Phase 3
- [ ] `campy context regen` does not break after new `.github/` files are added (no CONTEXT.md regression)

---

## Backlog Card

**B291 — OSS Release & Agent PR Review Pipeline**
Priority: P2 (before public release)
Dependencies: None (independent of B290 CWS)
