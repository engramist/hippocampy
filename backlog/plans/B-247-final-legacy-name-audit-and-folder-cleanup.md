# Plan for B247 - Final Legacy Name Audit and Optional Folder Cleanup

## Metadata

- **Card ID**: B247
- **Priority**: P1
- **Dependencies**: B243, B244, B245, B246
- **Risk**: Medium - broad cleanup can accidentally rewrite historical/patent sources

## Goal

Audit remaining SideQuests/sidequests names and remove stale public-facing references while preserving intentional historical, patent, graph ontology, and compatibility references.

## Guardrails

- Do not bulk rename patent/provisional source artifacts without explicit approval.
- Do not rename graph ontology terms such as `SideQuest` unless a schema card says so.
- Do not remove legacy shims before compatibility tests pass.
- Do not delete user data or runtime directories.

## Step 1: Generate Audit

Run:

```bash
find . -path './.git' -prune -o -path './.venv' -prune -o -path './build' -prune -o -path './dist' -prune -o -iname '*sidequest*' -print | sort
rg -n "sidequests-brain|SideQuests Brain|sidequests-memory|sidequests.toml|from sidequests|python -m sidequests" . --glob '!.git/**' --glob '!.venv/**' --glob '!build/**' --glob '!dist/**'
```

## Step 2: Create Audit Doc

Create `docs/legacy-name-audit.md` with sections:

- Public-facing stale names to fix now
- Intentional compatibility names
- Historical/patent records to preserve
- Graph ontology terms to preserve
- Generated artifacts to delete/ignore

## Step 3: Cleanup Safe Generated Artifacts

Remove or ignore stale generated artifacts such as:

- old `.mcpb` bundles
- old preflight wheels/sdists
- caches
- build folders

Do not remove source files.

## Step 4: Update Active Docs and Backlog

Update active install docs and future backlog cards. Historical archives may keep original names but should be listed in the audit doc.

## Step 5: Tests and Audit

Run:

```bash
.venv/bin/pytest -q
bash scripts/audit_public_release.sh
```

## Completion Notes

Paste the final intentional-exceptions list into the card completion notes.
