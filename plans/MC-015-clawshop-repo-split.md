# MC-015 - ClawShop / SideQuests Brain Repo Boundary (First Pass)

## Executive Summary

**Recommendation:** split now at the repo boundary, but migrate in **two phases**:

1. **Create a new `clawshop` repo immediately** as the home for the OpenClaw development environment, Mission Control product surface, operator workflows, and future shop/runtime code.
2. **Move product/runtime/UI code first** (`mission-control/` and related docs/plans), while leaving SideQuests Brain as an independent memory engine repo.
3. **Keep SideQuests-specific memory engine code in `sidequests-brain`**: daemon, graph/loop engine, adapters, installer, MCP/web API, and SideQuests-branded plugin surfaces.
4. **Treat the Brain ↔ ClawShop link as an integration contract**, not a shared codebase. ClawShop may consume SideQuests Brain, but must not continue to grow inside the Brain repo.

Core framing for the split:

- **SideQuests Brain** = reusable memory/knowledge engine product.
- **ClawShop** = OpenClaw-based operator environment / workbench / shop layer used to create and run projects.
- **SideQuests** remains its own independent project/repo and is not the same thing as the OpenClaw environment.

---

## Boundary Decision

## What SideQuests Brain is

`sidequests-brain` should remain the repo for:

- the **memory engine**
- the **knowledge graph / consolidation loop**
- the **daemon + API/MCP server**
- **client adapters** that expose Brain tools to external AI clients
- the **install/setup/packaging story** for the Brain as an independent product
- SideQuests-specific docs, tests, and seed data

This repo should answer: **"How does the Brain work, run, and integrate?"**

## What ClawShop is

`clawshop` should become the repo for:

- the **OpenClaw-centered work environment**
- the **operator UX** for coordinating agents/jobs/tasks
- **Mission Control** and other environment-facing dashboards
- OpenClaw runtime glue, environment config templates, orchestration helpers, shop workflows
- future multi-project workbench/product code that is **not** the Brain itself

This repo should answer: **"How do we run and operate the OpenClaw workspace/shop?"**

## Architectural Rule

**If code can exist without SideQuests Brain as a product, it probably belongs in ClawShop.**

**If code is the Brain, installs the Brain, or exposes Brain APIs/tools, it belongs in `sidequests-brain`.**

When uncertain, use this ownership test:

- **Brain-owned** if the module would still be necessary when ClawShop is replaced by another client.
- **ClawShop-owned** if the module would still be necessary when SideQuests Brain is replaced by another memory backend.
- **Integration-owned** if it exists purely to connect the two; keep it near the side with the narrower contract until the API stabilizes.

---

## Current Inventory - What Likely Belongs Where

## Keep in `sidequests-brain`

### Core runtime / engine
- `mcp_engine/`
- `brain_daemon.py`
- `sidequests/`
- `web/`
- `adapters/`
- `tests/` (except any future Mission Control-only tests)
- `InvertorsDocs/` (seed/routing knowledge assets)
- `requirements.txt`
- `pyproject.toml`
- `pytest.ini`
- `sidequests.toml`
- `smithery.yaml`
- `mcpb/`

### Brain-facing plugin/integration surfaces
- `plugin/`
- `extensions/sidequests-brain/`

**Why keep these for now:** they are branded and shaped as **SideQuests Brain integrations**. They expose Brain functionality to clients. They are not the Mission Control/operator product itself.

### Brain-specific planning/docs
- most `plans/B*.md`
- `SESSION-STATUS.md`
- Brain architecture/debug docs tied to graph/loop/runtime behavior

---

## Move to `clawshop`

### Product/UI/workbench code
- `mission-control/`

This is the clearest move candidate. It is an operator dashboard / task board / runtime cockpit for the OpenClaw work environment, not part of the Brain engine.

### Likely companion docs/plans to move or copy into ClawShop
- `plans/B-mission-control.md`
- `plans/MC-durable-workflow.md`
- this new split plan (`plans/MC-015-clawshop-repo-split.md`) should be copied into the new repo when created
- any future notes specifically about OpenClaw workspace UX, task routing, dashboards, shop flows, or agent operations

### Likely future ClawShop-owned surfaces once they exist
- OpenClaw environment bootstrap scripts
- workspace-level agent configs/templates
- operator dashboards
- job orchestration helpers
- shop/project catalog UX
- project creation / execution workflows

---

## Mixed / Transitional Areas

These are real boundary seams and should be handled deliberately.

### 1. `mission-control/` currently talks directly to the Brain and OpenClaw

Current behavior in `mission-control/server.py` shows it is simultaneously:
- a dashboard for work/task orchestration
- a consumer of Brain endpoints
- a consumer of OpenClaw runtime state

That makes it **ClawShop-owned UI over external services**, not Brain-owned core logic.

**Decision:** move `mission-control/` to ClawShop, but refactor it to depend only on stable external contracts.

### 2. `extensions/sidequests-brain/`

This extension is an **OpenClaw plugin that exposes SideQuests Brain memory tools**. It sits between the two worlds.

**First-pass recommendation:** keep it in `sidequests-brain` for the first cut because:
- the package identity is `sidequests-brain`
- it is specifically a Brain memory provider
- its primary responsibility is exposing Brain semantics, not ClawShop UX

**Later option:** once the Brain API is stable, consider extracting integrations into:
- `sidequests-brain-integrations`, or
- keeping the plugin source in ClawShop but publishing under a Brain-owned namespace

For **this** split, do **not** block on moving the extension.

### 3. CLI installer/client detection in `sidequests/cli/`

The current installer detects Claude/Codex/Gemini clients and configures adapters. That still fits Brain ownership because it installs the Brain and registers Brain adapters into clients.

However, if a future OpenClaw/ClawShop bootstrap script starts installing whole work environments, that bootstrap should live in ClawShop and simply consume Brain installation as a dependency.

---

## Minimal Contract Between ClawShop and SideQuests Brain

Do **not** share internals across repos. Use a narrow contract.

## Brain should expose

### Runtime interfaces
- HTTP endpoint(s) for health and tool calls
- MCP tool surface
- daemon availability / status

### Stable semantic surfaces
- recall/search
- passive ingestion (`notify_turn` / equivalent)
- open loops / context status
- optional graph exploration endpoints

### Optional packaging interfaces
- pip package / install command
- local daemon startup contract

## ClawShop should consume

- Brain base URL / transport config
- Brain tool names and response schema
- health/status contract
- auth/config injection as configuration, not hardcoded values

---

## Key Risks / Smells Found In Current Layout

## 1. Mission Control is in the wrong repo

`mission-control/` is product/workbench code living inside the Brain repo. This muddies ownership and will keep pulling more OpenClaw-environment logic into `sidequests-brain` unless split now.

## 2. Mission Control appears tightly coupled to local machine assumptions

From `mission-control/server.py`, current coupling includes:
- repo-root assumptions
- local filesystem paths into `.openclaw`
- direct OpenClaw URL/token config in app code
- direct Brain URL assumptions

This is exactly the kind of environment orchestration code that belongs in ClawShop.

## 3. The extension directory includes a large dependency tree

`extensions/sidequests-brain/` includes `node_modules` in-repo. Even if retained in `sidequests-brain`, generated dependency trees should not be part of boundary reasoning or repo moves. Rebuild in target repos rather than copying bulky generated artifacts.

## 4. Brand confusion already exists in structure

The current repo contains all of these at once:
- Brain engine code
- Mission Control UI
- OpenClaw extension
- plugin packaging
- operator/workbench plans

That encourages accidental identity drift: the Brain repo starts acting like the whole operating environment.

---

## Migration Sequence (Recommended)

## Phase 0 - Freeze the boundary decision

Do this immediately:
- agree that **new Mission Control / shop / OpenClaw-environment work goes to ClawShop**, not `sidequests-brain`
- treat `sidequests-brain` as Brain-only except for temporary transitional code

This is the most important action because it stops further accretion before files are moved.

## Phase 1 - Create the new repo

Create `clawshop` with minimal scaffolding:

```text
clawshop/
  README.md
  docs/
  mission-control/
  config/
  scripts/
  .gitignore
```

Recommended initial README framing:
- ClawShop is the OpenClaw development environment / operator workbench
- it can create and run projects like SideQuests
- it is not SideQuests itself
- SideQuests Brain is an external dependency/integration, not this repo's identity

## Phase 2 - Move Mission Control first

Move/copy first:
- `mission-control/`
- `plans/B-mission-control.md`
- `plans/MC-durable-workflow.md`
- this plan document

Then in ClawShop, rename/reframe product language as needed:
- "SideQuests Mission Control" → "ClawShop Mission Control" or similar
- replace Brain-repo-root assumptions with app config

**Why this first:** it delivers immediate clarity with minimal risk to Brain engine stability.

## Phase 3 - Refactor Mission Control to consume contracts

Before doing bigger moves, clean the coupling:
- replace hardcoded `REPO_ROOT` assumptions with config/env
- move OpenClaw token/URL to env or config file
- treat Brain URL as external service config
- isolate side-effects into small client modules:
  - `brain_client`
  - `openclaw_client`
  - `workspace_client`

This creates a proper product/service boundary.

## Phase 4 - Leave Brain integrations in place temporarily

Do **not** move these in the first cut:
- `extensions/sidequests-brain/`
- `plugin/`
- `adapters/`
- `sidequests/cli/`

Revisit only after:
- Mission Control is stable in ClawShop
- Brain API/tool contracts are documented
- there is pressure to split integration ownership more cleanly

## Phase 5 - Optional second-wave extraction

Only if needed later:
- extract generic OpenClaw environment bootstrap code from Brain install scripts
- move shared operator docs/workflow specs into ClawShop
- possibly create a separate integration package/repo for OpenClaw ↔ Brain bridges

---

## File-by-File First Pass

## Strong keepers in `sidequests-brain`
- `mcp_engine/**`
- `sidequests/**`
- `adapters/**`
- `web/**`
- `brain_daemon.py`
- `plugin/**`
- `extensions/sidequests-brain/**`
- `tests/**` (except any future Mission Control-only tests)
- `mcpb/**`
- `InvertorsDocs/**`

## Strong movers to `clawshop`
- `mission-control/**`

## Move-or-copy supporting docs
- `plans/B-mission-control.md`
- `plans/MC-durable-workflow.md`
- `plans/MC-015-clawshop-repo-split.md`

## Do not copy as source-of-truth
- `__pycache__/`
- `.pytest_cache/`
- `.venv/`
- `extensions/sidequests-brain/node_modules/` (rebuild instead)
- local logs / generated artifacts

---

## Recommended Ownership Model After Split

## SideQuests Brain repo owner responsibilities
- memory engine
- data model / graph schema
- daemon and transport
- recall/ingest semantics
- client adapters and Brain plugin surfaces
- packaging/install for Brain

## ClawShop repo owner responsibilities
- workspace/operator UX
- task and agent operations
- dashboards
- environment configuration
- orchestration/product workflows
- future shop/project management surfaces

---

## Concrete Next Moves

1. **Create the GitHub repo now**: `clawshop`.
2. **Copy `mission-control/` into the new repo first** as the initial product slice.
3. **Copy the 2–3 planning docs** that define Mission Control and the split.
4. **Refactor Mission Control config immediately** so URLs/tokens/paths are not hardcoded to DJ's local machine.
5. **Add a short boundary note to both repos**:
   - `sidequests-brain`: "Brain engine only; operator/shop/runtime UX lives in ClawShop."
   - `clawshop`: "Workspace/shop runtime; SideQuests Brain is an optional external memory backend."
6. **Declare a temporary moratorium**: no new Mission Control or OpenClaw-environment features land in `sidequests-brain` unless absolutely necessary for the transition.

---

## Cut Recommendation

**Cut the repo now, move Mission Control first, and postpone integration-package cleanup.**

That gives the highest clarity for the least migration risk.

The wrong move would be waiting for a perfect final architecture and continuing to build ClawShop product code inside `sidequests-brain` in the meantime.

---

## First Concrete Extraction Target (MC-016 Slice 1 — Ready to Execute)

*Updated 2026-03-23 after MC-016 inventory pass. This section defines the exact first bundle to move; everything above is still the authoritative boundary definition.*

### The first folder to extract: `mission-control/`

This is the single highest-confidence extraction candidate. It is entirely product/operator code, not Brain engine code. MC-016 slice-1 has already catalogued its exact contents.

### Ordered extraction bundle

**Move as source code into `clawshop/mission-control/`:**

```
mission-control/server.py
mission-control/static/
mission-control/templates/
mission-control/specs/
mission-control/test_hardening.py
mission-control/test_mc006b_handles.py
mission-control/test_mc020_risk_ui.py
mission-control/test_mc023_discord_hooks.py
```

**Copy as seed runtime data (ClawShop owns/updates from day 1):**

```
mission-control/kanban.json        → clawshop/mission-control/kanban.json
mission-control/digest.json        → clawshop/mission-control/digest.json
mission-control/activity-feed.json → clawshop/mission-control/activity-feed.json
```

**Exclude / do not copy:**

```
mission-control/__pycache__/
```

**Copy supporting plans as bootstrap context into `clawshop/plans/`:**

```
plans/B-mission-control.md
plans/MC-durable-workflow.md
plans/MC-015-clawshop-repo-split.md   ← this file
plans/MC-016-clawshop-inventory-slice-1.md
plans/MC-017-clawshop-bootstrap-checklist.md
```

---

### Config externalization required before `server.py` is portable

`mission-control/server.py` currently has hard-coupled assumptions that must be converted to env vars or config before the new repo is considered portable. These are **not blocking the extraction**, but they are blocking treating the extracted copy as standalone/runnable elsewhere:

| Assumption | Recommended replacement |
|---|---|
| Hard-coded Brain URL | `SIDEQUESTS_BRAIN_URL` env var |
| Hard-coded OpenClaw URL | `OPENCLAW_BASE_URL` env var |
| Hard-coded OpenClaw token | `OPENCLAW_TOKEN` env var (from `.env`) |
| `REPO_ROOT` / local path assumptions | `CLAWSHOP_REPO_ROOT` env var or config discovery |
| Memory-path / Brain DB path | `SIDEQUESTS_MEMORY_PATH` env var |
| Bind host/port defaults | `MC_BIND_HOST` / `MC_BIND_PORT` env vars |
| Timezone defaults | `MC_TIMEZONE` env var |

The cleanest approach: add a `config.py` module in ClawShop's `mission-control/` that reads these from environment with sensible defaults, rather than patching server.py inline.

---

### Repo scaffold for `clawshop` (minimal first cut)

```
clawshop/
  README.md              ← "ClawShop — OpenClaw operator workbench…"
  .gitignore
  requirements.txt       ← copied/adapted from sidequests-brain requirements
  pyproject.toml         ← clawshop package identity
  pytest.ini
  Makefile
  .env.example           ← documents all env vars from the config table above
  mission-control/
    server.py
    static/
    templates/
    specs/
    config.py            ← new: centralizes env-var config
    test_*.py
    *.json               ← seed data copies
  plans/
    *.md                 ← copied boundary/bootstrap docs
  docs/
    BOUNDARY.md          ← one-paragraph note: "sidequests-brain is Brain only; this repo is the operator layer"
```

---

### Immediate next actions after this plan is accepted

1. `gh repo create clawshop --private` (or public — DJ's call)
2. Copy the extraction bundle above into a fresh local checkout
3. Add `config.py` in `mission-control/` so env vars replace hardcoded assumptions
4. Verify Mission Control tests pass in the new repo with env vars set
5. Add the boundary moratorium note to `sidequests-brain/README.md`
6. Update MC-015 kanban card to `boundary_complete / ready_for_repo_creation`

Do **not** delete the `mission-control/` directory from `sidequests-brain` until the new repo is verified running and DJ signs off on the cut.
