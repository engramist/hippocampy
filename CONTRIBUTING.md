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

### Gate 2 — Ecosystem Alignment (automatic, GitHub Copilot review)

GitHub Copilot code review automatically reviews the PR for ecosystem compliance
(per `.github/copilot-instructions.md`):
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
