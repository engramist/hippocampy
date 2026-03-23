# MC-022 — Discord manual rollout playbook

Purpose: turn the approved MC-021 Discord operating model into a small, repeatable manual workflow that can be used immediately before deeper automation is fully relied on.

Source model: `plans/MC-021-discord-operating-model.md`

## 1. Create the top-level channels

Create exactly these channels first:
- `#mission-control`
- `#work-intake`
- `#blocked-decisions`
- `#ship-log`

Use them as follows:
- `#mission-control` = active card anchors + major state changes
- `#work-intake` = rough asks before/while becoming cards
- `#blocked-decisions` = explicit blockers, approvals, missing info, decisions needed
- `#ship-log` = low-noise completions and milestones

## 2. Post one anchor per meaningful active card

When a card becomes real active work, post one anchor message in `#mission-control`.

Post an anchor when the card is:
- `in_progress`, or
- high priority / visible, or
- assigned for real work, or
- likely to need coordination or multiple updates

Skip the anchor for tiny backlog/admin cards.

### Anchor template

```text
[MC-022] Roll out Discord operating model manually in Mission Control workflow
Owner: Claws
Phase: implementation
Priority: critical
Goal: make the approved Discord operating model usable immediately via a manual playbook.
Next: create channels, post anchor, and use per-card threads only when warranted.
Thread: not created yet
Artifact: plans/MC-022-discord-manual-rollout-playbook.md
```

## 3. Decide thread vs no thread

Default rule: do not create a thread unless the card needs ongoing conversation.

Create a thread when the card is:
- active implementation work
- expected to need multiple updates
- a handoff
- blocked and likely to need back-and-forth
- critical / high-visibility coordination

Do not create a thread when the card is:
- a tiny one-shot
- likely to finish in one update
- only bookkeeping

### Thread creation steps

1. Start from the anchor post in `#mission-control`
2. Name the thread: `[CARD-ID] short working title`
3. In the first thread message, paste:
   - one-line goal
   - current owner
   - current next event
   - Mission Control card/detail link or path reference
4. Keep ongoing card discussion in that thread until done or unblocked

### Thread naming examples
- `[MC-021] Discord workflow rollout`
- `[MC-022] Manual rollout playbook`
- `[MC-028] Discord last mile`

## 4. Keep top-level channel noise low

Use the thread for detailed work updates.

Only post back into `#mission-control` when there is a meaningful state change:
- thread created
- owner changed
- phase changed
- blocked / unblocked
- major milestone
- completed

## 5. Route blockers explicitly

When a card is blocked:

1. Update Mission Control first:
   - `phase=blocked`
   - `waiting_on`
   - `next_event`
   - `next_check_at`
   - blocker notes
2. Post/update the blocker in the card thread if one exists
3. If action or attention is needed, post in `#blocked-decisions`

### Blocker template

```text
[BLOCKED][MC-022] Need exact server/channel creation owner and rollout time
Waiting on: DJ or operator
Impact: manual rollout cannot be completed cleanly in Discord yet
Next check: <time>
Context: see MC-022 anchor/thread and playbook artifact
```

Important rule: do not create a new blocker-only thread for a card that never needed a thread. Use `#blocked-decisions` as the shared queue.

## 6. Post completions consistently

When a card completes:

1. Update Mission Control first
2. Post a concise summary in `#ship-log`
3. Optionally add a short close-out note in `#mission-control`
4. Add a final note in the card thread if one exists

### Completion template

```text
[DONE][MC-022] Discord manual rollout playbook added
Owner: Claws
Result: created the manual channel/thread/blocker/completion checklist for immediate use
Artifact: plans/MC-022-discord-manual-rollout-playbook.md
Follow-on: MC-023 / MC-028 can automate the same flow
```

## 7. Operator checklist for first live rollout

Use this checklist the first time the model is run manually:

- [ ] Create the four top-level channels
- [ ] Pick one active card to pilot from `#mission-control`
- [ ] Post its anchor message
- [ ] Decide whether it needs a thread using the rules above
- [ ] If yes, create thread named `[CARD-ID] short working title`
- [ ] Put all detailed updates in the thread
- [ ] If blocked, mirror the blocker to `#blocked-decisions`
- [ ] When complete, post summary to `#ship-log`
- [ ] Leave Mission Control as the source of truth if Discord and board state diverge

## 8. Tight scope boundary

This playbook is intentionally manual and operational.

It does not redesign the Discord model.
It does not depend on auto-posting being live.
It exists so the approved MC-021 model can be run immediately and consistently while MC-023/MC-028 continue the automation path.
