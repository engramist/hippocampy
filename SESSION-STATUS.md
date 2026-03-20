# SideQuests Brain — Session Status

> Repo-tracked handoff doc so any machine can pick up where work left off.
> Update this at the end of every working session.

---

## Last Updated: 2026-03-19 (evening)

### What's Working
- **End-to-end cross-agent memory sharing VERIFIED (clean retest).** Fresh DB, Gemini stores "SQLAlchemy" decision + "JWT auth" constraint → Claude Code retrieves both correctly via `current_truth`. No hallucinations, no junk.
- **Brain Daemon** runs, accepts connections from both Claude Code and Gemini CLI adapters.
- **409 tests pass**, 18 skipped.
- **10 pipeline bugs fixed** total (ISSUE-018 through ISSUE-026).

### Bugs Fixed (2026-03-19) — Summary
| Issue | Problem | Fix |
|-------|---------|-----|
| ISSUE-024 | Hallucination poisoning — Claude fabricated constraints, `notify_turn` stored them as truth, future sessions recalled them as confirmed facts | Assistant turns capped at 0.85 confidence (below HARD_LOCK 0.90) — can never create confirmed Decision/Constraint nodes. Role passed through queue → orchestrator → Step 4. |
| ISSUE-025 | Decisions dropped as noise — "We decided to use SQLAlchemy" scored 0.2355 against PhysicalThing centroid, below NOISE_FLOOR 0.25 | Lowered NOISE_FLOOR from 0.25 to 0.18. Added 5 decision-oriented seed examples to PhysicalThing, 3 to Category in GistSeedExamples.md. |
| ISSUE-026 | Junk concepts leaking — "MainQuest", "first", "all endpoints", "the only exception" stored as Concepts | Added ordinal regex, SideQuests system terms set, and determiner-initial noun chunk filter to `step1_ner.py`. |

Also fixed in this session:
- **Claude auto-memory poisoning** — deleted hallucinated memory files from `~/.claude/projects/-Users-djshelton-Desktop-sidequests-test/memory/` (Redis, bcrypt, SQLite forbidden, auth constraints that were fabricated by Claude in a prior session).
- **Added `GEMINI-DELEGATION.md` workflow** to CLAUDE.md so future sessions use Gemini CLI for implementation.

### Previous Bugs (2026-03-18)
| Issue | Problem | Fix |
|-------|---------|-----|
| ISSUE-018 | Gemini CLI infinite self-reflection loop after `notify_turn` | Rewrote `GEMINI.md` + adapter system prompt with "fire-and-forget / STOP" instructions |
| ISSUE-019 | Junk concepts stored (box-drawing chars, UUIDs, formatting artifacts, pure numbers) | Added `_is_junk_entity()` filter in `step1_ner.py` |
| ISSUE-020 | Confidence scoring too conservative — no Decision/Constraint nodes ever created | Changed formula to `0.67 + (hits × 0.15)`, increased gist agreement boost to +0.10 |
| ISSUE-021 | MainQuest never created — Kuzu HNSW silent failure on MERGE...SET embedding | Replaced MERGE with check-then-CREATE/UPDATE in `quest.py` |
| ISSUE-022 | Constraint signal patterns too narrow ("make sure", "ensure" not matched) | Added broader signal patterns to `step4_pattern.py` |
| ISSUE-023 | Gemini never ingested user turns (told not to, to prevent loop) | Updated GEMINI.md to call `notify_turn` twice (user + assistant), both fire-and-forget |

### Pending — Next Steps

**1. Remaining data quality issues (minor — don't block usage)**
- **Duplicate concepts:** JWT appears as both confirmed Concept + Constraint. Step 5 retrieval dedup may need tuning.
- **Markdown formatting leakage:** "Project Setup:**" stored as concept — markdown bold markers (`**`) passing through NER.
- **Generic word "constraints"** stored as a Concept — the word itself, not a specific constraint.
- **Assistant-originated open loops:** "Bearer", "Routes", "Setup Boilerplate" from Gemini's responses enter as `confidence_low` (correct behavior via ISSUE-024 cap) but clutter the open_loops list.

**2. System-level issues**
- **UserPromptSubmit hook error** in Claude Code test dir — hook config not set up, user turns only come via `notify_turn`.
- **Background sweep not implemented:** Confidence re-scoring, time-decay, archival, and resurrection are designed but not coded yet. This would naturally clean up the `confidence_low` clutter from item 1.

**3. Backlog priorities (from `backlog.md`)**
- B13 installer (`sidequests install`) — implemented on other machine, pulled into repo
- B14 proactive insight surfacing — biggest consumer-readiness gap
- B15 deep-link handoff (chat → Memory Control Panel)
