# Gemini CLI Delegation Model

## Roles

**Opus (Senior Dev / Dev Lead):**
- Architecture decisions, strategic planning, IP protection
- Creates detailed implementation plans (`B-*.md` files)
- Reviews all code Gemini writes
- Runs tests and fixes issues
- Handles all git operations (commits, pushes, PRs)
- Vets external ideas (Gemini canvas conversations, videos, competitor analysis)

**Gemini CLI (Junior Developer):**
- Executes well-specified implementation plans
- Writes code and tests as directed
- Never commits, never pushes, never makes architectural decisions
- Works in `--yolo` mode (auto-approves all file edits)

## How It Works

### 1. Opus Creates a Plan

When implementation work is needed, Opus writes a detailed plan to a `B-*.md` file in the repo root. The plan includes:
- Exact file paths to create/modify
- Function signatures with docstrings
- Step-by-step logic for each function
- Error handling behavior
- Complete test specifications
- Implementation order (what depends on what)

### 2. Opus Delegates to Gemini

```bash
gemini -p "Read B-<plan-name>.md and implement exactly as specified. \
Read existing files first to understand patterns. \
Follow the plan precisely — every function signature, every class, every test. \
Do not skip tests. Do not simplify the plan." --yolo 2>&1
```

Run with `run_in_background: true` for tasks expected to take more than a few minutes.

### 3. Opus Reviews and Validates

After Gemini finishes:
1. Check what files were created/modified (`git diff --stat`)
2. Run the new tests (`python3 -m pytest tests/test_<feature>.py -v`)
3. Run the full test suite (`python3 -m pytest tests/ -v`)
4. Review the code for correctness against the plan
5. Fix any issues (or re-delegate to Gemini with specific fix instructions)
6. Commit when satisfied

## Sequential Multi-CLI Delegation (Mirrored Policy)

When implementation throughput is blocked by provider capacity or policy constraints, use sequential distribution across available CLI executors while preserving dependency order and validation standards.

### Core rule
- Execute cards in dependency order.
- Distribute execution attempts across available CLIs/models:
	- Gemini CLI
	- Claude CLI (Haiku)
	- Codex CLI

### Rotation
1. Card N -> Gemini
2. Card N+1 -> Haiku
3. Card N+2 -> Codex (prefer cheaper model)
4. Repeat

If executor fails:
- Retry once if transient.
- If still failing, fail over to next executor in rotation.

### Known executor failure modes
- Gemini CLI: 429 capacity exhausted.
- Haiku (Claude CLI): may defer direct implementation due local policy constraints.
- Codex CLI: some model IDs/aliases unavailable depending on account entitlements.

### Codex model notes (verified)
- Working: `gpt-5.1-codex-mini`, `gpt-5.1-codex-max`, `gpt-5.4-mini`
- Rejected in this context: `codex`, `codex-mini`, `codex-5.1-mini`

Always smoke-test model IDs before relying on them for a batch.

## Agent Execution Standards

### Non-negotiables
- Run targeted tests after each card implementation.
- Never mark a card complete without test evidence.
- Never revert unrelated existing workspace changes.
- Keep changes minimal and scoped to the active card and plan.
- If regressions are introduced, fix them before advancing.

### Per-card checklist
1. Read card markdown.
2. Read attached plan markdown.
3. Delegate implementation to selected executor.
4. Validate with focused tests.
5. Run adjacent regression tests when risk is elevated.
6. Record changed files + tests + results.
7. Update tracker/card state only after verification.

## Backlog Card Authoring Criteria (Execution-Ready)

Each card markdown (`backlog/B*.md`) should include:
- Card ID and title
- State (`ready`, `in-progress`, `complete`, `blocked`)
- Problem statement
- Scope (`What it does`)
- Dependencies
- Files to create/modify
- Acceptance criteria (measurable)
- Outcome statement

Card quality gate:
- No ambiguity in scope
- Explicit dependencies
- Concrete file targets
- Testable acceptance criteria

## Plan Document Contract

Plan files live in `backlog/plans/` using:
- `B-<card-number>-<slug>.md`

Each plan should include:
- Card metadata (ID, priority, dependencies)
- Summary
- Technical approach
- Concrete file changes
- API/schema/test updates
- Acceptance criteria
- Validation commands
- Risk/constraint notes

## Card <-> Plan Linking Rules

### In card file
Add near top:
- `Plan: backlog/plans/B-XX-<slug>.md`

### In tracker
In `backlog/masterBacklogTracker.md`:
- Populate `Matched Plan(s)` with exact path(s).

Link integrity:
- Minimum one primary plan per card
- Multi-plan cards allowed only when intentionally split by subsystem
- Paths in card and tracker must match exactly

## Completion Criteria (Before Marking Complete)

Card can move to `complete` only if:
- Implementation landed
- Acceptance criteria validated
- Relevant tests passing
- No unresolved regressions introduced by the card
- Validation note added (tests run + pass/fail)

## Delegation Prompt Template

Use this baseline prompt for any executor:

```
Read backlog/plans/B-XX-<slug>.md and implement exactly as specified.
Use minimal safe changes.
Preserve existing behavior outside scope.
Add/update tests for acceptance criteria.
Run relevant pytest commands and report:
- changed files
- test commands
- pass/fail summary
- regressions found/fixed
```

## Validation Note Template

```
Validation Note (YYYY-MM-DD):
- Implemented files: ...
- Tests run: ...
- Result: ... passed
- Regression checks: ...
```

## Prerequisites

- Gemini CLI installed: `npm install -g @google/gemini-cli`
- Gemini CLI authenticated: `gemini` (interactive, first run)
- Gemini CLI trusted for this project: `gemini trust` (run once per project folder)
- Verify: `which gemini && gemini --version`

## Proven Results

| Task | Plan File | Lines Written | Tests | Result |
|------|-----------|--------------|-------|--------|
| B13 Installer | `B-install-plan.md` | 1,353 (858 + 495) | 38/38 passing | First run success |

## Tips

- **Be extremely specific in plans.** Gemini executes literally — ambiguity leads to wrong assumptions.
- **Include existing file paths** so Gemini reads current patterns before writing.
- **Separate plan creation from delegation.** Opus creates the plan, gets DJ's approval, then delegates.
- **Use `--yolo` always.** Gemini needs auto-approval to write files without hanging on prompts.
- **Check Gemini's output tail** for self-corrections — it sometimes fixes its own mistakes during execution.
- **Never let Gemini make architectural decisions.** If it encounters an ambiguity, it should be in the plan, not improvised.

## When NOT to Use Gemini

- Architecture decisions or design discussions
- Vetting external ideas or competitor analysis
- Code review (Opus reviews Gemini's output, not the other way around)
- Git operations (commits, pushes, branch management)
- Security-sensitive changes (auth, key handling, path validation)
- Changes that touch IP-protected algorithms (Gated Consolidation Loop steps)
