# Lessons Learned: Backlog Execution and Delegation Protocol

Last updated: 2026-03-28

## 1) Why this document exists

This project now uses a multi-executor delegation pattern to keep throughput high when one provider/model is rate-limited or overloaded.

Goal:
- Keep backlog execution moving continuously.
- Preserve quality and test coverage.
- Reduce context switching and avoid losing working process knowledge.

## 2) Delegation strategy (sequential distribution)

### Core rule
Work cards sequentially by dependency order, but distribute execution attempts across available CLIs/models:
- Gemini CLI
- Claude CLI (Haiku)
- Codex CLI

### Practical rotation
Use a round-robin pattern for implementation execution:
1. Card N -> Gemini
2. Card N+1 -> Haiku
3. Card N+2 -> Codex (prefer cheap model)
4. Repeat

If a CLI/model fails, retry once with same executor if error is transient.
If still failing, fail over to next executor in rotation.

### Executor failover policy
- Gemini: common failure = 429 capacity exhausted.
- Haiku (Claude CLI): may refuse direct coding if local policy files enforce delegation.
- Codex CLI: model availability depends on account entitlements and exact model IDs.

Failover order (recommended):
1. Preferred executor in rotation
2. Next executor in rotation
3. Third executor

### Model selection lessons learned
Codex CLI model IDs that were verified usable on this machine/session:
- gpt-5.1-codex-mini
- gpt-5.1-codex-max
- gpt-5.4-mini

Note:
- "codex" and "codex-mini" aliases were rejected under this account.
- Always smoke-test model IDs before relying on them for a batch.
- **Codex `exec` subcommand runs in a read-only sandbox** — it cannot write files or run pytest.
  Confirmed on 2026-03-30. Remove Codex from rotation for this project; use Gemini + Haiku only.

## 3) Agent operating rules (execution behavior)

### Non-negotiables
- Always execute work in dependency order.
- Always run targeted tests after each card implementation.
- Never mark a card complete without test evidence.
- Never revert unrelated existing workspace changes.
- Keep changes minimal and scoped to the active card plan.

### Per-card workflow
1. Read card file.
2. Read attached plan file.
3. Delegate implementation to selected executor.
4. Validate with targeted tests (and adjacent regression tests when needed).
5. If regressions are introduced:
   - fix before moving to next card
   - rerun relevant tests
6. Update card/tracker only when implementation is verified.

### Verification standards
Per card, collect:
- Changed files list.
- Test command(s) run.
- Pass/fail summary.
- Known unrelated failures (if any) explicitly separated from card scope.

## 4) Backlog card authoring criteria (.md per card)

Each backlog card file must include:
- Card ID and title (example: B61 - OpenClaw Extension: Tools Not Surfaced to Agent Without Manual Config)
- State (ready, in-progress, complete, blocked)
- Problem statement
- What it does (scope)
- Dependencies (if any)
- Files to create/modify
- Acceptance criteria (testable)
- Outcome statement

### Card quality checklist
A card is execution-ready only if:
- Scope is specific enough to be implemented without guesswork.
- Acceptance criteria are measurable.
- Dependencies are explicit.
- File targets are concrete.
- The card explicitly checks whether any tool/work changes must also be propagated to adapter allow-lists.
- If the card introduces or changes a tool, it must also include updates to docs/tool-catalog.md.
- The card complies with `docs/arc-harness-rules.md` (layer ownership, phase rules, prompt placement) and `docs/ecosystem-rules.md` (import boundaries, layer separation). Any card that touches ARC agent code must state which ecosystem layer(s) it operates in and confirm no cross-layer violations.
- **No shadow stores**: If the card introduces or modifies persistent agent state (roles, hypotheses, victory conditions, action facts, etc.), that state MUST be persisted to KuzuDB — not stored only in Python dicts or instance variables. See `docs/ecosystem-rules.md` "No shadow stores rule" for details. In-memory variables are permitted only as read-through caches over KuzuDB.

How to verify:
- Run `rg -n "TOOL_HANDLERS|TOOLS:" mcp_engine/tool_schemas.py mcp_engine/tools/__init__.py adapters` and confirm any new/changed tool is reflected in adapter allow-lists and docs/tool-catalog.md.
- Run `pytest -q tests/test_adapters.py tests/test_analogical.py tests/test_web.py`.

## 5) Plan documents (what they are)

A plan document is an implementation contract for one card.
It defines exactly how a card should be executed.

Plan location:
- backlog/plans/

Recommended plan filename:
- B-<card-number>-<slug>.md
- Examples:
  - B-61-openclaw-tools-surfacing.md
  - B-58-arc-model-strategy.md

### Required sections in a plan document
- Card metadata (ID, priority, dependencies)
- Summary
- Technical approach
- Concrete file changes
- API/schema/test updates
- Acceptance criteria
- Validation commands
- Notes on risks or constraints

## 6) How plans are attached/linked to cards

### In card file
Add a plan reference near the top:
- Plan: backlog/plans/B-XX-<slug>.md

### In tracker
In [backlog/masterBacklogTracker.md](backlog/masterBacklogTracker.md), populate:
- Matched Plan(s) column with the exact plan path(s).

### Link integrity rules
- One primary plan per card minimum.
- Multi-plan cards are allowed only when clearly split by subsystem.
- Plan path in card and tracker must match exactly.

## 7) Completion criteria for a card

A card can move to complete only when all are true:
- Implementation landed in workspace.
- Acceptance criteria validated.
- Relevant tests passing.
- No unresolved regressions introduced by this card.
- Validation note added (what was run + result summary).

## 8) Suggested execution template (copy/paste)

### Delegation prompt template
Read backlog/plans/B-XX-<slug>.md and implement exactly as specified.
Use minimal safe changes.
Preserve existing behavior outside scope.
Add/update tests for acceptance criteria.
Run relevant pytest commands and report:
- changed files
- test commands
- pass/fail summary
- regressions found/fixed

### Validation note template
Validation Note (YYYY-MM-DD):
- Implemented files: ...
- Tests run: ...
- Result: ... passed
- Regression checks: ...

## 9) Known pitfalls and safeguards

Pitfalls observed:
- Provider/model capacity throttling interrupts long bursts.
- Delegated output may claim success even when unrelated tests fail.
- Large refactors can be introduced unintentionally (scope creep).

Safeguards:
- Alternate executors between cards.
- Verify each card with direct local test runs.
- Use focused test subsets first, then broader regression where risk is higher.
- Keep card-level changes small and auditable.

## 10) Current recommended executor policy

For this repository right now:
- Use sequential card execution.
- Use round-robin delegation across Gemini, Haiku, and Codex.
- Prefer cheaper Codex model for Codex turns:
  - gpt-5.1-codex-mini
- If any executor blocks/fails, fail over immediately and continue.

This is now the default operating model for completing remaining ready cards efficiently and reliably.
