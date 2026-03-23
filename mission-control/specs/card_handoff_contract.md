# Card Handoff Contract

## Purpose

Every card that changes owner or phase must carry enough context for the next agent to execute without relying on chat history.

The card is the execution handoff package.

## Required Handoff Contents

Each implementation-ready card should include:

- **Context** — why this card exists / parent relationship
- **Scope** — exactly what to build or decide
- **Spec path** — file(s) that define schema/rules/requirements
- **Guardrails** — what not to do / approval boundaries
- **Acceptance criteria** — how we know it is done
- **Execution notes** — current worker/job/run state
- **Next-step semantics** — what happens on success/failure

## Minimum Structured Fields on the Card

Use card fields where possible:

- `phase`
- `execution_mode`
- `waiting_on`
- `next_event`
- `next_check_at`
- `on_success`
- `on_failure`
- `escalate_to`
- `run_ref`
- `job_ref`

## Required Note Sections

Cards that are implementation-ready should have notes that clearly cover:

### Context
- parent card / why this exists
- relevant background in one short paragraph

### Scope
- exact implementation slice
- what is in scope and out of scope

### Spec / References
- repo paths to specs/docs
- relevant code paths if known

### Guardrails
- approval boundaries
- no-inference / no-autonomy limits if applicable

### Definition of Done
- concrete verification conditions
- tests/checks/endpoints to confirm

### On Success / On Failure
- next routing expectation
- who owns escalation

## Agent Responsibility

### The reviewing/specifying agent must:
- put the implementation guidance on the card or linked spec
- not leave critical context only in Discord/chat

### Claws must:
- normalize handoff context onto the card before assignment
- ensure the worker prompt references the card + spec path
- refuse to treat a card as implementation-ready if the handoff is vague

### The implementing agent must:
- read the card and referenced spec(s)
- update the card notes if new execution-relevant discoveries appear
- leave a result that is useful for the next phase

## Non-Negotiable Rule

If the important implementation context exists only in chat and not on the card/spec, the handoff is incomplete.

Do not assign implementation from incomplete handoff context.
