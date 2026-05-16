# Campy Memory Skill

**Purpose:** Use HippoCampy (Campy) as a reliable durable memory system without bloating your context window.

Campy continuously captures your decisions, constraints, plans, and lessons as you work. This skill teaches you when to recall that memory, which tool to use, and how to keep your context lean.

## Core Rule

**Do not recall on every turn. Do not bloat context. Recall only when a decision needs memory.**

Campy writes passively. You recall actively and selectively.

---

## Write vs Recall

### Write (Passive - Always On)

Campy captures:
- **Decisions** - what you decided and why
- **Constraints** - what you must or cannot do
- **Plans** - your implementation strategies
- **Lessons** - what you learned that applies elsewhere
- **Entity relationships** - how concepts connect
- **Contradictions** - when expectations differ from reality

You do nothing. The system listens to your messages and stores the core signal.

### Recall (Active - You Decide)

You call a recall tool when you need:
- Prior choices or context
- Timeline of what happened
- Lessons from similar work
- Workflow procedures
- Changes since another session

---

## Recall Decision Tree

### **Q: What kind of decision are you making?**

#### Prior decisions, architecture, constraints, or preferences
-> **`current_truth`**
- Use when: "What did we decide?", "What are the constraints?", "Is feature X enabled?"
- Example: "What architecture did we settle on for the installer?"

#### What changed since last session or another agent
-> **`diff_since`**
- Use when: "What changed?", "Since the last time...", "What did the other agent do?"
- Example: "What's different since the last session?"

#### Sequence, timeline, or debugging history
-> **`reconstruct_timeline`**
- Use when: "What happened in order?", "How did we get here?", "Walk me through the debug steps"
- Example: "What was the sequence of steps that led to this bug?"

#### Planning similar work
-> **`recall_plans`**
- Use when: "How did we do this before?", "Similar project", "Implement X like we did Y"
- Example: "I need to set up an installer. What did we learn from the last one?"

#### Reusable workflow or procedure
-> **`recall_procedures`**
- Use when: "How do we usually do this?", "Standard workflow", "Process we use"
- Example: "What's our standard testing procedure?"

#### Lessons learned or cross-session learning
-> **`recall_relevant_lessons`**
- Use when: "What did we learn?", "Don't repeat the mistake", "Best practice from before"
- Example: "What lessons did we learn from the last release?"

#### Similar past project (analogy)
-> **`analogical_search`**
- Use when: "This is like...", "Similar situation before", "Analogous problem"
- Example: "We had a similar performance problem before. What did we do?"

#### ARC mechanics, world model, scene graph, or puzzle patterns
-> **`recall_mechanic_priors`** or **`recall_scene_graph_priors`**
- Use when: "ARC", "world model", "mechanic", "puzzle pattern"
- Example: "What world-model mechanics did we discover for this type of puzzle?"

#### Context window or token health
-> **`context_status`**
- Use when: "How much context is left?", "Token budget", "Context bloat check"
- Example: "Am I at risk of context bloat? How many tokens are loaded?"

#### Simple local edit or current context sufficient
-> **Do not recall**
- Example: "Add a comment to this function" or "Fix the typo on line 42"

---

## Tool Map

| Tool | Use Case | Confidence | Output Format |
|------|----------|------------|----------------|
| `current_truth` | Prior decisions, constraints, architecture | 0.9 | Ranked facts + provenance |
| `diff_since` | Changes since milestone/session | 0.85 | Structured diff + annotation |
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
