# SideQuests Legacy Name Audit

This document tracks intentional and unintentional occurrences of the legacy "SideQuests" / "sidequests" naming after the HippoCampy (Campy) rebranding and repository-folder rename.

## Public-facing stale names to fix now

- [ ] `docs/ARCHITECTURE.md` - many references to `sidequests.toml`
- [ ] `docs/openclaw-install.md` - references to `sidequests-brain` plugin
- [ ] `README.md` - potential legacy naming
- [ ] `AGENTS.md` - references to SideQuests Brain
- [ ] `CLAUDE.md` - references to sidequests package

## Intentional compatibility names

- `sidequests/` directory (shims for backward-compatible Python imports)
- `sidequests.toml` (fallback config file in project root)
- `~/.sidequests/` (legacy runtime directory for existing users)
- `ai.sidequests.brain` (legacy launchd label)
- `sidequests-memory` (legacy Codex skill name)
- `sidequests` entry points in `pyproject.toml`

## Historical/patent records to preserve

- `InvertorsDocs/` - all original invention and patent documents
- `Backlog_Archive*.md` - historical project state
- `backlog/` - old backlog cards (intentional history)

## Graph ontology terms to preserve

- `SideQuest` node type
- `BRANCHED_TO_SIDEQUEST` relationship
- `Quest` (generic term, but often used as `SideQuest` in context)

## Generated artifacts to delete/ignore

- `build/`
- `dist/`
- `*.egg-info`
- `__pycache__`
- `.pytest_cache`
