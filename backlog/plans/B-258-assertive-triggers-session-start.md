# B258 - Assertive Trigger Language + Session-Start Skill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all trigger language in plugin skills to use assertive mandatory phrasing. Create a new `session-start` skill with a step-by-step recall protocol.

**Architecture:** Edit 4 existing SKILL.md files to replace passive language with assertive triggers. Create `plugin/skills/session-start/SKILL.md` with a 4-step protocol: memory_decision → suggested tool → diff_since → surface findings.

**Tech Stack:** Markdown skill files

---

### Task 1: Audit and Replace Passive Language in Recall Skill

**Files:**
- Modify: `plugin/skills/recall/SKILL.md`

- [ ] **Step 1: Find all passive trigger patterns**

Search for passive patterns:
```bash
grep -n "you can\|you may\|consider\|optionally\|if you want\|when the user asks" plugin/skills/recall/SKILL.md
```

- [ ] **Step 2: Replace passive with assertive language**

Apply these replacements throughout `plugin/skills/recall/SKILL.md`:

| Old Pattern | New Pattern |
|---|---|
| "Before answering questions about past decisions..." | "**BEFORE answering ANY question about past decisions, architecture, constraints, or project history, you MUST check the Brain's memory.**" |
| "Call `current_truth` when the user asks about:" | "**ALWAYS call `current_truth` when you encounter:**" |
| "Use 'both' when the question might involve" | "**ALWAYS use scope 'both' when the question involves**" |

Add a trigger table at the top of the file, right after the title:

```markdown
## Mandatory Recall Triggers

| When You See This | You MUST Call This |
|---|---|
| Questions about past decisions | `current_truth(query="<decision topic>")` |
| "Why did we choose X?" | `current_truth(query="decision about X")` |
| Architecture or design questions | `current_truth(query="<architecture topic>")` |
| Multi-entity or broad context needs | `compile_context(query="<broad topic>")` |
| "Tell me everything about X" | `compile_context(query="X")` |
| Not sure which tool to use | `memory_decision(query="<question>")` |
| Process or procedure questions | `recall_procedures(query="<process>")` |
| "What went wrong last time?" | `recall_relevant_lessons(query="<topic>")` |
| "What happened this week?" | `reconstruct_timeline(limit=20)` |
| "What changed since yesterday?" | `diff_since(since_iso="<ISO timestamp>")` |

**Do NOT answer from your context window alone.** The Brain's graph is more reliable than your training data for project-specific facts.
```

- [ ] **Step 3: Verify zero passive patterns remain**

```bash
grep -c "you can call\|you may\|consider calling\|optionally" plugin/skills/recall/SKILL.md
```

Expected: 0

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/recall/SKILL.md
git commit -m "feat(B258): rewrite recall skill with assertive trigger language"
```

---

### Task 2: Replace Passive Language in Memory-Awareness Skill

**Files:**
- Modify: `plugin/skills/memory-awareness/SKILL.md`

- [ ] **Step 1: Find passive patterns**

```bash
grep -n "you can\|you may\|consider\|optionally\|don't need to" plugin/skills/memory-awareness/SKILL.md
```

- [ ] **Step 2: Apply assertive rewrites**

Key replacements:

| Old | New |
|---|---|
| "You don't need to tell the Brain what to remember" | "The Brain handles memory automatically — your job is to ALWAYS call `notify_turn` after every response." |
| "After every response you give, call `notify_turn`" | "**AFTER EVERY RESPONSE, you MUST call `notify_turn`.** This is mandatory. Never skip it." |
| "Keep it brief — one sentence" | "**ALWAYS mention insights briefly** when `concepts_stored > 0` or `reified > 0` or `contradictions > 0`." |

- [ ] **Step 3: Verify zero passive patterns remain**

```bash
grep -c "you can\|you may\|consider\|optionally" plugin/skills/memory-awareness/SKILL.md
```

Expected: 0

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/memory-awareness/SKILL.md
git commit -m "feat(B258): rewrite memory-awareness skill with assertive language"
```

---

### Task 3: Replace Passive Language in Quest-Management Skill

**Files:**
- Modify: `plugin/skills/quest-management/SKILL.md`

- [ ] **Step 1: Find passive patterns**

```bash
grep -n "you can\|you may\|consider\|offer to" plugin/skills/quest-management/SKILL.md
```

- [ ] **Step 2: Apply assertive rewrites**

Key replacements:

| Old | New |
|---|---|
| "offer to create a Side Quest" | "**ALWAYS offer to create a Side Quest** when the conversation shifts to a distinct tangent" |
| "When a project or workstream wraps up, mark it complete" | "**When a project wraps up, you MUST call `complete_quest`**" |

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/quest-management/SKILL.md
git commit -m "feat(B258): rewrite quest-management skill with assertive language"
```

---

### Task 4: Replace Passive Language in Status Skill

**Files:**
- Modify: `plugin/skills/status/SKILL.md`

- [ ] **Step 1: Find passive patterns and apply assertive rewrites**

Key replacements:

| Old | New |
|---|---|
| "Check how full the current conversation's context window is" | "**ALWAYS check context health** when the conversation is getting long" |
| "Surface unresolved tentative knowledge for user review" | "**Periodically call `get_open_loops()`** to surface unresolved items" |
| "When starting a new conversation about an existing project, check what's changed" | "**When starting a new conversation about an existing project, you MUST call `diff_since`**" |

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/status/SKILL.md
git commit -m "feat(B258): rewrite status skill with assertive language"
```

---

### Task 5: Create Session-Start Skill

**Files:**
- Create: `plugin/skills/session-start/SKILL.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p plugin/skills/session-start
```

- [ ] **Step 2: Write the session-start skill**

Create `plugin/skills/session-start/SKILL.md`:

```markdown
# Session Start — Memory Recall Protocol

**This skill fires at the START of every conversation.** Before doing any work, you MUST follow this 4-step protocol to load context from the Brain.

## Step 1: Ask the Brain What to Recall

Call `memory_decision` with the user's first message to get routing advice:

```
memory_decision(query="<user's first message or topic>", session_id="<session>")
```

The Brain returns:
- `recommended_tool`: which recall tool to call next
- `reasoning`: why this tool was chosen
- `confidence`: how confident the routing is

## Step 2: Call the Recommended Tool

Based on `recommended_tool` from Step 1:

| Recommendation | Action |
|---|---|
| `current_truth` | `current_truth(query="<topic>", session_id="<session>")` |
| `compile_context` | `compile_context(query="<topic>", token_budget=32000, agent_type="<your type>")` |
| `recall_procedures` | `recall_procedures(query="<process topic>")` |
| `recall_relevant_lessons` | `recall_relevant_lessons(query="<topic>")` |
| `recall_plans` | `recall_plans(query="<plan topic>")` |
| `none` | Skip to Step 3 (Brain has no relevant context) |

**ALWAYS call the recommended tool.** Do not skip this step.

## Step 3: Check for Recent Changes

If you are continuing work on an existing project or quest, call `diff_since` to see what changed since the last session:

```
diff_since(since_iso="<last session ISO timestamp>")
```

If you don't know the last session timestamp, use a reasonable default (e.g., 24 hours ago):

```python
from datetime import datetime, timedelta
since = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"
```

## Step 4: Surface Findings Before Working

**BEFORE starting any work**, present what the Brain knows to the user:

- Summarize key facts, constraints, and decisions relevant to their request
- Mention any recent changes from `diff_since`
- Flag any low-confidence or contradictory information
- If the Brain returned nothing relevant, say so: "I checked the Brain's memory and didn't find existing context on this topic."

**The user should never wonder if you checked memory.** Make it visible that you did.

## Example Flow

User: "Let's work on the authentication refactor"

1. `memory_decision(query="authentication refactor")` → `recommended_tool: "compile_context"`
2. `compile_context(query="authentication refactor", token_budget=32000)` → returns bundle with constraints, decisions, related entities
3. `diff_since(since_iso="2026-05-19T00:00:00Z")` → 3 nodes changed since yesterday
4. "Based on the Brain's memory: we decided to use JWT with rotating refresh tokens (high confidence). The auth module was last modified yesterday — 3 changes including a new rate-limiting constraint. There's a low-confidence note about session storage that we should clarify..."
```

- [ ] **Step 3: Verify skill content**

```bash
cat plugin/skills/session-start/SKILL.md | head -5
```

Expected: Title and "This skill fires at the START of every conversation"

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/session-start/
git commit -m "feat(B258): create session-start skill with 4-step recall protocol"
```

---

### Task 6: Verification

- [ ] **Step 1: Verify zero passive trigger language across all 5 skills**

```bash
grep -rn "you can call\|you may call\|consider calling\|optionally call" plugin/skills/
```

Expected: 0 matches

- [ ] **Step 2: Verify session-start skill references all key tools**

```bash
grep -c "memory_decision\|current_truth\|compile_context\|diff_since" plugin/skills/session-start/SKILL.md
```

Expected: 4+ matches (each tool referenced at least once)

- [ ] **Step 3: Verify all 5 skill directories exist**

```bash
ls plugin/skills/
```

Expected: `memory-awareness  quest-management  recall  session-start  status`

- [ ] **Step 4: Final commit**

```bash
git add plugin/skills/
git commit -m "feat(B258): complete — assertive triggers + session-start skill"
```
