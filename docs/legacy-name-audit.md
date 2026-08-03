# SideQuests Legacy Name Audit

This document tracks intentional and unintentional occurrences of the legacy "SideQuests" / "sidequests" naming after the HippoCampy (Campy) rebranding and namespace migration (B242-B247).

Last verified: 2026-08-02, against repo HEAD after commit `3b4c608` ("chore: remove sidequests compatibility shims and console scripts").

## Migration history note

The original plan (B242-B244) assumed a gradual path: add a `campy` import shim -> move implementation into `campy/` while leaving `sidequests/` as thin forwarding shims -> repoint installers. In practice the rename landed in one larger pass (`27c9f6e "Rename project namespace to Campy"`) and the compatibility shim stage was retired shortly after (`3b4c608`) once it was confirmed no production code or the ARC_AGI consumer depended on `sidequests.*` imports. Net effect: `campy` is the only Python import namespace today. There is no `sidequests/` package on disk and no `sidequests` / `sidequests-daemon` console script in `pyproject.toml`. This is a superset of what B242/B243 originally asked for, not a partial implementation of it.

## Public-facing stale names (fixed in this pass)

- `docs/openclaw-install.md` - fixed: package name line said `` `@sidequests/hippocampy` ``, corrected to `` `hippocampy` `` (matches `extensions/hippocampy/package.json` and the `openclaw.plugin.json` manifest id).
- `docs/openclaw-install.md` - fixed: example memory-block tag said `<sidequests-memory>`, corrected to `<campy-memory>` (matches the literal string emitted by `extensions/hippocampy/src/index.ts`).

Previously flagged items confirmed already clean (no remaining `sidequests` references as of this pass):
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/ARCHITECTURE.md` - down to a single intentional reference (see "Known gap" below); the "many references" note from the prior version of this audit is stale.

## Known gap noted, not changed in this pass

- `campy/brain/temporal_lobe/dictionary.py` (`DICTIONARY_PATHS`) and the matching docstring in `campy/brain/thalamus/tool_schemas.py` (`reload_domain_dictionary`) only search `.sidequests/domain_dictionary.yaml` / `.yml` (plus a bare `domain_dictionary.yaml` in cwd). There is no `.campy/domain_dictionary.yaml` primary path, unlike the `campy.toml`-before-`sidequests.toml` precedence used elsewhere (`campy/brain/brainstem/config.py`). This is a real behavioral gap, not just naming — flagging it here rather than fixing it in this documentation-scoped pass, since it would need its own test coverage and touches files outside B247's listed file set.
- `docs/ARCHITECTURE.md`'s remaining `sidequests` reference documents `reload_domain_dictionary`'s `.sidequests/domain_dictionary.yaml` path, which is currently accurate (it's the only path implemented) — leave as-is until the gap above is addressed.

## Intentional compatibility names (current, corrected from the prior version of this doc)

- `sidequests.toml` (legacy fallback config file, both at repo root and packaged at `campy/data/config/sidequests.toml`) - `campy.toml` is preferred and wins if both exist; see `campy/brain/brainstem/config.py` search order.
- `~/.sidequests/` (legacy runtime directory and `~/.sidequests/config.toml` fallback for existing users; `campy/paths.py`).
- `ai.sidequests.brain` (legacy launchd label, checked/migrated by `campy doctor`).
- `skills/sidequests-memory/SKILL.md` and packaged `campy/data/sidequests-memory/SKILL.md` — both are now deliberately short deprecation stubs (13 lines) that point at `campy-memory`, not full duplicates. `campy-memory` (`skills/campy-memory/SKILL.md`, 251 lines) is the sole canonical policy source.
- `sidequests` references in `campy/branding.py` (`LEGACY_*` constants) used by doctor/uninstall/register to detect and clean up pre-rename installs.
- `tests/test_sidequests_memory_skill.py` — compatibility test asserting the legacy skill is a forwarding stub, not that it still carries policy content.

Note: there is **no** `sidequests/` Python package directory and **no** `sidequests` / `sidequests-daemon` console script anymore (both removed in `3b4c608`). The prior version of this audit listed these as "intentional compatibility names" — that was accurate when it was written but is now stale; corrected here.

## Historical/patent records to preserve

- `InvertorsDocs/` - all original invention and patent documents (review only, not touched by this pass).
- `Backlog_Archive*.md` - historical project state.
- `backlog/` - old backlog cards (B1-B241 and other completed/historical cards may legitimately reference "SideQuests" in problem statements describing that era; only active/future cards should default to HippoCampy/Campy naming going forward). Bulk-auditing individual historical backlog cards for naming is out of scope for this pass — the agent that wrote it was explicitly instructed not to touch card files outside B242-B248. Left as a follow-up for whoever owns `backlog/` tracker regeneration.
- `backlog.md` (root-level legacy backlog snapshot) still reads "SideQuests Brain" throughout — historical artifact, not touched here for the same reason.

## Graph ontology terms to preserve

- `SideQuest` node type.
- `BRANCHED_TO_SIDEQUEST` relationship.
- `Quest` (generic term, but often used as `SideQuest` in context).

## Generated artifacts to delete/ignore

- `build/`, `dist/`, `*.egg-info`, `__pycache__`, `.pytest_cache` — all already covered by `.gitignore`; `scripts/audit_public_release.sh` passes clean (0 blocked patterns, 0 high-risk artifacts) as of this pass.
- No stray `*sidequest*`-named generated artifacts were found outside the intentional-compatibility list above (verified via a full non-git/non-venv/non-build/non-dist filesystem scan).
