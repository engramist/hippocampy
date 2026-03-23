# MC-016 — ClawShop inventory slice 1

Scope: first concrete inventory slice for the planned ClawShop bootstrap.

This slice is intentionally narrow: Mission Control plus the immediately adjacent planning files already referenced by MC-015/017. It does not change the repo-boundary decision; it just turns the first cut into an explicit file/folder list.

## Slice A — `mission-control/`

### Move as source code / product surface
- `mission-control/server.py`
- `mission-control/static/`
- `mission-control/templates/`
- `mission-control/specs/`
- `mission-control/test_hardening.py`
- `mission-control/test_mc006b_handles.py`
- `mission-control/test_mc020_risk_ui.py`
- `mission-control/test_mc023_discord_hooks.py`

### Copy as seed runtime data, then let ClawShop own/update
- `mission-control/kanban.json`
- `mission-control/digest.json`
- `mission-control/activity-feed.json`

### Exclude / regenerate
- `mission-control/__pycache__/`

## Slice B — planning/docs that directly bootstrap the first cut

### Copy into `clawshop/plans/`
- `plans/B-mission-control.md`
- `plans/MC-durable-workflow.md`
- `plans/MC-015-clawshop-repo-split.md`
- `plans/MC-017-clawshop-bootstrap-checklist.md`
- `plans/MC-016-clawshop-inventory-slice-1.md`

## Immediate blocker surfaced by this slice

The first ClawShop cut can copy the files above now, but `mission-control/server.py` still needs config externalization before the new repo can be treated as portable. The known first-pass config seam remains:
- Brain URL
- OpenClaw URL
- OpenClaw token
- repo-root / memory-path assumptions
- bind host/port and timezone defaults

## Why this slice matters

This gives MC-015 a concrete starting bundle for the first repo cut:
1. one product directory to extract,
2. three seed state files to copy intentionally,
3. one explicit junk directory to skip,
4. five plan files to carry into the new repo as context.
