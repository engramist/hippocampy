# MC-017 — ClawShop Bootstrap Move/Copy Checklist

Context: MC-015 set the repo boundary direction.
- `sidequests-brain` stays the Brain/memory-engine repo.
- `mission-control/` is the best immediate extraction candidate for the future `clawshop` repo.
- This checklist is a practical first-cut bootstrap plan, not a final boundary ruling for every mixed file.

## Goal

Stand up a usable first version of the new `clawshop` repo by moving the operator-facing Mission Control surface first, copying only the minimum planning/bootstrap files needed to run it, and explicitly externalizing machine-specific assumptions.

---

## Proposed first-cut contents of the new repo

```text
clawshop/
  README.md
  .gitignore
  .env.example
  pyproject.toml              # or a slim Mission Control-specific replacement
  requirements.txt           # if staying with pip-first bootstrap
  pytest.ini                 # only if Mission Control tests stay in pytest
  Makefile                   # only if targets are rewritten for clawshop
  mission-control/
    server.py
    kanban.json
    digest.json
    activity-feed.json
    specs/
    static/
    templates/
    test_hardening.py
    test_mc006b_handles.py
  docs/                      # optional landing place for copied plans/specs later
  plans/
    B-mission-control.md
    MC-durable-workflow.md
    MC-015-clawshop-repo-split.md
    MC-017-clawshop-bootstrap-checklist.md
```

If we want the leanest possible initial cut, the smallest runnable slice is:
- `mission-control/`
- one dependency/bootstrap path (`requirements.txt` and/or `pyproject.toml`)
- `.gitignore`
- `.env.example`
- copied plan docs under `plans/`
- a new repo `README.md`

---

## 1) Mission Control core files

These are the first files/directories to move because they are the clearest ClawShop-owned product surface.

### Move first
- [ ] `mission-control/server.py`
- [ ] `mission-control/templates/base.html`
- [ ] `mission-control/templates/dashboard.html`
- [ ] `mission-control/templates/board.html`
- [ ] `mission-control/templates/activity.html`
- [ ] `mission-control/templates/card_detail.html`
- [ ] `mission-control/templates/digest.html`
- [ ] `mission-control/templates/thinking.html`
- [ ] `mission-control/static/mission.css`
- [ ] `mission-control/static/avatars/claws.png`
- [ ] `mission-control/static/avatars/crusty.png`
- [ ] `mission-control/static/avatars/gemini.png`
- [ ] `mission-control/specs/card_handoff_contract.md`
- [ ] `mission-control/specs/chain_next_spec.md`
- [ ] `mission-control/specs/handoff_ready_checklist.md`
- [ ] `mission-control/test_hardening.py`
- [ ] `mission-control/test_mc006b_handles.py`
- [ ] `mission-control/test_mc020_risk_ui.py`
- [ ] `mission-control/test_mc023_discord_hooks.py`

### Copy as starter data, then let ClawShop own them
These are runtime state/data files. Copy them into the new repo as seed fixtures unless we intentionally want a clean blank slate.
- [ ] `mission-control/kanban.json`
- [ ] `mission-control/digest.json`
- [ ] `mission-control/activity-feed.json`

### Do not move/copy
- [ ] Skip `mission-control/__pycache__/`

### Operator note
- Prefer a directory-level copy of `mission-control/`, then delete generated junk and rewrite config in place.
- If history preservation matters later, do a `git mv`/history-aware extraction pass after the repo shape is proven.

---

## 2) Supporting docs / plans

These should be copied into the new repo immediately so ClawShop starts with the product intent and operating context that Mission Control already depends on.

### Copy into `clawshop/plans/`
- [ ] `plans/B-mission-control.md`
- [ ] `plans/MC-durable-workflow.md`
- [ ] `plans/MC-015-clawshop-repo-split.md`
- [ ] `plans/MC-016-clawshop-inventory-slice-1.md`
- [ ] `plans/MC-017-clawshop-bootstrap-checklist.md`

### Optional follow-on docs to add in ClawShop right away
- [ ] New `README.md` explaining that ClawShop is the OpenClaw operator/workbench repo and consumes SideQuests Brain as an external integration
- [ ] New `docs/repo-boundary.md` or `docs/integrations/brain.md` summarizing the Brain ↔ ClawShop contract

### Why copy instead of move
- These plans still explain decisions that matter to the Brain repo transition.
- Keeping copies in both repos avoids losing decision context during the handoff.

---

## 3) Repo bootstrap files

This is the next bucket after inventory slice 1. Do not widen past these root/bootstrap files until Crusty reviews the Mission Control bundle and the `server.py` config seams.

These are the files to copy only if they still serve the extracted Mission Control app. Copy first, then trim aggressively so ClawShop does not inherit Brain-specific packaging by accident.

### Copy first, then edit for ClawShop
- [ ] `.gitignore`
- [ ] `requirements.txt`
- [ ] `pyproject.toml`
- [ ] `pytest.ini`
- [ ] `Makefile`

### Copy only if confirmed still relevant
- [ ] `.mcp.json` — only if it helps local dev for Mission Control/ClawShop and does not assume Brain-repo-specific paths

### Probably do not copy as-is
- [ ] `sidequests.toml`
- [ ] `smithery.yaml`

These last two look Brain/product-specific and should stay behind unless a specific ClawShop workflow proves they are needed.

### Bootstrap files to create new in ClawShop
- [ ] `README.md`
- [ ] `.env.example`
- [ ] `docs/` or `plans/` landing index for operators

### Practical trimming rule
Keep only what is needed to:
1. install Python dependencies,
2. run `mission-control/server.py`,
3. run Mission Control tests,
4. document required service URLs/tokens.

Anything Brain-packaging-specific should be removed or rewritten before calling the new repo “bootstrapped.”

---

## 4) Config / env assumptions to externalize

These are the biggest immediate portability risks in `mission-control/server.py`. Do not carry them forward as hardcoded values.

### Externalize before or immediately after first copy
- [ ] `BRAIN_URL` (`http://127.0.0.1:7799`) → env/config
- [ ] `OPENCLAW_URL` (`http://127.0.0.1:18789`) → env/config
- [ ] `OPENCLAW_TOKEN` (currently hardcoded) → env/secret only; never commit a real token in ClawShop
- [ ] `REPO_ROOT = Path(__file__).parent.parent` → replace with explicit workspace/project path config where needed
- [ ] `MEMORY_PATH = ... /.openclaw/workspace/memory` → make configurable or remove if ClawShop should not assume DJ’s home-layout
- [ ] bind host/port defaults (`127.0.0.1:7800`) → configurable for local/VPS/tailnet use
- [ ] timezone assumption (`America/Denver`) → env/config or UI/user setting

### Paths/state assumptions to review
- [ ] `kanban.json`, `digest.json`, and `activity-feed.json` ownership: decide whether these remain repo-tracked seed files, runtime-local data files, or configurable storage locations
- [ ] git commands against repo root: confirm whether Mission Control should inspect the ClawShop repo, a project repo, or a configurable workspace target
- [ ] any OpenClaw API headers/auth handling: move into a small client/config layer instead of leaving inline in app code

### Suggested first `.env.example`
```dotenv
MISSION_CONTROL_HOST=127.0.0.1
MISSION_CONTROL_PORT=7800
MISSION_CONTROL_TIMEZONE=America/Denver
BRAIN_URL=http://127.0.0.1:7799
OPENCLAW_URL=http://127.0.0.1:18789
OPENCLAW_TOKEN=
MISSION_CONTROL_REPO_ROOT=
MISSION_CONTROL_MEMORY_PATH=
```

### Immediate safety note
The currently hardcoded OpenClaw token in `mission-control/server.py` should be treated as compromised and rotated when the real split starts.

---

## 5) Follow-up cleanup tasks in `sidequests-brain` after the split

Once the first ClawShop copy exists and boots, clean up the Brain repo so the boundary stops drifting.

### Remove or reduce duplicate ownership
- [ ] Delete or archive the moved `mission-control/` code from `sidequests-brain` once the ClawShop copy is the active source of truth
- [ ] Remove Mission Control-specific tests from Brain CI/test ownership
- [ ] Stop landing new operator UX/dashboard work in `sidequests-brain`

### Replace with boundary notes
- [ ] Add a short note in `sidequests-brain/README` or docs: Mission Control/operator workbench now lives in ClawShop
- [ ] Keep `plans/MC-015-clawshop-repo-split.md` in Brain as the record of the split decision
- [ ] Optionally keep this checklist in Brain as the execution record of the extraction

### Check for stale references
- [ ] Search the Brain repo for `mission-control/` path references and update/remove them
- [ ] Search for `7800`, `OPENCLAW_URL`, `OPENCLAW_TOKEN`, and direct Mission Control links
- [ ] Update any Makefile/docs/scripts that still present Mission Control as part of the Brain product surface

### Revalidate repo scope
- [ ] Confirm `plugin/`, `extensions/`, `adapters/`, `web/`, `mcp_engine/`, `sidequests/`, and `brain_daemon.py` still read clearly as Brain-owned after Mission Control is gone
- [ ] Decide later whether any shared integration glue deserves a separate package, but do not block the first split on that

---

## Recommended move/copy order

1. [ ] Create new `clawshop` repo with `README.md`, `.gitignore`, and `.env.example`
2. [ ] Copy `mission-control/` into the new repo
3. [ ] Delete generated junk (`__pycache__`) from the copied tree
4. [ ] Copy the four plan docs into `clawshop/plans/`
5. [ ] Copy bootstrap files: `requirements.txt`, `pyproject.toml`, `pytest.ini`, `Makefile`
6. [ ] Remove Brain-specific packaging/config that ClawShop does not need
7. [ ] Externalize URLs, token, repo path, memory path, timezone, and bind settings
8. [ ] Confirm Mission Control runs in the new repo
9. [ ] Confirm Mission Control tests run in the new repo
10. [ ] Add boundary notes in both repos
11. [ ] Remove or archive the old Mission Control source from `sidequests-brain`

---

## Minimal success criteria for the first cut

The split is good enough to proceed when all of the following are true:
- [ ] `clawshop` can run Mission Control without depending on Brain-repo-relative paths
- [ ] no real token is committed in the new repo
- [ ] copied plan docs explain why ClawShop exists and what still belongs to SideQuests Brain
- [ ] `sidequests-brain` no longer looks like the home of the operator dashboard
- [ ] future Mission Control work has an obvious repo destination: ClawShop
