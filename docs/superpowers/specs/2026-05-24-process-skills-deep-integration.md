# Layer 4 Process Skills — Deep Integration

## Context

Campy has a plugin (`plugin/`) that auto-installs 5 skills and 28 MCP tools. Matt Pocock's skills (`mattpocock/skills`) provide proven process discipline — grilling sessions, debug loops, TDD, architecture reviews, handoffs. Phase 1 of the Layer Cake installed Matt's skills globally and created Campy-native skills (`campy-brief`, `campy-learn`, etc.).

**Problem:** Matt's skills have zero Campy awareness. `/grill-with-docs` reads CONTEXT.md but never calls `compile_context`. `/diagnose` never checks the graph for past bugs. The integration is passive — Campy generates files that Matt's skills happen to read. There's no active graph querying.

**Second problem:** Skills are fragmented across 3 locations:
- `plugin/skills/` — auto-installed with Campy plugin (5 skills)
- `skills/` — project-level, only available in hippocampy directory (6 skills)
- `~/.agents/skills/` — Matt's skills, requires separate `npx skills@latest add mattpocock/skills` (14 skills)

A non-tech user who installs Campy gets 5 plugin skills. They don't get `campy-brief`, `campy-recall`, `campy-learn`, or any of Matt's process discipline skills.

**Solution:** Selective fork of Matt's 5 highest-value skills into Campy's plugin with lean Campy integration. Move existing Campy skills from `skills/` to `plugin/skills/`. Result: 12 skills auto-install with the plugin. Zero external dependencies. Everything works for non-tech users out of the box.

## Design Principles

### Lean Integration

Matt's process stays intact. Campy adds memory at natural inflection points — but suggestively, not mandatorily.

**Why lean:** The `session-start` skill already fires at conversation start and loads relevant context from the graph via `memory_decision` → `compile_context`. By the time a user invokes `/diagnose`, the LLM already has domain knowledge, recent changes, and relevant decisions. Skills don't need to duplicate this recall.

**The pattern:**
- **Before:** Nothing mandatory. Session-start already loaded context. Skill mentions Campy tools exist for deeper recall if needed.
- **During:** Suggestive, not prescriptive. "If this error looks familiar, check `recall_relevant_lessons`." The LLM uses judgment.
- **After:** Encourage capture via `upsert_lesson` when something worth remembering happened.

### Same Names, Plugin Namespace

Forked skills use the same base names as Matt's originals (`diagnose`, `tdd`, `handoff`). The plugin namespace (`hippocampy:`) disambiguates if a user has both installed. For users with only Campy, the names are clean and familiar.

### Companion Files Forked Verbatim

Matt's skills reference companion docs (CONTEXT-FORMAT.md, ADR-FORMAT.md, mocking.md, etc.). These are reference material, not process instructions. They're forked as-is.

## Skill Distribution Architecture

### Before (3 locations, fragmented)

```
plugin/skills/     → session-start, memory-awareness, quest-management, recall, status
skills/            → campy-brief, campy-handoff, campy-learn, campy-recall, campy-memory, sidequests-memory
~/.agents/skills/  → Matt's 14 skills (separate npm install)
```

### After (consolidated)

```
plugin/skills/     → 12 skills (all auto-install with Campy plugin)
  Existing:         session-start, memory-awareness, quest-management, status
  Merged:           recall (existing + campy-recall)
  Moved:            brief (from campy-brief), learn (from campy-learn)
  Forked:           grill, diagnose, handoff, tdd, improve-architecture

skills/            → Dev-only (campy-memory, sidequests-memory)
~/.agents/skills/  → Optional (power users can still install Matt's full set)
```

### Naming

| Plugin Skill | Source | Matt's Original Name | Conflict? |
|---|---|---|---|
| `grill` | Fork of `grill-with-docs` | `grill-with-docs` | No (different name) |
| `diagnose` | Fork of `diagnose` | `diagnose` | Yes — `hippocampy:diagnose` resolves |
| `handoff` | Merge of Matt's `handoff` + `campy-handoff` | `handoff` | Yes — `hippocampy:handoff` resolves |
| `tdd` | Fork of `tdd` | `tdd` | Yes — `hippocampy:tdd` resolves |
| `improve-architecture` | Fork of `improve-codebase-architecture` | `improve-codebase-architecture` | No (different name) |
| `brief` | Move from `skills/campy-brief` | N/A | No |
| `learn` | Move from `skills/campy-learn` | N/A | No |
| `recall` | Merge of existing `plugin/skills/recall` + `skills/campy-recall` | N/A | No |

## Enhanced Skill Designs

### 1. `grill` (from Matt's `grill-with-docs`)

**Matt's process (kept intact):** Grill the user relentlessly on every aspect of their plan. Challenge against domain glossary. Update CONTEXT.md and create ADRs as decisions crystallize. One question at a time.

**Campy additions (lean):**

Before starting: "The Brain may have relevant context about this domain. If you need deeper recall than what session-start provided, call `compile_context` or `recall_relevant_lessons` with the plan's topic."

During grilling — when a domain term conflicts or a decision crystallizes: "If you create or update CONTEXT.md or ADR files, the File Bridge will sync changes to the graph automatically. For significant decisions, consider calling `report_outcome` to create a Decision node with full relational context."

After grilling: "If the grilling surfaced a pattern worth remembering (common misconception, recurring confusion, surprising constraint), capture it via `upsert_lesson`."

**Files:**
- `plugin/skills/grill/SKILL.md` — enhanced
- `plugin/skills/grill/CONTEXT-FORMAT.md` — forked verbatim
- `plugin/skills/grill/ADR-FORMAT.md` — forked verbatim

### 2. `diagnose` (from Matt's `diagnose`)

**Matt's process (kept intact):** 6-phase debug loop. Build feedback loop → reproduce → hypothesize → instrument → fix → cleanup/post-mortem.

**Campy additions (lean):**

Phase 1 (build feedback loop): "If you've seen similar errors before, check `recall_relevant_lessons(query=<error description>)` — past fixes might shortcut the feedback loop construction."

Phase 3 (hypothesize): "Before ranking hypotheses, consider calling `recall_relevant_lessons` or `analogical_search` for past bugs with similar symptoms. Graph-backed pattern history can inform which hypotheses to rank higher."

Phase 6 (post-mortem): "Capture the root cause and fix via `upsert_lesson(text=<what caused it and fix>, lesson_type='mistake')`. If the error has a distinctive message, include trigger metadata so the hook system catches it next time."

**Files:**
- `plugin/skills/diagnose/SKILL.md` — enhanced
- `plugin/skills/diagnose/scripts/hitl-loop.template.sh` — forked verbatim

### 3. `handoff` (merge Matt's `handoff` + `campy-handoff`)

**Matt's process (kept intact):** Compact the conversation into a handoff doc. Include suggested skills. Save to temp directory. Redact sensitive info.

**Campy additions (lean):**

Sending: "After writing the handoff doc to the temp directory, also store the handoff state in the graph via `register_plan(goal=<summary>, steps=<remaining>, metadata={handoff: true, source_session: <session_id>})`. This lets the receiving session retrieve it via `compile_context` — works across machines, not just local."

Receiving: "When picking up a handoff, call `compile_context(query='handoff for <task>')` to surface the most recent handoff plan and related context from the graph."

**Files:**
- `plugin/skills/handoff/SKILL.md` — merged and enhanced

### 4. `tdd` (from Matt's `tdd`)

**Matt's process (kept intact):** Red-green-refactor with vertical slicing. Integration-style tests through public interfaces. One test → one implementation → repeat. No horizontal slices.

**Campy additions (lean):**

Planning phase: "If the project has established testing patterns or conventions, check `recall_procedures(query=<feature area>)` for existing approaches. Check `current_truth(query=<component>)` for constraints that affect testing strategy."

After refactor: "If a new testing pattern or insight emerged from this TDD cycle, consider capturing it via `upsert_lesson(text=<pattern>, lesson_type='optimization')`."

**Files:**
- `plugin/skills/tdd/SKILL.md` — enhanced
- `plugin/skills/tdd/mocking.md` — forked verbatim
- `plugin/skills/tdd/deep-modules.md` — forked verbatim
- `plugin/skills/tdd/tests.md` — forked verbatim
- `plugin/skills/tdd/interface-design.md` — forked verbatim
- `plugin/skills/tdd/refactoring.md` — forked verbatim

### 5. `improve-architecture` (from Matt's `improve-codebase-architecture`)

**Matt's process (kept intact):** Explore codebase for deepening opportunities. Present candidates in HTML report. Grilling loop on chosen candidate. CONTEXT.md/ADR updates inline.

**Campy additions (lean):**

Before exploring: "For full context about the area being reviewed, consider calling `compile_context(query=<area>)` and `get_knowledge_gaps()` for areas the system knows are under-documented."

Presenting candidates: "Cross-reference candidates against existing Decision nodes — if a candidate contradicts an active decision, flag it. Call `current_truth(query=<relevant decision>)` to check."

After grilling: "Capture architectural insights via `upsert_lesson`. For decisions that were made during the grilling, the File Bridge syncs ADR file changes to the graph automatically."

**Files:**
- `plugin/skills/improve-architecture/SKILL.md` — enhanced
- `plugin/skills/improve-architecture/LANGUAGE.md` — forked verbatim
- `plugin/skills/improve-architecture/HTML-REPORT.md` — forked verbatim
- `plugin/skills/improve-architecture/DEEPENING.md` — forked verbatim
- `plugin/skills/improve-architecture/INTERFACE-DESIGN.md` — forked verbatim

## Merges

### `recall` merge

The existing `plugin/skills/recall/SKILL.md` and `skills/campy-recall/SKILL.md` overlap significantly. Both route through `memory_decision` and provide recall tool tables. Merge into a single `plugin/skills/recall/SKILL.md` that combines the best of both.

### `handoff` merge

Matt's `handoff` writes to /tmp. `skills/campy-handoff` writes to graph. The merged `plugin/skills/handoff/SKILL.md` does both — temp file for immediate use, graph state for persistence.

## Implementation

### Files to create (17 total)

**Forked skills (5 SKILL.md + 12 companion files):**

| Path | Source | Modified? |
|---|---|---|
| `plugin/skills/grill/SKILL.md` | `~/.agents/skills/grill-with-docs/SKILL.md` | Yes — Campy additions |
| `plugin/skills/grill/CONTEXT-FORMAT.md` | `~/.agents/skills/grill-with-docs/CONTEXT-FORMAT.md` | No — verbatim |
| `plugin/skills/grill/ADR-FORMAT.md` | `~/.agents/skills/grill-with-docs/ADR-FORMAT.md` | No — verbatim |
| `plugin/skills/diagnose/SKILL.md` | `~/.agents/skills/diagnose/SKILL.md` | Yes — Campy additions |
| `plugin/skills/diagnose/scripts/hitl-loop.template.sh` | `~/.agents/skills/diagnose/scripts/hitl-loop.template.sh` | No — verbatim |
| `plugin/skills/handoff/SKILL.md` | Merge: Matt's + `skills/campy-handoff/SKILL.md` | Yes — merged |
| `plugin/skills/tdd/SKILL.md` | `~/.agents/skills/tdd/SKILL.md` | Yes — Campy additions |
| `plugin/skills/tdd/mocking.md` | `~/.agents/skills/tdd/mocking.md` | No — verbatim |
| `plugin/skills/tdd/deep-modules.md` | `~/.agents/skills/tdd/deep-modules.md` | No — verbatim |
| `plugin/skills/tdd/tests.md` | `~/.agents/skills/tdd/tests.md` | No — verbatim |
| `plugin/skills/tdd/interface-design.md` | `~/.agents/skills/tdd/interface-design.md` | No — verbatim |
| `plugin/skills/tdd/refactoring.md` | `~/.agents/skills/tdd/refactoring.md` | No — verbatim |
| `plugin/skills/improve-architecture/SKILL.md` | `~/.agents/skills/improve-codebase-architecture/SKILL.md` | Yes — Campy additions |
| `plugin/skills/improve-architecture/LANGUAGE.md` | `~/.agents/skills/improve-codebase-architecture/LANGUAGE.md` | No — verbatim |
| `plugin/skills/improve-architecture/HTML-REPORT.md` | `~/.agents/skills/improve-codebase-architecture/HTML-REPORT.md` | No — verbatim |
| `plugin/skills/improve-architecture/DEEPENING.md` | `~/.agents/skills/improve-codebase-architecture/DEEPENING.md` | No — verbatim |
| `plugin/skills/improve-architecture/INTERFACE-DESIGN.md` | `~/.agents/skills/improve-codebase-architecture/INTERFACE-DESIGN.md` | No — verbatim |

### Files to move (3 skills)

| From | To |
|---|---|
| `skills/campy-brief/SKILL.md` | `plugin/skills/brief/SKILL.md` |
| `skills/campy-learn/SKILL.md` | `plugin/skills/learn/SKILL.md` |
| `skills/campy-recall/SKILL.md` | Merged into `plugin/skills/recall/SKILL.md` |

### Files to modify (1)

| File | Change |
|---|---|
| `plugin/skills/recall/SKILL.md` | Merge content from `skills/campy-recall/SKILL.md` |

### Files to remove after move (3)

| Path | Reason |
|---|---|
| `skills/campy-brief/` | Moved to `plugin/skills/brief/` |
| `skills/campy-learn/` | Moved to `plugin/skills/learn/` |
| `skills/campy-recall/` | Merged into `plugin/skills/recall/` |
| `skills/campy-handoff/` | Merged into `plugin/skills/handoff/` |

### Data directory mirroring

Campy's pip-installable package bundles plugin skills from `campy/data/plugin/skills/`. Any new skills added to `plugin/skills/` must also be mirrored to `campy/data/plugin/skills/` for the installed package to include them. The existing build/packaging process handles this.

## Build Sequence

| Step | What | Files |
|---|---|---|
| 1 | Fork 12 companion files verbatim | Copy from `~/.agents/skills/` to `plugin/skills/` |
| 2 | Create 5 enhanced SKILL.md files | grill, diagnose, handoff, tdd, improve-architecture |
| 3 | Move 3 existing skills to plugin | brief, learn, and merge recall |
| 4 | Remove old skill directories | `skills/campy-brief/`, `skills/campy-learn/`, `skills/campy-recall/`, `skills/campy-handoff/` |
| 5 | Mirror to `campy/data/plugin/skills/` | All new plugin skills |
| 6 | Update design spec status | Mark Phase 5 as shipped |

## Verification

| Check | How |
|---|---|
| Skills discoverable | Install Campy plugin, verify all 12 skills appear in `/help` or skill listing |
| No namespace conflict | Have both Matt's skills and Campy installed, verify `hippocampy:diagnose` resolves correctly |
| Grill integration | Run `/grill`, verify it suggests Campy tools and handles CONTEXT.md updates |
| Diagnose integration | Run `/diagnose`, verify Phase 6 post-mortem suggests `upsert_lesson` |
| Handoff integration | Run `/handoff`, verify both /tmp file and graph state are created |
| TDD integration | Run `/tdd`, verify it suggests `recall_procedures` during planning |
| Improve-architecture integration | Run `/improve-architecture`, verify it suggests `compile_context` and `get_knowledge_gaps` |
| Moved skills work | Run `/brief`, `/learn`, verify they work from plugin context (not just project) |
| Merged recall works | Run `/recall` (the plugin version), verify it covers both old recall and campy-recall functionality |

## Attribution

Forked skills originate from Matt Pocock's `mattpocock/skills` repository. Companion files (CONTEXT-FORMAT.md, ADR-FORMAT.md, mocking.md, etc.) are forked verbatim. SKILL.md files are modified to add Campy integration. Each forked SKILL.md includes an attribution line: "Process adapted from Matt Pocock's skills (mattpocock/skills)."

## Implementation Status

| Step | Status | Commit |
|---|---|---|
| Fork companion files | Complete | — |
| Create enhanced SKILL.md files | Complete | — |
| Move existing skills | Complete | — |
| Mirror to campy/data | Complete | — |
| Update design spec | Complete | — |
