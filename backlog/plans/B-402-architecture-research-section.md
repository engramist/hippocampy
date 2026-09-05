# Plan — B402: Open Research Questions Section in ARCHITECTURE.md

## Goal

Give `docs/ARCHITECTURE.md` a place to record architectural questions that are open,
being measured, or deliberately deferred — so the source of truth distinguishes
settled design from current best guess.

## Why now

Two failures this week trace directly to the absence of this:

1. B384's `<80 MB` target was import-time-only RSS. Nobody re-derived it, so it was
   repeated into four cards and into review commentary before a warm measurement
   (818.6 MB) contradicted it.
2. The finding that `step1_ner.py` never consults the graph's SKOS `Label` layer —
   entity recognition without entity linking — currently lives in exactly one dated
   spec file that nothing links to.

Both are cases where a *known uncertainty* was invisible to the next reader.

## Steps

1. **Read `docs/ARCHITECTURE.md` first.** Match its existing heading depth, tone, and
   table conventions. Do not restructure the document.
2. Add `## Open Research Questions` after `## Patent Notice` and before
   `## Project Mission` — high enough to be seen, not competing with the mission
   statement.
3. Define the entry format in a short preamble, then a table or subsection per entry:
   Question / Status / Why it matters / Evidence / Detail link / Decision rule.
4. Populate the four seed entries listed in the card. **Copy numbers from their
   sources; do not restate from memory.** Each number states how it was measured.
5. Add the section to `## Required Companion References` at the top.
6. Add one line to `CLAUDE.md` pointing at it.

## Constraints

- **Record, do not decide.** This card changes no architectural claim. If you find a
  contradiction between the new section and existing `ARCHITECTURE.md` text, report it
  — do not silently reconcile it.
- Every number carries its methodology. A bare RSS figure with no "warm/cold" label is
  precisely the defect this section exists to prevent.
- Status values are exactly: `open`, `measuring`, `resolved`, `deferred`. A `deferred`
  entry must state the condition that would reopen it.
- Do not invent research questions. Only the four seeds, drawn from their sources.

## Verification

- Every link resolves to a file that exists.
- Every number is traceable to the card, spec, or commit it came from.
- Section is reachable from the top of `ARCHITECTURE.md` and from `CLAUDE.md`.
- `git diff` touches only `docs/ARCHITECTURE.md` and `CLAUDE.md`.
