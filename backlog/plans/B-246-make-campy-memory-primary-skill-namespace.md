# Plan for B246 - Make `campy-memory` the Only Primary Skill Namespace

## Metadata

- **Card ID**: B246
- **Priority**: P1
- **Dependencies**: B241, B242
- **Risk**: Low/Medium - affects agent guidance and installed Codex skills

## Goal

Make `campy-memory` the canonical memory usage skill and reduce `sidequests-memory` to legacy forwarding compatibility.

## Guardrails

- Do not delete user-modified installed skills.
- Do not duplicate full policy text in both skill folders after this card.
- Keep anti-bloat policy intact.
- Keep at least one legacy compatibility test.

## Step 1: Canonical Skill

Ensure this file is canonical:

```text
skills/campy-memory/SKILL.md
```

It should mention Campy/HippoCampy, `campy activity --follow`, and `campy doctor --repair`.

## Step 2: Packaged Skill

Ensure packaged copy matches canonical exactly:

```text
campy/data/campy-memory/SKILL.md
```

If package data is still under a compatibility package after B243, use the current package-data location but name the resource `campy-memory`.

## Step 3: Legacy Skill Forwarder

Replace full legacy skill content in:

```text
skills/sidequests-memory/SKILL.md
sidequests/data/sidequests-memory/SKILL.md
```

with a short deprecation note pointing to `campy-memory`, unless package-data compatibility requires keeping the full file. If full file must remain, mark it as legacy and add a cleanup note.

## Step 4: Installer Behavior

Update Codex skill install to install `campy-memory`.

If an owned old `sidequests-memory` skill exists and matches the old packaged hash, the installer may replace it with a forwarding note. If it differs, leave it untouched.

## Step 5: Tests

Create/update tests:

- `tests/test_campy_memory_skill.py` verifies canonical content.
- `tests/test_sidequests_memory_skill.py` verifies legacy forwarding compatibility.
- installer tests verify target path is `~/.codex/skills/campy-memory/SKILL.md`.

## Step 6: Validate

Run exactly:

```bash
.venv/bin/pytest -q tests/test_campy_memory_skill.py tests/test_sidequests_memory_skill.py tests/test_installer_idempotency.py
rg -n "skills/sidequests-memory|sidequests-memory" AGENTS.md CLAUDE.md GEMINI.md README.md docs tests skills sidequests campy
```

## Completion Notes

Record whether legacy skill files were reduced to forwarding notes or retained as full compatibility copies.
