# B257 - Upgrade Plugin Skills with Memory OS Tools

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all 4 existing plugin skills to reference the full set of Memory OS tools (B249-B254). Add missing tools: `compile_context`, `memory_decision`, `ingest_data`, `recall_procedures`, `recall_relevant_lessons`, `reconstruct_timeline`.

**Architecture:** Direct file edits to the 4 SKILL.md files in `plugin/skills/`. Each skill gets its tool references expanded to cover the complete retrieval toolkit.

**Tech Stack:** Markdown skill files

---

### Task 1: Upgrade Recall Skill

**Files:**
- Modify: `plugin/skills/recall/SKILL.md`

- [ ] **Step 1: Read current file**

Read `plugin/skills/recall/SKILL.md` to understand current content.

- [ ] **Step 2: Rewrite with full tool coverage**

Replace the contents of `plugin/skills/recall/SKILL.md` with:

```markdown
# Recalling Past Decisions and Context

Before answering questions about past decisions, architecture choices, constraints, or project history, ALWAYS check the Brain's memory first.

## Tool Reference

| Tool | When to Use |
|---|---|
| `current_truth` | Single-topic recall: "why did we choose X?", "what's the constraint on Y?" |
| `compile_context` | Multi-entity queries: "tell me everything about the auth system", broad context needs |
| `memory_decision` | Not sure which tool? Call this first — it recommends the right retrieval tool |
| `recall_procedures` | "How do we deploy?", "What's the process for X?" — procedural knowledge |
| `recall_relevant_lessons` | "What went wrong last time?", "Any lessons about X?" — past outcomes |
| `reconstruct_timeline` | "What happened this week?", "When did we decide X?" — temporal queries |
| `analogical_search` | "Have we done something like this before?" — cross-project patterns |
| `explore_graph` | Browse entity connections: "What's related to X?" |
| `diff_since` | "What changed since yesterday?" — recent changes |

## When to Use current_truth

Call `current_truth` when the user asks about:
- Past decisions ("why did we choose X?", "what did we decide about Y?")
- Constraints or requirements ("what are the rules for Z?")
- Project context ("what's the current state of X?")
- Architecture ("how does X work?", "what's the design for Y?")

```
current_truth(query="<what you're looking for>", session_id="<session>")
```

## When to Use compile_context

Call `compile_context` for broad or multi-entity queries:
- "Tell me everything about the payment system"
- "What do I need to know before changing the auth module?"
- Starting work on a component you haven't touched recently

```
compile_context(query="<broad query>", token_budget=32000, agent_type="claude_code")
```

## When to Use memory_decision

Call `memory_decision` when you're not sure which tool to use:

```
memory_decision(query="<user's question>", session_id="<session>")
```

It returns a `recommended_tool` field telling you exactly which tool to call next.

## Scoping

- `scope: "branch"` — search only the current project (default)
- `scope: "global"` — search cross-project constraints and preferences
- `scope: "both"` — search everywhere

## How to Use Results

- Results are ranked by relevance and confidence
- High pathway_strength = frequently accessed, well-established knowledge
- Items marked `confidence_low` are tentative — flag the uncertainty to the user
- The Brain's graph is more reliable than your context window for historical facts
- If results include a `bloat_warning`, mention to the user that the conversation is getting long
```

- [ ] **Step 3: Verify no old tool names remain**

Search the file for any references to tools that don't exist in `TOOL_HANDLERS`.

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/recall/SKILL.md
git commit -m "feat(B257): upgrade recall skill with full Memory OS tool coverage"
```

---

### Task 2: Upgrade Memory Awareness Skill

**Files:**
- Modify: `plugin/skills/memory-awareness/SKILL.md`

- [ ] **Step 1: Read current file**

Read `plugin/skills/memory-awareness/SKILL.md`.

- [ ] **Step 2: Add ingest_data and bundle compilation mentions**

Update the file to add these sections after the existing content:

After the "Insight Surfacing" section, add:

```markdown
## Tabular Data Ingestion

When the user shares spreadsheets, CSVs, or structured data files, use `ingest_data` for intelligent routing:

```
ingest_data(file_path="/path/to/data.csv", session_id="<session>")
```

The Brain automatically classifies the data and routes it to the optimal storage:
- Tabular data → SQLite store (queryable via bundle compiler)
- Document text → chunked and embedded in the knowledge graph
- Mixed content → both paths

## Bundle Compilation Awareness

When you call `notify_turn`, the Brain may also compile context bundles in the background. These bundles assemble:
- Exact facts (constraints, preferences)
- Semantic search results
- Graph relationship traversals
- Tabular data from ingested spreadsheets
- Synthesized summaries

The bundle compiler shapes this context for your specific agent type, so you get the most relevant information in the format you work best with.
```

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/memory-awareness/SKILL.md
git commit -m "feat(B257): upgrade memory-awareness skill with ingest_data and bundle awareness"
```

---

### Task 3: Upgrade Status Skill

**Files:**
- Modify: `plugin/skills/status/SKILL.md`

- [ ] **Step 1: Read current file**

Read `plugin/skills/status/SKILL.md`.

- [ ] **Step 2: Add compile_context token budget guidance and bundle truncation**

After the "Cross-project insights" section, add:

```markdown
## Token Budget Guidance

When using `compile_context`, specify an appropriate token budget based on your context window:

| Agent Context Size | Recommended Budget | What You Get |
|---|---|---|
| 4K-8K tokens | `token_budget=4000` | Exact facts + top 3 semantic results |
| 32K-128K tokens | `token_budget=32000` | Full semantic + graph + tabular summaries |
| 200K+ tokens | `token_budget=100000` | Everything including raw tabular data |

```
compile_context(query="<topic>", token_budget=32000, agent_type="claude_code")
```

## Bundle Truncation Awareness

When a compiled bundle exceeds the token budget, the compiler truncates lower-priority sections. If you see `"truncated": true` in a bundle response:
- The most important facts are preserved (exact constraints always survive)
- Tabular data and summaries may be compressed or omitted
- Request a larger budget if you need the full picture
- Consider narrowing your query for more focused results
```

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/status/SKILL.md
git commit -m "feat(B257): upgrade status skill with token budget guidance"
```

---

### Task 4: Upgrade Quest Management Skill

**Files:**
- Modify: `plugin/skills/quest-management/SKILL.md`

- [ ] **Step 1: Read current file**

Read `plugin/skills/quest-management/SKILL.md`.

- [ ] **Step 2: Add diff_since reference for quest switching**

After the "Setting the Quest explicitly" section, add:

```markdown
## Switching Context with Memory

When switching to a different quest or returning to a project after time away, ALWAYS call `diff_since` to see what changed:

```
diff_since(since_iso="<last session timestamp>")
```

This shows nodes created, updated, or deprecated since your last visit — crucial for catching up on changes made in other conversations or by other agents.

If you don't know the last session timestamp, use `reconstruct_timeline` to see recent activity:

```
reconstruct_timeline(quest_id="<quest>", limit=20)
```
```

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/quest-management/SKILL.md
git commit -m "feat(B257): upgrade quest-management skill with diff_since reference"
```

---

### Task 5: Verification

- [ ] **Step 1: Verify all 4 skills reference current tools**

```bash
grep -r "current_truth\|compile_context\|memory_decision\|ingest_data\|recall_procedures\|recall_relevant_lessons\|reconstruct_timeline\|diff_since" plugin/skills/
```

Expected: All tools mentioned across the skill files.

- [ ] **Step 2: Verify no references to old/missing tool names**

```bash
grep -rn "old_tool_name\|deprecated_tool" plugin/skills/
```

Expected: No matches.

- [ ] **Step 3: Final commit**

```bash
git add plugin/skills/
git commit -m "feat(B257): complete — all 4 plugin skills upgraded with Memory OS tools"
```
