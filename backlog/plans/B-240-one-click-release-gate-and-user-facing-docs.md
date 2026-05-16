# Plan for B240 - One-Click Install Release Gate and User-Facing Docs

## Metadata

- **Card ID**: B240
- **Priority**: P0
- **Dependencies**: B236, B237, B238; B239 optional
- **Risk**: Medium - docs can overstate readiness if gate is not explicit

## Goal

Create the final go/no-go gate and user-facing docs for advertising one-click install.

## Step 1: Create Release Gate Doc

Create `docs/one-click-install-release-gate.md`.

Required sections:

- supported platforms
- required validation commands
- expected passing output
- package path status
- bootstrap status
- clean-machine status
- Homebrew status
- known limitations
- go/no-go decision record

## Step 2: Rewrite Install Docs

Update `README.md` and `Instalation_Instructions.md`.

Rules:

- Do not make one-click canonical until B236-B238 are complete.
- Include inspect-first and one-line variants.
- Include source/dev install as fallback.
- Include `campy doctor --repair`, `campy status`, and `campy activity --follow`.
- Explain where user memory lives and how uninstall preserves it.

## Step 3: Troubleshooting Guide

Create `docs/troubleshooting-install.md` with fixes for:

- daemon socket missing
- launchd plist missing
- Codex TOML duplicate/malformed blocks
- Claude MCP already exists
- VS Code config missing
- Kuzu DB health fail
- Ollama/provider unavailable
- activity feed empty

## Step 4: Update Tracker

Update `backlog/masterBacklogTracker.md` with B236-B240 rows and a One-Click Install section.

## Step 5: Validate

Run:

```bash
rg -n "one-click|bootstrap.sh|doctor --repair|activity --follow|~/.campy|uninstall|Codex|Claude|VS Code" README.md Instalation_Instructions.md docs
bash scripts/audit_public_release.sh --release
.venv/bin/campy doctor
.venv/bin/pytest -q tests/test_public_release_manifest.py tests/test_packaging_installed_mode.py tests/test_bootstrap_script.py tests/test_bootstrap_clean_home.py
```

If B237/B238 tests do not exist yet, this card must remain ready, not complete.

## Completion Notes

Mark B240 complete only when docs and release gate accurately reflect the final installer readiness.
