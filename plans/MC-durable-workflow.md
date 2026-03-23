# MC-Durable-Workflow — Claws as Mission Control Orchestrator

## Purpose

Mission Control should behave like a lightweight durable workflow engine for cards, not just a passive kanban board.

Claws is the orchestrator.
Each card is a workflow instance.
The board is the visible state, not the source of truth.

## Core Principle

A card is not "moving" because it has an assignee.
A card is moving because it has:
- an owner
- an active or scheduled worker
- a current wait condition
- a next event or timer
- a defined success transition
- a defined failure transition

## Roles

### Claws
Owns orchestration, routing, follow-up, state transitions, and first-pass diagnosis.

### Crusty
CTO authority. Owns:
- architecture decisions
- deep/system debugging
- bugs that imply design or workflow changes
- review of risky technical direction

### Gemini
Execution engine. Owns:
- coding
- implementation
- research
- tests
- repetitive or parallel heavy lifting

Multiple Gemini runs may exist at once.

## Card = Workflow Instance

Each card should be treated as a workflow object with durable state.

### Required Workflow Fields

Minimum fields each active card should carry in structured form or note discipline:

- `id`
- `title`
- `phase`
- `owner`
- `execution_mode`
- `run_ref`
- `job_ref`
- `waiting_on`
- `next_event`
- `next_check_at`
- `on_success`
- `on_failure`
- `escalate_to`
- `last_signal_at`
- `status_note`

## Phases

Recommended card phases:

1. `backlog`
2. `assigned`
3. `running`
4. `waiting`
5. `under_review`
6. `blocked`
7. `completed`
8. `failed`

For the current kanban board, these may be projected into the existing board columns:

- `backlog` -> backlog
- `assigned` / `running` / `waiting` -> in_progress
- `under_review` -> under_review
- `completed` -> completed
- `blocked` / `failed` -> either backlog with blocker note or a future dedicated blocked column

## Execution Modes

A card in motion must have one execution mode:

- `claws_direct`
- `crusty_scheduled`
- `crusty_active`
- `gemini_active`
- `gemini_parallel`
- `review_wait`
- `external_wait`
- `cron_wait`

If no execution mode exists, the card is not truly active.

## Event Model

Each card waits on an event.

### Valid Event Types

- `worker_started`
- `worker_progress`
- `worker_completed`
- `worker_failed`
- `worker_needs_input`
- `review_requested`
- `review_approved`
- `review_rejected`
- `timer_expired`
- `cron_completed`
- `cron_failed`
- `manual_reassign`
- `manual_pause`

### Event Sources

- exec/process completion
- cron run completion/failure
- subagent completion event
- commit landed
- digest/activity post landed
- explicit user instruction
- manual board action

## Transition Rules

### Assign
When a card is assigned:
1. choose owner by strengths
2. start worker immediately or schedule it immediately
3. write wait condition
4. set next check

Assigned-without-worker is invalid.

### Running -> Waiting
When a worker starts and is executing asynchronously:
- set `phase=waiting`
- set `waiting_on=worker_completed|worker_failed|worker_needs_input`
- set `run_ref` or `job_ref`
- set `next_check_at`

### Waiting -> Under Review
When execution completes and review is needed:
- move to `under_review`
- set `waiting_on=review_approved|review_rejected`
- write review summary

### Waiting -> Completed
When execution completes with no review needed:
- move to `completed`
- capture result
- close the loop

### Waiting -> Blocked
When execution fails or stalls:
- run first-pass diagnosis
- write concrete blocker
- route next owner
- set next event/timer

## Failure Handling

Claws always does first-pass diagnosis.

### Route to Crusty if failure is:
- architecture-shaped
- system/debugging-shaped
- risk-bearing
- design-changing
- unclear after first diagnosis

### Route to Gemini if failure is:
- concrete implementation bug
- test failure with clear target
- scoped patch or research task
- parallelizable execution work

## Timers and Durability

Every active card must have a timer/checkpoint.

Examples:
- Gemini implementation run -> check in 15–30 min
- Crusty review -> check after next scheduled run
- review wait -> check after reviewer SLA
- cron-owned card -> check after next cron event

Timer expiry is itself an event.
When a timer expires with no progress signal, Claws must act.

## Definition of Motion

A card is moving only if all are true:
- correct owner
- active/scheduled worker exists
- current wait condition exists
- next event or timer exists
- success/failure path exists

Otherwise it is stale and must be corrected.

## Durable Workflow Loop for Claws

For every active card:

1. inspect current phase
2. inspect current wait condition
3. inspect latest signal/event
4. if event arrived, transition state
5. if timer expired without event, intervene
6. if failure, diagnose and reroute
7. write updated status back to Mission Control
8. set the next wait condition

## Practical Implementation Plan

### Phase 1 — Operating Discipline (now)
- enforce notes/checkpoints on all active cards
- recurring board audit job
- require worker launch after assignment
- capture run refs where possible

### Phase 2 — Structured Workflow Metadata
Extend `mission-control/kanban.json` task objects with workflow metadata:
- `phase`
- `execution_mode`
- `run_ref`
- `job_ref`
- `waiting_on`
- `next_event`
- `next_check_at`
- `on_success`
- `on_failure`
- `escalate_to`
- `last_signal_at`

### Phase 3 — Event-Driven Transition Automation
Teach Mission Control to react to:
- exec/process completion
- cron success/failure
- activity/digest writes
- manual approval/rejection

### Phase 4 — UI Support
Mission Control should surface:
- current wait condition
- next event
- next check time
- stale/healthy workflow status
- blocked reason

## Current Active Card Expectations

### B29
- owner: Crusty
- mode: `crusty_scheduled`
- wait: next Crusty work-session result
- success: concrete path defined or implementation delegated
- failure: split blocker and escalate/support with Gemini

### MC-002
- owner: Crusty
- mode: `crusty_scheduled`
- wait: digest reliability result
- success: digest path verified/fixed
- failure: concrete bugfix card created

### MC-003
- owner: Gemini
- mode: `gemini_active`
- wait: Gemini run completion/failure
- success: activity board fixed and card advanced
- failure: Claws diagnoses and routes to Crusty if systemic

### MC-004
- owner: Claws
- mode: `claws_direct`
- wait: recurring audits + workflow hygiene updates
- success: no fake in-progress cards
- failure: tighten policy and transitions

### MC-005
- owner: Claws
- mode: `claws_direct`
- wait: workflow model adoption into board/server
- success: Mission Control behaves like durable orchestration
- failure: escalate implementation design to Crusty

## Non-Negotiable Rule

Claws owns the transition logic.

Not just:
- assign card
- wait
- notice later

But:
- assign
- launch
- wait on event
- transition
- launch next step
- diagnose failures
- reroute
- repeat until complete
