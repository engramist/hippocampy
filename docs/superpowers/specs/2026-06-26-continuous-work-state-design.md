# Continuous Work State (CWS)
_Spec date: 2026-06-26_

## Problem

When a user hits a token limit in one agent (Claude Code, Codex, Gemini CLI, VS Code Copilot) and switches to another, the receiving agent starts cold. Querying Campy with vague intent like "pick up where we left off" fails because work context lives in raw `notify_turn` captures that haven't been distilled into searchable Lessons yet — the GCL sweep runs every 300 seconds, too slow for a mid-session handoff.

The core mismatch: "continue" and "pick up" are **temporal** intents but `compile_context` is a **semantic** retrieval engine. Time-anchored retrieval needs a different path.

## Goal

Any agent, on any platform, can pick up exactly where the previous agent left off — within seconds of the last turn, with no user action required beyond switching agents.

## Confirmed Design Decisions

| Decision | Choice |
|----------|--------|
| Write trigger | Automatic on every turn (hot write in `notify_turn`) |
| Storage | WorkSummary node in KuzuDB + `## Current Work` section in `CONTEXT.md` |
| Content shape | Layered: resume line (~50 tokens) every turn + full snapshot (~800 tokens) every 10 turns |
| Delivery | `session_start` hook injects resume line before first agent message |
| Git branch capture | Daemon reads `git -C repo_root branch --show-current` server-side |
| Cross-agent writes | All agents already route through same `notify_turn` MCP tool — no per-platform write code |
| Post-commit checkpoint | `.githooks/post-commit` fires `notify_turn` on every git commit |

---

## Architecture

### 1. WorkSummary Node (new schema node)

```
WorkSummary {
  summary_id      STRING   PRIMARY KEY  ("ws-{session_id}")
  session_id      STRING               FK → Session
  agent_source    STRING               claude_code | codex | gemini_cli | vscode
  git_branch      STRING               read daemon-side
  git_commit      STRING               7-char short hash of HEAD
  active_card     STRING               e.g. "B288" — inferred from active Plan
  resume_line     STRING               ~50 tokens, updated every turn
  snapshot_text   STRING               ~800 tokens, updated every 10 turns
  turn_count      INT32
  last_updated_at TIMESTAMP
}
```

One WorkSummary per session. The session_start hook always queries the most recent one:
```cypher
MATCH (ws:WorkSummary) 
ORDER BY ws.last_updated_at DESC 
LIMIT 1
```

### 2. Hot Write Pipeline

`notify_turn` fires a non-blocking background coroutine after every turn lands:

```python
asyncio.create_task(_update_work_summary(session_id, db, config))
```

`_update_work_summary` is **entirely rule-based** (no LLM call):

**Every turn — resume line:**
1. Read `git branch --show-current` and `git log -1 --format=%h` from `repo_root`
2. Query active Plan for this session (most recent `PLANNED_IN` edge)
3. Infer `active_card` from Plan title (regex: first word matching `B\d+`); fall back to `"No active card"` if no Plan is linked to the session
4. Build: `"Working on {card} (branch: {branch} · {sha7}). Next: {plan_next_step}. Last active: {ts} via {agent_source}."` — if no active card: `"No active card (branch: {branch} · {sha7}). Last active: {ts} via {agent_source}."`
5. Upsert WorkSummary node
6. Rewrite `## Current Work` section in `CONTEXT.md`

**Every 10th turn — full snapshot (appended to snapshot_text):**
1. Fetch last 20 Messages from this session ordered by `created_at`
2. Fetch Decisions made this session (via `ESTABLISHED_IN` edges)
3. Extract file paths from message text (regex: paths containing `/` and a file extension)
4. Query open loops (`get_open_loops` for this session)
5. Format as structured markdown (see CONTEXT.md section below)

### 3. CONTEXT.md Integration

`_update_work_summary` writes directly to `CONTEXT.md`. It owns the `## Current Work` section exclusively. `campy context regen` detects this header and leaves everything between it and the next `##` untouched.

**File format:**

```markdown
## Current Work
_Last active: 2026-06-26 20:53 via claude_code — branch: main (abc1234)_

**Resume:** Working on B288. Next: add compile_context to index.ts.

<details>
<summary>Session snapshot (turn 47)</summary>

**Active card:** B288 — Reconcile Adapter Tool Surfaces  
**Branch:** main · abc1234  
**Files in flight:** extensions/hippocampy/src/index.ts, tests/test_analogical.py  
**Recent decisions:**
- Use registry-derived assertion for test_codex_adapter_has_all_tools
**Open loops:**
- Add compile_context and ingest_data to OpenClaw toolDefinitions

</details>
```

The `<details>` block keeps the resume line at low token cost; agents expand the snapshot only when they need the full context. The git history of `CONTEXT.md` is the versioned handoff log — every snapshot update that gets committed is a point-in-time record.

### 4. Session Start Delivery

**Claude Code** — `session_start.sh` gets a new block at the top:

```bash
# Inject resume line from CONTEXT.md Current Work section
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
RESUME=$(grep -A 2 "^## Current Work" "$REPO_ROOT/CONTEXT.md" 2>/dev/null \
  | grep "^\*\*Resume:\*\*" | sed 's/\*\*Resume:\*\* //')
if [ -n "$RESUME" ]; then
  # Validate branch still exists (BSD-compatible sed, no -P grep)
  BRANCH=$(echo "$RESUME" | sed -n 's/.*branch: \([^ ·)]*\).*/\1/p')
  if [ -n "$BRANCH" ] && ! git branch --list "$BRANCH" | grep -q "$BRANCH"; then
    RESUME="$RESUME (branch $BRANCH no longer exists — may have been merged)"
  fi
  echo "[Campy] $RESUME"
fi
```

No daemon query, no DB read — grep on a file already on disk. Fast, works offline.

**Delivery by platform:**

| Agent | Mechanism |
|-------|-----------|
| Claude Code | `session_start.sh` — updated as above |
| Codex | `session_start.py` (B265) — same logic in Python |
| Gemini CLI | `session_start.py` (B265) — same logic in Python |
| VS Code Copilot | `.github/copilot-instructions.md` already references `CONTEXT.md` — `## Current Work` visible with no hook needed |

### 5. Post-Commit Git Hook

`.githooks/post-commit`:

```bash
#!/usr/bin/env bash
# Force a WorkSummary checkpoint on every git commit.
COMMIT=$(git log -1 --oneline)
campy notify-turn --role system --content "committed: $COMMIT" 2>/dev/null || true
```

Installed by `campy setup` via `git config core.hooksPath .githooks`. The `|| true` ensures a missing daemon never blocks a commit.

---

### 6. WorkArtifact — Document Provenance Tracking

Any time an agent creates or materially edits a structured document (`.md` files: plans, specs, backlog cards, ADRs, READMEs), a `WorkArtifact` node is written to the graph capturing its location and provenance. This makes "files in flight" in the WorkSummary snapshot an authoritative graph query rather than a regex heuristic.

**Node schema:**

```
WorkArtifact {
  artifact_id      STRING    PRIMARY KEY
  file_path        STRING    (repo-relative, e.g. "backlog/B290.md")
  document_type    STRING    (plan | spec | backlog_card | adr | readme | other)
  title            STRING    (first H1 heading, extracted from file)
  summary          STRING    (~100 chars — first non-heading paragraph, extracted from file)
  linked_card      STRING    (e.g. "B290" — from filename regex or register_artifact call)
  session_id       STRING    FK → Session
  agent_source     STRING    (claude_code | codex | gemini_cli | vscode)
  created_at       TIMESTAMP
  last_modified_at TIMESTAMP
}
```

**Relationships:**
- `(WorkArtifact)-[:CREATED_IN]->(Session)`
- `(WorkArtifact)-[:DOCUMENTS]->(Plan)` — when `linked_card` resolves to a Plan node

**Two-path capture:**

*Path 1 — PostToolUse hook (automatic, zero agent burden):*
The `post_tool_use.sh` / `post_tool_use.py` hook detects Write or Edit tool calls targeting `*.md` files. It:
1. Extracts `title` via `grep -m1 "^# " <file> | sed 's/^# //'`
2. Extracts `summary` via first non-heading line > 20 chars
3. Infers `document_type` from path (`backlog/` → backlog_card, `docs/superpowers/specs/` → spec, `backlog/plans/` → plan, etc.)
4. Infers `linked_card` from filename regex (`B\d+`)
5. Fires a bare `register_artifact` MCP call with these fields

*Path 2 — `register_artifact` MCP tool (explicit enrichment):*
When an agent has richer context (knows the linked card, has a better summary), it calls `register_artifact` directly. Both paths upsert by `file_path` — the explicit call wins on any field it provides.

**WorkSummary integration:**
`_update_work_summary` replaces the file-path regex with a graph query:
```cypher
MATCH (wa:WorkArtifact)-[:CREATED_IN]->(s:Session {session_id: $sid})
RETURN wa.file_path, wa.document_type, wa.title
ORDER BY wa.last_modified_at DESC
LIMIT 10
```

**New components for this section:**

| Component | File | Notes |
|-----------|------|-------|
| WorkArtifact node DDL | `campy/brain/hippocampus/schema.py` | New node table + `CREATED_IN` + `DOCUMENTS` rel tables |
| `register_artifact` MCP tool | `campy/brain/thalamus/tools/__init__.py` | Upsert WorkArtifact; resolve Plan link if linked_card matches |
| PostToolUse hook extension | `adapters/claude_code/hooks/post_tool_use.sh` | Detect `*.md` Write/Edit, fire register_artifact |
| Codex PostToolUse extension | `adapters/codex/hooks/post_tool_use.py` | Same logic in Python (B265) |
| Gemini AfterTool extension | `adapters/gemini_cli/hooks/after_tool.py` | Same logic in Python (B265) |

---

## What Doesn't Change

- `compile_context` — unchanged. CWS is a parallel retrieval path for temporal intent, not a replacement for semantic retrieval.
- GCL sweep interval — stays at 300s. Full distillation (embeddings, consistency audit) is still async.
- `notify_turn` signature — unchanged. The background task is internal.
- `campy context regen` — unchanged except it skips the `## Current Work` section.

---

## New Components

| Component | File | Notes |
|-----------|------|-------|
| WorkSummary node DDL | `campy/brain/hippocampus/schema.py` | New node table + migration entry |
| `_update_work_summary` | `campy/brain/thalamus/tools/work_summary.py` | New module, called from notify_turn |
| Hook in notify_turn | `campy/brain/thalamus/tools/__init__.py` | One `asyncio.create_task` call |
| CONTEXT.md writer | `campy/brain/thalamus/tools/work_summary.py` | Writes `## Current Work` section |
| `campy context regen` guard | `campy/cli/context.py` | Skip `## Current Work` section |
| session_start.sh update | `adapters/claude_code/hooks/session_start.sh` | Resume line injection block |
| post-commit hook | `.githooks/post-commit` | New file |
| `campy notify-turn` CLI command | `campy/cli/notify_turn.py` | Thin CLI wrapper over `call_brain("notify_turn", ...)` — required by post-commit hook |
| `campy setup` wiring | `adapters/claude_code/setup.py` | `git config core.hooksPath .githooks` |
| WorkArtifact node DDL | `campy/brain/hippocampus/schema.py` | New node + rel tables (see Section 6) |
| `register_artifact` MCP tool | `campy/brain/thalamus/tools/__init__.py` | Upsert WorkArtifact with Plan link resolution |
| PostToolUse hook extension | `adapters/claude_code/hooks/post_tool_use.sh` | Auto-capture on `*.md` Write/Edit |

---

## Acceptance Criteria

- [ ] After 1 turn in Claude Code, `CONTEXT.md` contains a `## Current Work` section with a populated resume line
- [ ] After 10 turns, the `<details>` snapshot block is populated with decisions and files
- [ ] A new Claude Code session injects the resume line as the first system context line
- [ ] A git commit triggers a WorkSummary update (post-commit hook fires)
- [ ] After branch merge and deletion, session_start appends the "may have been merged" note
- [ ] Codex session_start.py reads and outputs the resume line identically to Claude Code
- [ ] `campy context regen` does not overwrite the `## Current Work` section
- [ ] WorkSummary node is queryable: `MATCH (ws:WorkSummary) ORDER BY ws.last_updated_at DESC LIMIT 1`
- [ ] All existing tests pass — notify_turn is backward-compatible
- [ ] Creating a `.md` file via Write tool causes a WorkArtifact node to appear in the graph within one turn
- [ ] WorkArtifact node has populated `title`, `summary`, `document_type`, `linked_card` (where inferrable)
- [ ] `register_artifact` MCP tool upserts correctly and resolves Plan link when linked_card matches
- [ ] WorkSummary "files in flight" uses graph query (not regex) and lists WorkArtifacts created this session

---

## Backlog Card

**B290 — Continuous Work State (CWS)**  
Priority: P1 (core use case — cross-agent handoff)  
Dependencies: B265 (cross-agent hooks) for full Codex/Gemini delivery; CWS itself has no blocking dependencies and can ship independently.
