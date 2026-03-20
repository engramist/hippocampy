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
