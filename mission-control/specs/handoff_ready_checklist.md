# Handoff Ready Checklist

A card is **handoff_ready** only if the next implementing agent can execute without relying on chat history.

## Required checklist items

- `context_ready` — Why this card exists is written down clearly
- `scope_ready` — Exact implementation slice is defined
- `spec_ready` — Spec/doc path is linked if rules/schema matter
- `guardrails_ready` — Constraints / approval boundaries are explicit
- `acceptance_ready` — Definition of done is concrete
- `execution_ready` — Current worker/run/job state is recorded if active
- `routing_ready` — Success/failure routing is explicit

## Rule

A card should not be assigned for implementation unless all required checklist items are true.

## Exceptions

Lightweight cards may omit `spec_ready` if no separate spec is needed, but the card notes must still contain the equivalent guidance.

## Operational meaning

If `handoff_ready = false`:
- Claws must normalize the handoff first
- do not launch implementation worker yet

If `handoff_ready = true`:
- Claws may launch implementation
- worker prompt must reference the card and any linked spec paths
