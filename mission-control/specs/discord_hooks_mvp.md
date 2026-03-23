# MC-023 — Discord hook MVP

## What landed

Mission Control now has a **Discord hook planning layer** in `mission-control/server.py`.

MC-025 adds a **first real write adapter path** on top of that planning layer:
- `POST /api/discord/execute/{task_id}` executes the derived hook plan for one card
- dry-run is the default, so the adapter is safe to verify without Discord side effects
- live posting is gated behind `MISSION_CONTROL_DISCORD_ENABLE_WRITES=1`
- returned Discord ids are written back onto the Mission Control card so the board stays source of truth

## Current behavior

### 0. Real adapter execution path (MC-025)

`POST /api/discord/execute/{task_id}` now runs the same derived hook plan Mission Control previews.

Request body:
- `dry_run` — optional, defaults to `true`
- `signal` — optional, lets the executor compute the same completion-oriented plan a caller just triggered

Live mode requirements:
- `MISSION_CONTROL_DISCORD_ENABLE_WRITES=1`
- `MISSION_CONTROL_DISCORD_BOT_TOKEN`
- channel ids for the top-level destinations:
  - `MISSION_CONTROL_DISCORD_CHANNEL_MISSION_CONTROL`
  - `MISSION_CONTROL_DISCORD_CHANNEL_BLOCKED_DECISIONS`
  - `MISSION_CONTROL_DISCORD_CHANNEL_SHIP_LOG`
  - `MISSION_CONTROL_DISCORD_CHANNEL_WORK_INTAKE` (reserved/not used by current plan)

What the live adapter can do in this first slice:
- create or update anchor posts
- create a thread off the anchor post when the plan says one is needed and the card does not already have a stored thread id
- create or update blocker posts
- create or update completion posts
- send the anchor resolution reply for completed cards
- persist returned Discord ids/state back to the card metadata in `kanban.json`

Persisted fields in live mode:
- `discord_anchor_channel`
- `discord_anchor_message_id`
- `discord_thread_id`
- `discord_thread_state`
- `discord_blocked_message_id`
- `discord_shiplog_message_id`

### 1. Anchor post planning
For meaningful cards, Mission Control can now generate an anchor-plan payload for `#mission-control`.

The payload includes:
- create vs update mode
- channel name
- title/body text
- whether a thread is recommended
- suggested thread name

Heuristics:
- implementation cards default to thread-needed
- critical cards default to thread-needed
- blocked/running/under_review cards default to thread-needed
- explicit `discord_thread_needed` overrides the heuristic

### 2. Blocker routing planning
For blocked cards, Mission Control now generates a blocker-plan payload for `#blocked-decisions`.

The payload includes:
- create vs update mode
- blocker summary body
- waiting_on / next_event / next_check_at context

### 3. Completion planning
For completed cards, Mission Control now generates a completion-plan payload for `#ship-log`.

If the card already has an anchor message id, the plan also includes an anchor reply suggestion so the top-level thread can be closed out cleanly.

## New card metadata fields

These fields are now accepted on Mission Control cards:
- `discord_anchor_channel`
- `discord_anchor_message_id`
- `discord_thread_id`
- `discord_thread_needed`
- `discord_thread_state`
- `discord_blocked_message_id`
- `discord_shiplog_message_id`

These metadata fields are now populated by the live adapter path when `POST /api/discord/execute/{task_id}` runs in live mode.
They can still be previewed or left untouched in dry-run mode.

## New API surface

### `GET /api/discord/plan/{task_id}`
Returns the current Discord hook plan for a card.

Use this to:
- preview what would be posted
- drive a future Discord bot/adapter
- validate the policy without external side effects

### `POST /api/workflow/signal`
Now returns `discord_hooks` in the JSON response after the workflow state transition is applied.

This means a Discord adapter can:
1. send a Mission Control workflow signal
2. read back the recommended Discord actions
3. either execute them directly via its own caller logic or hand the card to `POST /api/discord/execute/{task_id}`

## Why this slice is safe

Mission Control remains the source of truth.
Discord behavior is still derived output.

This MVP + first live slice adds:
- policy heuristics
- message rendering
- previewable API outputs
- a dry-run-first live execution endpoint
- Discord REST posting for anchor/blocker/completion/reply actions
- thread creation for anchor posts when needed
- persistence of returned Discord ids back into card metadata

It does **not** yet add:
- archive/cleanup jobs
- reconciliation against Discord state
- delete/close behavior for stale blocker posts or archived threads

## MC-028 live path

`POST /api/workflow/signal` can now auto-execute the derived Discord hook plan in live mode immediately after the workflow state change is written.

Auto-execution is intentionally opt-in and requires **both**:
- `MISSION_CONTROL_DISCORD_AUTO_EXECUTE=1`
- a fully ready live adapter config (`MISSION_CONTROL_DISCORD_ENABLE_WRITES=1`, bot token, and channel ids)

When auto-execution is not ready, the workflow signal still succeeds and now returns a precise `discord_execution` status object naming the missing config keys. That makes the remaining blocker explicit instead of leaving Discord in a vague half-wired state.

## What remains manual

Still manual / not yet automatic:
- deciding when to call the live executor after a workflow signal
- provisioning and wiring the Discord bot token + channel ids in each environment
- archiving/locking threads after completion
- reconciling Mission Control metadata against Discord if someone edits/deletes posts manually

## Recommended next slice

Build the automation around the new executor path:
1. trigger `POST /api/discord/execute/{task_id}` automatically from the workflow-signal caller path once environment wiring is trusted
2. add idempotency / dedupe so repeated signals do not create duplicate completion replies
3. add reconciliation for edited/deleted Discord posts and archived threads
4. optionally move stored Discord state from flat card fields into a clearer per-surface status object if the integration grows
