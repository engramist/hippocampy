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
| Phase 2 tooling | GitHub Copilot code review (automatic reviewer, reads `.github/copilot-instructions.md`) — chosen over Codex because it ships with the maintainer's existing Copilot plan; Codex would require a separate paid OpenAI subscription |
| Phase 3 tooling | `/code-review ultra` — maintainer-triggered before merge |
| Findings format | Structured table: file, line, rule, severity, fix |
| Block threshold | Phase 1: Semgrep HIGH/CRITICAL blocks via `review_gate.py` exit code; pip-audit dependency CVEs are advisory (surfaced, non-blocking) — a heavy ML dependency tree always carries unfixable CVEs; only code-level Semgrep HIGH/CRITICAL findings hard-block; CodeQL requires branch protection "Code scanning" check + alert severity threshold configured separately; Phase 2: Copilot review requests changes |
| Escalation trigger | Same rule fires on 2nd push AND contributor posted a comment since last bot comment |
| OSS org | GitHub org `hippocampy` — repo transferred from personal account |
| License | MIT |

---

## Architecture

### 1. Pipeline Overview

```
PR opened / new push
        │
        ▼ (runs in parallel)
┌─────────────────────────────────────────────────────┐
│ Phase 1 — Security Gate (GitHub Actions)            │  automatic on every push
│  CodeQL → Semgrep → pip-audit → secret scan        │
│  Semgrep/pip-audit FAIL → hard block via exit code  │
│  + structured findings comment                       │
│  CodeQL → Security tab (block via branch protection) │
└─────────────────────────────────────────────────────┘
│ Phase 2 — Ecosystem Gate (GitHub Copilot review)   │  runs in parallel with Phase 1
│  Reads .github/copilot-instructions.md (+ AGENTS.md)│  (advisory; cannot hard-block alone)
│  CHANGES REQUESTED → maintainer holds merge          │
└─────────────────────────────────────────────────────┘
        │ Phase 1 PASS (required check) + maintainer weighs Copilot review
        ▼
┌─────────────────────────────────────────────────────┐
│ Phase 3 — Deep Gate (/code-review ultra)            │  maintainer-triggered
│  5 parallel Claude reviewers, CLAUDE.md-grounded    │
└─────────────────────────────────────────────────────┘
        │ PASS
        ▼
     Maintainer approves + merges

Note: Phase 1 and Phase 2 run in parallel. The hard merge block is the `semgrep-pip` Actions
status check (required via branch protection) plus CODEOWNERS approval. Copilot's review is
advisory — an AI reviewer's "changes requested" does not hard-block in GitHub — but since the
maintainer is the sole merger, they withhold approval until Copilot's findings are resolved.

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

**Mechanism:** GitHub Copilot code review is enabled on the `hippocampy` repo and configured as
an automatic reviewer (repo Settings → Code review, or a repository ruleset requiring Copilot
review). It reviews automatically on each PR. Copilot was chosen over Codex because it is
included in the maintainer's existing Copilot plan, whereas Codex would require a separate paid
OpenAI subscription.

**Configuration file** — `.github/copilot-instructions.md` carries a `## PR Review Checklist
(Ecosystem Gate)` section that tells Copilot exactly what to check. The same checklist also
lives in `AGENTS.md` so any other agent (Claude, Gemini) applies the identical rules. The rules:

```markdown
## PR Review Checklist (Ecosystem Gate)

When reviewing a PR, check each item and report findings in this format:
| File | Line | Rule | Severity | Fix |

Rules:

1. **Layer placement** — new code must go in the right directory per ecosystem-rules.md.
   Flag: any `campy/` code in `agents/` or `benchmarks/`, or vice versa.
   Flag: any `agents/` or `benchmarks/` file with `from campy` import.

2. **No shadow stores** — persistent state must go through KuzuDB.
   Flag: module-level `store`/`cache`/`state`/`registry`/`db`-named dicts or lists in `campy/`.

3. **Tool registration** — new MCP tools must appear in `TOOL_HANDLERS` in
   `campy/brain/thalamus/tools/__init__.py` AND in `tool_schemas.TOOLS`,
   `extensions/hippocampy/src/index.ts`, and `tests/test_adapters.py` `EXPECTED_TOOLS`.

4. **Schema changes need migrations** — new node/edge types need a `_MIGRATIONS` entry.
   Flag: additions to `NODE_TABLES` or `REL_TABLES` (module-level, no underscore) in
   `schema.py` without a corresponding entry in the `_MIGRATIONS` list inside `init_schema()`.

If all checks pass: approve the PR.
If any check fails: request changes with the structured findings table.
```

**Copilot verdict:**
- All rules pass → Copilot approves (or leaves no change requests)
- Any rule fails → Copilot requests changes with the structured findings table → maintainer holds merge

**Note on enforcement:** unlike a required *status check*, an AI reviewer's "changes requested"
is advisory in GitHub — it does not hard-block merge by itself. Because the maintainer is the
sole merger (CODEOWNERS + branch protection), this is acceptable: Copilot's review surfaces
ecosystem issues for the maintainer, who withholds approval until they're resolved.

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

**Gam-ability note (v1 accepted):** A contributor could trigger escalation without actually
fixing the finding — e.g., post any comment then re-push with the same issue. This is accepted
at v1 because @engramist is the sole merger, so a false escalation just pings the maintainer
who can assess it directly. The cost is low. A future gate could require the previous finding's
rule to be absent from the new run before escalating.

### 6. OSS Release Hygiene

One-time setup tasks (no code — GitHub web UI + file additions):

| Task | Detail |
|------|--------|
| Create GitHub org | `hippocampy` at github.com/hippocampy |
| Transfer repo | Settings → Transfer ownership → `hippocampy` org |
| `LICENSE` | MIT |
| `CODEOWNERS` | `* @<maintainer-username>` |
| Enable Copilot review | Repo Settings → Code review → enable automatic Copilot code review (uses the maintainer's existing Copilot plan; no extra cost) |
| Branch protection on `main` | Require PR; require CODEOWNERS approval (1); require the `semgrep-pip` Phase 1 status check to pass; no admin bypass. (Copilot's review is advisory, not a required status check — the maintainer enforces it via approval.) |
| `CONTRIBUTING.md` | Explains the three-gate pipeline to contributors; links to ecosystem-rules.md |
| PR template (`.github/PULL_REQUEST_TEMPLATE.md`) | Short: description, test plan, checklist (ran tests / no shadow stores / code in right layer) |

---

## New Components

| Component | File | Notes |
|-----------|------|-------|
| Security gate workflow | `.github/workflows/security-gate.yml` | CodeQL + Semgrep + pip-audit jobs in parallel |
| Campy shadow-store Semgrep rule | `.semgrep/campy-no-shadow-stores.yaml` | Custom rule for shadow store detection in `campy/` |
| CodeQL config | `.github/codeql/codeql-config.yml` | Python query suite, exclude test fixtures |
| Review gate script | `.github/scripts/review_gate.py` | Single stdlib-only script: parses Semgrep + pip-audit JSON, posts/replaces structured findings comment with hidden rule IDs, and handles escalation (rule-ID overlap + contributor comment → label + ping). Gates via exit code. |
| Review gate tests | `tests/test_review_gate.py` | Unit tests for all pure functions in `review_gate.py` |
| Copilot review instructions | `.github/copilot-instructions.md` | `## PR Review Checklist (Ecosystem Gate)` section Copilot code review applies on every PR |
| AGENTS.md PR checklist section | `AGENTS.md` | Same `## PR Review Checklist` section so any agent (Claude, Gemini) applies identical rules |
| License | `LICENSE` | MIT |
| Contributing guide | `CONTRIBUTING.md` | Pipeline explanation + contribution instructions |
| PR template | `.github/PULL_REQUEST_TEMPLATE.md` | Short checklist for contributors |
| CODEOWNERS | `CODEOWNERS` | `* @<maintainer-username>` |

---

## Acceptance Criteria

- [ ] A PR with a subprocess `shell=True` call in `campy/` is blocked by Phase 1 with a structured findings comment
- [ ] A PR with a HIGH CVE in requirements.txt is blocked by Phase 1
- [ ] A PR that passes Phase 1 but puts `campy/` code in `agents/` gets a Copilot "changes requested" review citing the layer-placement rule
- [ ] A PR that passes Phase 1 and clears Copilot's review can be reviewed by the maintainer via `/code-review ultra`
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
