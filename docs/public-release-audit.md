# Public Release Audit Manifest

**Last Run:** 2026-05-11  
**Release Mode:** Not yet released  
**Status:** Local audit and distribution checks pass

## Scope

This manifest tracks:
1. High-risk patterns scanned (API keys, local paths, credentials)
2. Generated/runtime artifacts (databases, sockets, logs)
3. Distribution content verification (wheel/sdist)
4. Decisions on each finding (keep, redact, remove, exclude)
5. Remediation status

## Required Findings Categories

| Category | Risk Level | Examples | Decision Template |
|----------|-----------|----------|-------------------|
| API Keys / Credentials | **BLOCKED** | `sk-*`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, private keys | REMOVE or REDACT |
| Local Paths | **BLOCKED** | `/Users/djshelton`, `/Desktop/GitProjects`, `/home/user` | REMOVE or REPLACE with `$HOME` |
| Runtime State | **BLOCKED** | `brain.db`, `brain.sock`, `.sidequests/` | EXCLUDE from wheel/sdist |
| Generated Artifacts | **HIGH** | `submission_results_*.json`, `agent_execution_trace.json` | EXCLUDE from wheel; may keep in repo with rationale |
| Personal Information | **HIGH** | Email addresses, personal contact info, annotations | REDACT or REMOVE |
| Patent Documents | **COUNSEL-REVIEW** | PPA specification, drawings, pre-filing notes | KEEP PRIVATE; exclude from public repo |

## Tracked Findings

### Blocked Category (Zero Tolerance)

| Pattern | Status | File(s) | Decision | Action | Date |
|---------|--------|---------|----------|--------|------|
| `/Users/djshelton` | CLEARED | None found in tracked or untracked release-candidate files | NONE | Continue scanning in build artifacts | 2026-05-11 |
| `OPENAI_API_KEY` | CLEARED | None found | NONE | N/A | 2026-05-10 |
| `ANTHROPIC_API_KEY` | CLEARED | None found | NONE | N/A | 2026-05-10 |
| `BEGIN RSA PRIVATE KEY` | CLEARED | None found | NONE | N/A | 2026-05-10 |

### High-Risk Artifacts

| Artifact | Status | Location | Decision | Action | Owner |
|----------|--------|----------|----------|--------|-------|
| `brain.db` | CLEARED | Generated at runtime under `~/.sidequests/` | EXCLUDE from distributions | Update `.gitignore` if needed | DShelton |
| `brain.sock` | CLEARED | Runtime socket | EXCLUDE from distributions | Verify not committed | DShelton |
| `submission_results_*.json` | CLEARED FROM DIST | Repo root historical artifacts | EXCLUDE from wheel/sdist; archive old runs separately | Verified by audit script | DShelton |
| `agent_execution_trace.json` | CLEARED FROM DIST | Repo root historical artifact | EXCLUDE from wheel/sdist; archive separately | Verified by audit script | DShelton |
| `master_timeline.json` | CLEARED FROM DIST | Repo root historical artifact | HISTORICAL-ONLY; archive separately | Verified by audit script | DShelton |

### Patent & Proprietary Documentation

| Document | Classification | Location | Status | Action |
|----------|-----------------|----------|--------|--------|
| `InvertorsDocs/Canonical-Inventors-Notebook.md` | **PRIVATE** | Repo (private) | KEPT PRIVATE | Do not publish |
| `InvertorsDocs/PPA-Specification-Draft.*` | **PRIVATE** | Repo (private) | KEPT PRIVATE | Do not publish |
| `InvertorsDocs/PPA-Figures-*.pdf` | **PRIVATE** | Repo (private) | KEPT PRIVATE | Do not publish |

### Generated Artifacts Excluded from Distribution

The following should be excluded from wheel/sdist:

```
.sidequests/                    # User runtime state
brain.db                         # Local Kuzu database
brain.sock                       # Daemon socket
*.log                           # Log files
submission_results*.json        # ARC run outputs
agent_execution_trace.json      # ARC execution trace
master_timeline.json            # Single-run timeline
*.pyc, __pycache__/            # Python cache
.egg-info/                      # Build artifacts
dist/, build/                   # Build output
```

### Distribution Verification

**Wheel Content Check:**
```bash
python -m build --wheel
python - <<'PY'
import zipfile
from pathlib import Path
for whl in Path('dist').glob('*.whl'):
    with zipfile.ZipFile(whl) as z:
        names = '\n'.join(z.namelist())
        blocked = ['.sidequests', 'brain.db', 'submission_results', 'agent_execution_trace']
        for token in blocked:
            assert token not in names, f"Blocked artifact in wheel: {token}"
print('Wheel content verified')
PY
```

**Sdist Content Check:**
```bash
python - <<'PY'
import tarfile
from pathlib import Path
for sdist in Path('dist').glob('*.tar.gz'):
    with tarfile.open(sdist) as t:
        names = '\n'.join(t.getnames())
        blocked = ['.sidequests', 'brain.db', 'submission_results', 'agent_execution_trace', 'master_timeline.json']
        for token in blocked:
            assert token not in names, f"Blocked artifact in sdist: {token}"
print('Sdist content verified')
PY
```

## Remediation Checklist

- [x] All API keys/credentials removed from tracked files
- [x] Local paths removed or replaced with placeholders
- [x] Generated artifacts excluded from `.gitignore`
- [x] `pyproject.toml` / `MANIFEST.in` excludes non-package files
- [x] Wheel build excludes runtime state
- [x] Sdist build excludes generated artifacts
- [x] Patent documents confirmed private
- [x] README includes local-data/privacy notice
- [ ] All findings documented with explicit decisions
- [ ] Counsel review for sensitive/strategic disclosures (if needed)

## Counsel-Review Items

Items requiring patent attorney approval before public release:

- [ ] Publishing ARCHITECTURE.md with full claim descriptions
- [ ] Tuning parameters and magic numbers (trade secret vs. patent claim)
- [ ] Academic comparisons (prior art framing)
- [ ] Non-provisional strategy in `docs/nonprovisional-strategy.md`

## Sign-Off

| Role | Name | Date | Status |
|------|------|------|--------|
| Engineering | DShelton | 2026-05-10 | In Progress |
| Patent Counsel | TBD | TBD | Pending Review |
| Release Owner | TBD | TBD | Pending Approval |

---

**Latest Verification:** `scripts/audit_public_release.sh` passed on May 11, 2026; generated `dist/` wheel and sdist were clean.

**Last Updated:** 2026-05-11  
**Responsible:** DShelton (Engineering)
