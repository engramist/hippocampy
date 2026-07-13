# Public Disclosure Boundary for Campy Release

**Status:** Patent Pending (March 25, 2026) — Non-Provisional Deadline: March 25, 2027

This document classifies all artifact types and establishes explicit disclosure decisions for public release.

## Classification Legend

| Decision | Meaning |
|----------|---------|
| **public** | Safe to include in public repository, PyPI wheel, and distribution |
| **private** | Keep in private/internal repository or archive; exclude from distribution |
| **redact** | Include with sensitive details removed (paths, credentials, names) |
| **counsel-review** | Requires patent attorney approval before public release |
| **package-exclude** | Exclude from wheel/sdist but may keep in GitHub repo |
| **historical-only** | Archive and remove from main repo; keep in historical record for reference |

---

## Artifact Classification

### 1. Runtime Code & Implementation

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `sidequests/` (core package) | **public** | Core implementation is the product | Ship in wheel/sdist |
| `mcp_engine/` (MCP server) | **public** | Public interface specification | Ship in wheel/sdist |
| `adapters/` (MCP integrations) | **public** | Integration code for public clients | Ship in wheel/sdist |
| `scripts/install.sh` | **public** | Bootstrap/setup documentation | Include in repo and distribution |
| `sidequests/cli/` (CLI commands) | **public** | Public-facing interface | Ship in wheel/sdist |
| `web/` (web assets) | **public** | Shipped with daemon | Ship in wheel/sdist |
| `sidequests/paths.py` (resource helpers) | **public** | Installed-mode infrastructure | Ship in wheel/sdist |

### 2. Architecture & Design Documentation

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `docs/ARCHITECTURE.md` | **public** | Public system design; references filed PPA | Publish with patent-pending notice |
| `docs/ecosystem-rules.md` | **public** | Development guidelines | Publish as reference |
| `docs/nonprovisional-strategy.md` | **counsel-review** | Filing facts & deadline; may guide competitors | Review before public release |
| `docs/public-disclosure-boundary.md` | **private** | Internal release planning; not end-user docs | Keep in private repo |
| Design diagrams & architecture sketches | **public** | Non-proprietary system overview | Publish sanitized versions |

### 3. Patent & Inventor Documentation

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `InvertorsDocs/Canonical-Inventors-Notebook.md` | **private** | Pre-filing invention record; strategically sensitive | Keep private; do not publish |
| `InvertorsDocs/PPA-Specification-Draft.*` | **private** | Filed provisional specification; may weaken claims | Keep private |
| `InvertorsDocs/PPA-Figures-*.pdf` | **private** | Provisional drawings; reference only | Keep private |
| Patent attorney communications | **private** | Legal work product; privileged | Keep private |
| Non-provisional draft outlines | **counsel-review** | Interim legal work; review before publication | Keep private until filed |

### 4. Backlog & Project Planning

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `backlog/B*.md` (completed cards) | **package-exclude** | Project history; may be too informal for public | Keep in repo, exclude from wheel |
| `backlog/B230-B233.md` (new release cards) | **package-exclude** | Release planning; not end-user documentation | Keep in repo, exclude from wheel |
| `backlog/plans/*.md` | **package-exclude** | Internal task tracking | Keep in repo, exclude from wheel |
| `backlog/masterBacklogTracker.md` | **package-exclude** | Project roadmap; OK for reference | Keep in repo, exclude from wheel |
| Historical sprint notes & decisions | **package-exclude** | Development artifacts; not product documentation | Keep in repo, exclude from wheel |

### 5. ARC (Automated Reasoning Challenge) Artifacts

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `benchmarks/` | **public** | Benchmark methodology & results | Publish with context |
| `submission_results_*.json` | **package-exclude** | Generated outputs; platform-dependent | Keep in repo for reference, exclude from wheel |
| `master_timeline.json` | **historical-only** | Single-run execution trace; archive | Move to archive, remove from main repo |
| ARC raw puzzle data (if included) | **package-exclude** | Respect ARC dataset licensing | Exclude from distribution |

### 6. Test Artifacts & Validation

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `tests/` (test suite) | **public** | Testing methodology | Include in repository and sdist; exclude from runtime wheel |
| `tests/test_*_installed_mode.py` (new tests from B230-B231) | **public** | Release validation tests | Include in repository and sdist; exclude from runtime wheel |
| `tests/test_public_release_manifest.py` (B232) | **public** | Distribution verification | Include in repository and sdist; exclude from runtime wheel |
| Generated test outputs (logs, coverage reports) | **package-exclude** | Transient outputs | Keep locally, exclude from distribution |

### 7. Configuration & Resources

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `pyproject.toml` | **public** | Package metadata & dependencies | Publish |
| `sidequests.toml` (repo config reference) | **public** | Development configuration reference | Keep in repo; do not rely on it at runtime |
| `sidequests/data/config/sidequests.toml` (default config template) | **public** | Installed-mode configuration template | Ship in wheel |
| `.gitignore` | **public** | Repository practices | Publish |
| `MANIFEST.in` (if needed) | **public** | Distribution rules | Publish |
| Generated `~/.campy/` runtime state | **private** | User data; never in distribution | Exclude from all distributions |

### 8. Build & Packaging Artifacts

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `dist/` (wheel/sdist outputs) | **public** | Distribution packages | Publish to PyPI |
| `pyproject.toml` build config | **public** | Build instructions | Publish |
| `.egg-info/` | **package-exclude** | Generated metadata | Keep locally, exclude from repo |
| Build logs & dependency locks | **package-exclude** | Development artifacts | Keep locally, exclude from repo |

### 9. Documentation & User Guides

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `README.md` | **redact** | Primary public documentation; must be sanitized | Include with patent-pending notice & local-data warning |
| `Instalation_Instructions.md` | **removed** (B297) | Stale test-machine Q&A that contradicted the README's install story; typo'd filename | Deleted — README's Install section is the updated version this row called for |
| `docs/` (user-facing) | **public** | Technical reference | Publish |
| CONTRIBUTING.md (if added) | **public** | Developer guidelines | Publish if created |

### 10. Credentials, Secrets & Local Paths

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| `.env` files | **private** | Environment secrets | Keep local only; add to `.gitignore` |
| API keys / credentials | **private** | Never commit | Remove if present; add to `.gitignore` |
| Personal/absolute paths (`/Users/djshelton`, `/home/user`) | **redact** | Machine-specific; use examples | Remove from all distributed code |
| Local `.sidequests/` runtime state | **private** | User memory database | Exclude from all distributions |
| Daemon socket files | **private** | Runtime IPC | Exclude from all distributions |

### 11. Academic & Research Materials

| Artifact | Classification | Rationale | Action |
|----------|-----------------|-----------|--------|
| Academic papers cited in ARCHITECTURE.md | **public** | Prior art references | Link to published versions |
| Benchmark comparisons (Zep, Mem0, Letta) | **counsel-review** | Competitive positioning; may raise claims | Review before publishing comparisons |
| Proprietary tuning parameters (embedding model choice, decay constants) | **counsel-review** | May warrant trade-secret protection | Decide per counsel: publish or protect |
| Thresholds & magic numbers (confidence gates, promotion factors) | **counsel-review** | May be trade secrets or patent claims | Decide per counsel |

---

## Decision Summary

### Public Distribution (Wheel/Sdist)

✅ **Include:**
- Runtime code (`sidequests/`, `mcp_engine/`, `adapters/`)
- CLI, web, and public interfaces
- Tests and validation scripts in the source distribution
- Documentation (`docs/ARCHITECTURE.md`, user guides)
- Configuration templates in the installed package
- Build & packaging metadata

❌ **Exclude:**
- Backlog, internal planning documents (`backlog/`, plans)
- Inventor/patent documents
- Generated artifacts (logs, databases)
- Personal paths, credentials
- User runtime state (`~/.campy/`)
- Pre-filing notes or sensitive strategy docs

### Public Repository (GitHub)

✅ **Include (visible to community):**
- Runtime code & tests
- Public documentation
- Backlog & project history (for transparency)
- Architecture & design decisions
- Contributing guidelines

❌ **Keep Private (or heavily redacted):**
- `InvertorsDocs/` (patent preparation)
- Internal counsel communications
- Pre-filing strategy docs (until filed)
- Personal contact information
- Credentials or secrets

---

## Patent-Pending Release Language

All public-facing materials must include:

```
Campy includes patent-pending memory architecture.
A U.S. provisional application was filed March 25, 2026 (Appl. #64/017,066).
No patent has been granted.
See PATENTS.md for filing facts and deadline.
```

---

## Private Data Minimization

**The following types of data must be removed before public release:**

1. ✅ `/Users/djshelton` paths → remove or replace with `$USER` or `~`
2. ✅ `/Desktop/GitProjects/hippocampy` → remove or replace with `$(git rev-parse --show-toplevel)`
3. ✅ `brain.db` (Kuzu database) → exclude from distribution
4. ✅ `brain.sock` (daemon socket) → exclude from distribution
5. ✅ `submission_results_*.json` (ARC run outputs) → exclude from wheel; keep in repo for historical reference
6. ✅ `agent_execution_trace.json` → exclude from distribution
7. ✅ `master_timeline.json` → archive; remove from main repo
8. ✅ API keys or credential examples → remove or use placeholders
9. ✅ Personal email addresses or contact info → redact
10. ✅ Obsidian/wiki generated output → exclude if not canonical

---

## Process: Counsel Review Before Public Release

**Step 1:** Run `scripts/audit_public_release.sh` to scan for high-risk artifacts (API keys, local paths, etc.).

**Step 2:** Consult this document to classify any findings.

**Step 3:** For items marked `counsel-review`, email a summary to patent counsel (e.g., "Disclosing ARCHITECTURE.md and design diagrams publicly; confirm this aligns with non-provisional strategy").

**Step 4:** Update this document with counsel feedback and decision rationale.

**Step 5:** Execute B232 (Private Data Audit) to verify wheel/sdist exclusions.

**Step 6:** Publish with confidence.

---

## Revision History

| Date | Change | Reviewer |
|------|--------|----------|
| 2026-05-10 | Initial creation from B233 plan | DShelton |
| TBD | Counsel review | Patent Attorney |

---

**Last Updated:** May 10, 2026  
**Responsible Party:** Engineering Team  
**Counsel Review Status:** Pending
