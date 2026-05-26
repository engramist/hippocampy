# Cross-Agent Skill Distribution

## Context

The Layer 4 deep integration (commit `6f75cabf`) consolidated 12 skills into `plugin/skills/` — they auto-install with the Campy Claude Code plugin. But Codex gets only 1 skill (`campy-memory`), Gemini CLI gets 0 skills (just GEMINI.md text injection), and VS Code Copilot gets a single recall block in `copilot-instructions.md`.

**Problem:** Non-Claude-Code users miss all 12 process and memory skills. Codex users can't `/grill`, `/diagnose`, or `/tdd`. Gemini CLI users get zero skill files. VS Code Copilot users only get a basic recall protocol.

**Solution:** Update the plugin installer to copy all 12 skill directories (with companion files) to each platform's native skill location. Single source of truth (`plugin/skills/`), platform-specific destinations.

## Design

### Platform skill locations

| Platform | Skill directory | Before | After |
|---|---|---|---|
| Claude Code | `~/.claude/plugins/hippocampy/skills/<name>/` | All 12 | No change |
| Codex | `~/.codex/skills/<name>/` | 1 (`campy-memory`) | All 12 |
| Gemini CLI | `~/.gemini/skills/<name>/` | 0 | All 12 |
| VS Code Copilot | `.github/copilot-instructions.md` | 1 recall block | All 12 skill summaries |

### Install strategy

All platforms use the same source: `plugin_dir / "skills"` (resolved by `find_plugin_dir()`).

**Codex and Gemini:** Full `copytree` of all 12 skill directories into the platform's skill folder. Each skill gets its own subdirectory with SKILL.md and all companion files.

**VS Code Copilot:** Copilot doesn't have a skills directory. Expand the existing `_add_copilot_recall_instructions()` in `register.py` to inject all 12 skill summaries (name + description + trigger) into `.github/copilot-instructions.md`. Keep it compact — full skill content lives in the MCP tools; the instructions file just tells Copilot what's available and when to suggest each skill.

### Shared helper

Extract `_copy_skills_tree(plugin_dir, target_skills_dir)` — shared by Claude Code, Codex, and Gemini installers. Does `rmtree(target)` then `copytree(source/skills, target)`.

### Legacy cleanup

- `install_codex_memory_skill()` in `register.py` currently copies a single skill. After the full installer runs, the old `~/.codex/skills/campy-memory/` directory becomes redundant (replaced by `~/.codex/skills/memory-awareness/` and `~/.codex/skills/recall/`). The installer should remove it.
- Gemini CLI's GEMINI.md injection in `register.py` stays for backward compat but is supplementary — the skills directory is the primary source.

## Implementation

### Files to modify (2)

| File | Change |
|---|---|
| `campy/cli/plugin_installer.py` | Extract `_copy_skills_tree()` helper; rewrite `install_codex_plugin()`; rewrite `install_gemini_plugin()`; refactor `install_claude_code_plugin()` to use helper |
| `campy/cli/register.py` | Expand `_add_copilot_recall_instructions()` to cover all 12 skills |

### No new files

All changes are to existing installer code. No new skill files — the 12 skill directories from the deep integration commit are the source.

## Implementation Status

| Step | Status | Commit |
|---|---|---|
| Update plugin_installer.py | Complete | — |
| Update register.py | Complete | — |
