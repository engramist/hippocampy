# Campy Memory — Session Recall Protocol

You have access to a persistent AI memory system called Campy (HippoCampy). It remembers decisions, constraints, plans, and context across all your sessions.

## At Session Start — MANDATORY

**BEFORE doing any work, you MUST follow this protocol:**

1. Call `memory_decision` with the user's first message:
   ```
   memory_decision(query="<user's first message>", session_id="<session>")
   ```

2. Call the recommended tool from Step 1's response:
   - `current_truth` for single-topic recall
   - `compile_context` for broad context needs
   - `recall_procedures` for process questions
   - `recall_relevant_lessons` for past outcomes

3. If continuing existing work, call `diff_since` to see recent changes:
   ```
   diff_since(since_iso="<24 hours ago ISO>")
   ```

4. Present findings to the user before starting work.

## During the Session — Recall Triggers

| When You See This | You MUST Call This |
|---|---|
| Questions about past decisions | `current_truth(query="<topic>")` |
| Architecture or design questions | `current_truth(query="<topic>")` |
| Multi-entity or broad queries | `compile_context(query="<topic>")` |
| "Why did we choose X?" | `current_truth(query="decision about X")` |
| Process or procedure questions | `recall_procedures(query="<topic>")` |
| "What went wrong last time?" | `recall_relevant_lessons(query="<topic>")` |
| Not sure which tool | `memory_decision(query="<question>")` |

## After Every Response — MANDATORY

**AFTER every response, you MUST call `notify_turn`:**

```
notify_turn(role="assistant", content="<your full response>", session_id="<session>")
```

This is how the Brain captures knowledge. Never skip it.

## Available Tools

| Tool | Purpose |
|---|---|
| `memory_decision` | Ask the Brain which recall tool to use |
| `current_truth` | Semantic search for specific facts |
| `compile_context` | Multi-source bundle compilation |
| `recall_procedures` | Process and procedure knowledge |
| `recall_relevant_lessons` | Past outcomes and lessons learned |
| `reconstruct_timeline` | Temporal view of events |
| `diff_since` | Changes since a timestamp |
| `analogical_search` | Cross-project pattern matching |
| `notify_turn` | Capture your response in memory |
| `ingest_data` | Ingest files/data into memory |
| `reconstruct_timeline` | Sequence, history, chronology | 0.8 | Ordered events + timestamps |
| `recall_plans` | Similar prior work, strategies | 0.75 | Plans + outcomes + lessons |
| `recall_procedures` | Workflows, standard processes | 0.85 | Step-by-step + variants |
| `recall_relevant_lessons` | Learned lessons, anti-patterns | 0.8 | Lesson + context + application |
| `analogical_search` | Similar past projects | 0.7 | Analogies + key differences |
| `recall_mechanic_priors` | ARC mechanics, world models | 0.75 | Mechanic signature + evidence |
| `recall_scene_graph_priors` | ARC scene graphs, spatial patterns | 0.75 | Scene pattern + success rate |
| `memory_decision` | Should I recall? Which tool? | 0.9 | Recommendation + confidence |
| `context_status` | Token/context health | 0.95 | Metrics + warnings |

---

## Anti-Bloat Rules

1. **Do not recall for every turn.** Only recall when a *decision needs memory*.

2. **Do not dump raw memory into your answer.** Use memory to *inform* your decision, then synthesize a compact answer.

3. **Prefer top 3 results unless you ask for exhaustive review.** Tools return ranked results; use the top few unless context demands exhaustive analysis.

4. **Summarize recalled memory compactly.** Example: "The prior installer learned X; we fixed Y by doing Z" - not the raw message dump.

5. **Use raw Message/DocumentExtract evidence as *provenance*, not primary context.** If you recall "the team decided on async pattern," cite the evidence but explain it yourself.

6. **If unsure whether to recall, call `memory_decision` first.** It's cheap and faster than guessing wrong.

7. **Recall refines; it doesn't replace current context.** Your current messages remain your primary working context.

---

## Examples

### Good: Selective, Compact Recall

**User:** "I need to implement the installer. What did we learn from the last attempt?"

**You:** (Call `recall_plans` with query "installer design and failures")
-> Returns: [Plan A (failed due to X), Plan B (succeeded with constraints Y), Lesson Z]

**Your answer:** "We learned that async bootstrapping is necessary (Plan B). Last time we avoided it and hit timeout issues. Let me build on that approach for this installer."

---

### Bad: Bloated, Unnecessary Recall

**User:** "Fix the typo on line 42"

**You:** (Call `current_truth` with query "line 42 typo context"  - DON'T DO THIS)

-> Your context bloats for no reason. Just fix the typo.

---

### Good: Structured Timeline

**User:** "Walk me through how we debugged the graph corruption."

**You:** (Call `reconstruct_timeline` with query "graph corruption debug sequence")
-> Returns: Event 1 (2026-03-15 10:30): noticed X, Event 2 (10:35): traced to Y, Event 3 (11:00): fixed by Z

**Your answer:** "Here's the sequence: we noticed corruption in the morning, traced it to a race condition in the sweep loop, and fixed it with a transaction lock."

---

## Activity Indicator

After you use memory, you can verify capture/recall worked:

```bash
campy activity --follow
```

This shows live events:
- `notify_turn` - your message was captured
- Consolidation steps - the system processed and stored it
- `recall` operations - when memory was retrieved
- Warnings - potential issues

---

## Failure Modes

### "Brain daemon is offline"
-> Passive capture stops. You can still edit and code. When the daemon restarts, it will resume captures.
-> **Workaround:** `campy doctor --repair` and `campy activity --follow` to monitor restart.

### "Recall tool timed out"
-> Network or KuzuDB latency. Recall failed; no memory was added to context.
-> **Workaround:** Retry or use `context_status` to check health. Fall back to current context.

### "I got the wrong recall results"
-> Query was ambiguous or memory is sparse (new quest).
-> **Workaround:** Rephrase the query more specifically. Example: "installer bootstrap script" instead of "install".

### "I'm using too much context"
-> Too many recalls or memory payloads are too large.
-> **Workaround:** Use `context_status` first. Call `memory_decision` before recalling. Reduce result count (top 3 instead of top 10).

---

## Key Takeaways

1. **Write is passive; recall is active.** Campy listens. You decide when to remember.
2. **Recall is selective.** Use the decision tree to pick the right tool for the question.
3. **Compact is better.** Summarize, don't dump. Prefer top results. Use evidence for provenance.
4. **`memory_decision` is your copilot.** If unsure, ask it first.
5. **`campy activity --follow` is your verification.** Watch the feed to confirm capture/recall worked.

---

**Last Updated:** May 11, 2026  
**Status:** Canonical Policy (all agents share this core guidance)
