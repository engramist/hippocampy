# Plan for B232 - Public Release Private Data Audit

## Card Metadata

- **Card ID**: B232
- **Priority**: P0
- **Dependencies**: B230 for distribution artifact audit, B233 for disclosure-boundary decisions

## Summary

Create a repeatable audit that blocks public distribution if private data, generated artifacts, secrets, local paths, or unintended research notes would ship.

The audit has two scopes:

1. Git-tracked repository contents.
2. Built wheel/sdist contents.

## Technical Approach

### Step 1: Create audit script

Create `scripts/audit_public_release.sh`.

Use shell plus `rg` for common findings:

```bash
rg -n "sk-[A-Za-z0-9]|OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|BEGIN .*PRIVATE KEY|/Users/|Desktop/GitProjects|brain\.db|brain\.sock|submission_results|agent_execution_trace|master_timeline" .
```

Exclude expected generated directories and the audit manifest itself carefully.

The script should also inspect `dist/*` if present. If `dist` is absent, print a warning but do not fail unless running in release mode:

```bash
scripts/audit_public_release.sh --release
```

### Step 2: Create audit manifest

Create `docs/public-release-audit.md` with sections:

- Scope
- Last run date
- High severity findings
- Medium severity findings
- Accepted historical references
- Package exclusions
- Files moved/removed/redacted
- Follow-up cards

Every finding should get a decision:

```text
keep | redact | remove | archive | ignore-only | package-exclude | counsel-review
```

### Step 3: Audit git-tracked files

Run:

```bash
git ls-files > /tmp/sidequests-tracked-files.txt
```

Scan tracked files only. Separate historical docs from runtime/package files.

Likely categories:

- personal absolute paths in docs/backlog
- ARC raw artifacts
- Obsidian/wiki generated output
- Kuzu DB/test DB files
- daemon logs
- private patent prep docs
- API-key examples
- local config files

### Step 4: Audit distribution artifacts

Build dist and inspect names/content:

```bash
python -m build --wheel --sdist
python - <<'PY'
import tarfile, zipfile
from pathlib import Path
for whl in Path('dist').glob('*.whl'):
    with zipfile.ZipFile(whl) as z:
        print('\n'.join(z.namelist()))
for sdist in Path('dist').glob('*.tar.gz'):
    with tarfile.open(sdist) as t:
        print('\n'.join(t.getnames()))
PY
```

Decide whether backlog, inventor docs, archives, diagrams, raw benchmark files, and internal reports belong in public sdist. Wheel should be minimal runtime package.

### Step 5: Update ignore and manifest rules

Update `.gitignore`, `pyproject.toml`, and/or `MANIFEST.in` so generated/private artifacts are not accidentally included.

Do not remove tracked files just because they are ignored; explicitly remove or move tracked files if needed.

### Step 6: Add tests

Create `tests/test_public_release_manifest.py`.

Test examples:

- wheel excludes `.sidequests`, `brain.db`, `*.sock`, `submission_results*`, `agent_execution_trace*`
- sdist excludes generated DB/log/wiki artifacts
- package data includes required runtime resources from B230

### Step 7: Update public docs

Add a short privacy/local-data note to README:

- SideQuests stores memory locally under `~/.sidequests`.
- Public package does not include user memory.
- Activity logs redact full prompt/response bodies.

## Validation

Run exactly:

```bash
bash scripts/audit_public_release.sh
python -m build --wheel --sdist
pytest -q tests/test_public_release_manifest.py
```

Distribution check:

```bash
python - <<'PY'
import tarfile, zipfile
from pathlib import Path
blocked = ['.sidequests', 'brain.db', 'brain.sock', 'submission_results', 'agent_execution_trace', 'master_timeline.json']
for whl in Path('dist').glob('*.whl'):
    with zipfile.ZipFile(whl) as z:
        names = '\n'.join(z.namelist())
        for token in blocked:
            assert token not in names, (whl, token)
for sdist in Path('dist').glob('*.tar.gz'):
    with tarfile.open(sdist) as t:
        names = '\n'.join(t.getnames())
        for token in blocked:
            assert token not in names, (sdist, token)
print('distribution audit ok')
PY
```

## Risks

- Historical patent/backlog docs may intentionally contain local paths. Classify rather than blindly redact.
- Git history may contain older sensitive data; this card audits current tree. If secrets are found, rotate them and create a separate history-cleanup decision.
- Excluding too much from sdist can break installs; coordinate with B230.
