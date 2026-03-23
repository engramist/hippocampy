# MC-021 — Discord operating model for Mission Control

## Goal

Use Discord as the day-to-day operating surface for Mission Control **without** creating one permanent channel per card.

The model is:
- a small set of top-level channels for shared flow,
- optional per-card threads for work that needs ongoing conversation,
- clear posting rules so cards stay visible without creating channel sprawl.

## Canonical channel set

### `#mission-control`
Primary stream for active work.

Use for:
- new card announcements,
- status changes for important cards,
- links to card threads,
- operator coordination around active work.

### `#work-intake`
Where new asks, rough ideas, bugs, and requests land before or while becoming cards.

Use for:
- user/operator requests,
- “should this become a card?” discussion,
- lightweight triage,
- intake forms or slash-command output later.

### `#blocked-decisions`
Single place for blockers, approvals, missing info, and decisions that need attention.

Use for:
- cards that are blocked on DJ,
- cards blocked on Crusty/another agent,
- dependency waits,
- explicit decision requests.

### `#ship-log`
Low-noise completion and milestone feed.

Use for:
- card completed,
- deployed/fixed/merged summaries,
- notable automated chain completions later.

## Core rule

**Cards live in Mission Control; Discord mirrors and supports the work.**

Discord is the conversation surface. Mission Control remains the source of truth for:
- card fields,
- status/phase,
- owner,
- waiting_on / next_event / next_check_at,
- execution handles,
- final notes.

## Thread policy

### Create a per-card thread when any of these are true
- the card is active implementation work,
- the card will likely generate multiple updates,
- the card needs handoff discussion,
- the card is blocked and the blocker needs back-and-forth,
- the card is high priority / high visibility,
- the card involves coordination across people or agents.

### Do **not** create a thread when
- the card is a tiny one-shot task,
- the update is likely a single post plus completion,
- the card is purely bookkeeping,
- the answer is immediate and no follow-up discussion is expected.

### Default heuristic
- **If in doubt, start without a thread.**
- Create the thread on the **second meaningful update**, or immediately for critical / complex cards.

This keeps the system lightweight while preserving room for deeper discussion.

## Naming conventions

### Main card post title/body format
Every important card announcement in `#mission-control` should start with:

`[MC-021] Design Discord operating model for card-based work without channel sprawl`

Recommended body fields:
- status/phase
- owner
- priority
- short objective
- next event
- link to Mission Control card/detail view

### Thread name format
Use:

`MC-021 · short-slug`

Examples:
- `MC-021 · discord-model`
- `MC-014 · detail-panel`
- `B29 · cross-session-context`

Rules:
- always start with the card ID,
- keep slug short and readable,
- do not include status in the thread name,
- rename only if the card meaning materially changes.

### Blocker post title format
In `#blocked-decisions`:

`[BLOCKED][MC-021] Need decision on thread auto-creation rules`

### Completion post title format
In `#ship-log`:

`[DONE][MC-021] Discord operating model spec drafted`

## Operational workflow

## 1) Card created
A card is created in Mission Control from intake, triage, or follow-on chaining.

### Discord action
Post a main summary in `#mission-control` when the card is:
- in progress,
- important,
- assigned for real work,
- likely to need coordination.

No Discord post is required yet for tiny backlog/admin cards.

### Initial card post template
- card ID + title
- owner
- phase/status
- why it exists
- whether a thread exists yet
- what the next event is

Example:

```text
[MC-021] Design Discord operating model for card-based work without channel sprawl
Owner: Claws
Phase: implementation
Priority: critical
Goal: define a lightweight Discord workflow using a few channels + optional per-card threads.
Next: codify channel/thread/posting rules.
Thread: not created yet
```

## 2) Decide whether to create a thread
At card creation time, decide thread/no-thread using the policy above.

### If no thread
Keep updates in the main `#mission-control` post or as reply-chain updates if supported by the client workflow.

Use this for:
- one-shot fixes,
- small documentation tasks,
- quick operator notes.

### If yes, create thread
Create a thread from the main `#mission-control` card post.

The main post becomes the anchor. The thread becomes the working room.

### First thread message should contain
- one-line restatement of the goal,
- current owner,
- current plan / checklist,
- any dependencies,
- link back to the card detail.

## 3) Working updates while active

### In the thread
Put detailed updates in the per-card thread:
- progress notes,
- implementation discussion,
- handoffs,
- intermediate findings,
- pasted evidence / logs / decisions.

### In `#mission-control`
Only post when there is a meaningful state change, such as:
- thread created,
- owner changed,
- phase changed,
- blocked/unblocked,
- major milestone reached,
- card completed.

This keeps the top-level channel readable.

## 4) Blocker handling
When a card becomes blocked:

### First
Update the card in Mission Control:
- `phase: blocked`
- `waiting_on`
- `next_event`
- `next_check_at`
- blocker notes

### Then in Discord
- add a concise blocker update in the card thread if one exists,
- post an explicit blocker summary in `#blocked-decisions` if action/attention is needed.

### Blocker post should include
- card ID + title,
- who/what it is waiting on,
- exact decision or dependency,
- impact if delayed,
- next check time,
- link to the thread/card.

Example:

```text
[BLOCKED][MC-021] Need decision on whether small cards ever auto-thread
Waiting on: DJ
Impact: cannot finalize the default automation rules
Next check: today 12:30 PM MDT
Context: see MC-021 thread
```

### Thread behavior for blocked cards
- keep the existing thread if the card already has one,
- do **not** create a new blocker-only thread if the card never warranted a thread,
- use `#blocked-decisions` as the cross-card decision queue.

## 5) Completion posting
When a card is completed:

### First
Update Mission Control to completed with final notes.

### Then in Discord
- post a concise completion summary in `#ship-log`,
- optionally add a closing reply in `#mission-control`,
- add final context in the card thread if one exists.

### Completion post should include
- card ID + title,
- what changed,
- owner,
- any artifact/PR/commit/spec link,
- whether there is follow-on work.

Example:

```text
[DONE][MC-021] Discord operating model spec drafted
Owner: Claws
Result: documented channel layout, thread rules, blocker flow, and completion flow
Artifact: plans/MC-021-discord-operating-model.md
Follow-on: automation hooks can be split into implementation cards
```

### Thread close behavior
When complete:
- leave the thread as the historical record,
- optionally archive after a quiet period,
- do not delete unless there is a moderation/privacy reason.

## Lightweight operating rules

### Rule 1: one anchor post per meaningful card
A card should have one main post in `#mission-control`, not multiple disconnected announcements.

### Rule 2: threads are workrooms, not permanent lanes
Threads exist only when useful.

### Rule 3: blocked work gets surfaced in one shared place
`#blocked-decisions` is the queue for attention, not a scattering of hidden thread-only blockers.

### Rule 4: completion goes to a low-noise feed
`#ship-log` should be easy to skim later.

### Rule 5: Mission Control remains canonical
If Discord and the board disagree, fix the board first, then post corrections.

## Suggested posting matrix

| Event | Channel | Thread? | Notes |
|---|---|---:|---|
| New important card created | `#mission-control` | Optional | Create anchor post |
| Tiny one-shot card created | none or `#mission-control` | No | Skip noise if trivial |
| Active implementation begins | `#mission-control` | Usually yes | Thread for multi-update work |
| Routine progress update | thread | Yes | Keep top-level clean |
| Owner/phase change | `#mission-control` | Optional | Summary-level update |
| Blocker discovered | thread + `#blocked-decisions` | If thread exists | Cross-card attention goes to blocked channel |
| Decision resolved | thread + optional `#mission-control` | Optional | Post top-level only if it materially changes status |
| Card completed | `#ship-log` + optional `#mission-control` | Optional | Thread gets final note |

## Automation hooks to add later

This design should work manually first. Later automation can make it smoother.

### Hook 1: card-created announcement
When a card enters active work (`in_progress` / assigned / high priority), automatically post the anchor message to `#mission-control`.

Needed data:
- card ID
- title
- owner
- phase
- priority
- next event
- card URL

### Hook 2: optional auto-thread creation
Add policy-driven thread creation when:
- card priority is critical, or
- card_type is implementation, or
- phase implies active execution, or
- explicit `discord_thread_needed: true` is set.

Important: keep a manual override so not every active card gets a thread.

Potential metadata to add later:
- `discord_anchor_channel`
- `discord_anchor_message_id`
- `discord_thread_id`
- `discord_thread_needed`
- `discord_thread_state`

### Hook 3: blocker mirroring
When a card changes to blocked and `waiting_on` is set:
- post/update a blocker message in `#blocked-decisions`,
- include next check time and requested decision,
- link back to the anchor/thread.

Potential metadata:
- `discord_blocked_message_id`
- `blocked_summary`
- `decision_needed_from`

### Hook 4: completion mirroring
When a card moves to completed:
- post to `#ship-log`,
- optionally post a short resolution reply in the anchor thread/post,
- mark thread ready for archive.

Potential metadata:
- `discord_shiplog_message_id`
- `discord_completed_at`

### Hook 5: thread summary refresh
For longer-running cards, periodically update the anchor post or thread opener with:
- current owner,
- phase,
- latest checkpoint,
- latest blocker.

This avoids needing to read the full thread to know current state.

## Recommended MVP

Start with this manual + lightweight model:
1. create the four top-level channels,
2. post one anchor message in `#mission-control` for each meaningful active card,
3. create threads only for complex/high-signal cards,
4. route all explicit blockers to `#blocked-decisions`,
5. post all completions to `#ship-log`,
6. keep Mission Control as source of truth.

Then add automation in this order:
1. anchor post creation,
2. blocker mirroring,
3. completion posting,
4. optional thread creation,
5. thread-summary refresh.

## Concrete recommendation for MC-021

Adopt the following default policy now:
- **Top-level channels:** `#mission-control`, `#work-intake`, `#blocked-decisions`, `#ship-log`
- **Per-card threads:** only for active/significant cards
- **Anchor post:** yes, for meaningful active cards
- **Tiny cards:** no thread by default
- **Blocked cards:** visible in `#blocked-decisions`
- **Completed cards:** summarized in `#ship-log`

That gives a simple, durable operating model with minimal channel sprawl and a clear path to future automation.
