# SideQuests Local Graph Visibility UI

This is an **optional debugging workflow**, not part of the default SideQuests runtime or install
path. It uses the archived official Kùzu Explorer project as the browser UI for inspecting the
SideQuests graph.

- Upstream base: [kuzudb/explorer](https://github.com/kuzudb/explorer)
- Default mode: `MODE=READ_ONLY`
- Local UI: `http://localhost:8000`

## What This Workflow Is For

Use this when you want to inspect the live graph directly instead of inferring behavior only from
JSON exports or logs.

It is useful for:

- recent writes during ARC runs
- plans and plan steps
- lessons
- hypotheses
- current session / loaded-memory state

It is not intended to be a required part of `sidequests setup`, daemon startup, or the main
product UX.

## SideQuests Database Paths

The repo uses plain Kùzu database files in `~/.sidequests/`.

Known paths in this workspace:

- `~/.sidequests/brain.db` - the main Brain Daemon database
- `~/.sidequests/brain_single_test.db` - the single-puzzle / smoke-test database
- `~/.sidequests/brain_test.db` - additional local test database
- `~/.sidequests/brain_test_anomaly.db` - anomaly-test database

Explorer mounts the parent directory as `/database` and uses `KUZU_FILE=<file name>`, so the
commands below always point at the file name, not the absolute path inside the container.

## Safe Default: Read-Only Snapshot

If the daemon may still be running, launch Explorer against a snapshot copy instead of the live
database file. That keeps the workflow isolated and avoids lock/contention surprises.

Recommended snapshot flow:

```bash
mkdir -p /tmp/sidequests-kuzu-explorer
cp ~/.sidequests/brain.db /tmp/sidequests-kuzu-explorer/brain.db
docker run -p 8000:8000 \
  -v /tmp/sidequests-kuzu-explorer:/database \
  -e KUZU_FILE=brain.db \
  -e MODE=READ_ONLY \
  --rm kuzudb/explorer:latest
```

If you want to inspect the single-puzzle smoke database instead, substitute
`brain_single_test.db` in the snapshot directory and `KUZU_FILE`.

## Optional Helper Script

For a manual, safer launch path, use:

```bash
bash tools/graph_viewer/open_kuzu_explorer.sh ~/.sidequests/brain.db
```

The helper script copies the selected database into a temporary snapshot directory, launches
Explorer in read-only mode, and deletes the snapshot when the container exits.

You can point it at any local SideQuests Kùzu file:

```bash
bash tools/graph_viewer/open_kuzu_explorer.sh ~/.sidequests/brain_single_test.db
bash tools/graph_viewer/open_kuzu_explorer.sh ~/.sidequests/brain_test.db
```

## Official Launch Commands

The upstream Explorer repo documents two launch patterns. For SideQuests, use the read-only form:

```bash
docker run -p 8000:8000 \
  -v {path to the directory containing the database file}:/database \
  -e KUZU_FILE={database file name} \
  -e MODE=READ_ONLY \
  --rm kuzudb/explorer:latest
```

If you want to inspect a non-live database without the helper script, mount the directory that
contains the `.db` file and use the file name for `KUZU_FILE`.

## Verification

Use the helper script against a real local SideQuests database file, then confirm the browser UI
opens and renders graph data:

```bash
bash tools/graph_viewer/open_kuzu_explorer.sh ~/.sidequests/brain_single_test.db
```

Then verify:

- Explorer opens at `http://localhost:8000`
- the database loads without modifying the source file
- `Session`, `Plan`, `Lesson`, and `Hypothesis` nodes are visible in the UI

## Starter Queries

These queries are intended as a starter pack for common SideQuests debugging tasks. Replace the
placeholder strings where needed.

### 1) Recent sessions and working-memory state

```cypher
MATCH (s:Session)
RETURN s.session_id, s.started_at, s.last_active_at, s.routing_state,
       s.loaded_node_count, s.injection_count, s.dedup_tokens_saved
ORDER BY s.last_active_at DESC
LIMIT 10;
```

### 2) Recent message provenance

```cypher
MATCH (m:Message)-[:SENT_IN]->(s:Session)
RETURN s.session_id, m.message_id, m.role, m.created_at, m.text_raw
ORDER BY m.created_at DESC
LIMIT 25;
```

### 3) Plans and plan steps

```cypher
MATCH (p:Plan)
OPTIONAL MATCH (ps:PlanStep)-[:STEP_OF]->(p)
RETURN p.plan_id, p.goal, p.strategy, p.status, p.created_at,
       ps.step_number, ps.status, ps.description, ps.actual_outcome, ps.valence
ORDER BY p.created_at DESC, ps.step_number ASC
LIMIT 100;
```

### 4) Lessons produced by quests

```cypher
MATCH (mq:MainQuest)-[:PRODUCED_LESSON]->(l:Lesson)
RETURN mq.quest_id, l.lesson_id, l.domain, l.lesson_type, l.confidence,
       l.pathway_strength, l.created_at, l.text_raw
ORDER BY l.created_at DESC
LIMIT 25;
```

### 5) Hypotheses currently in the graph

```cypher
MATCH (h:Hypothesis)
RETURN h.id, h.task_id, h.game_type, h.category, h.status, h.confidence,
       h.evidence_count, h.created_at, h.description
ORDER BY h.created_at DESC
LIMIT 50;
```

### 6) ARC-specific hypothesis slice

```cypher
MATCH (h:Hypothesis)
WHERE h.task_id IS NOT NULL
RETURN h.task_id, h.id, h.game_type, h.category, h.status, h.confidence, h.description
ORDER BY h.created_at DESC
LIMIT 100;
```

### 7) Current-memory slice from a session

```cypher
MATCH (s:Session)-[:LOADED]->(c:Concept)
RETURN s.session_id, c.concept_id, c.text_raw, c.gist_class, c.schema_org_type, c.confidence
ORDER BY c.last_accessed_at DESC
LIMIT 50;
```

### 8) Neighborhood around a concept

```cypher
MATCH (c:Concept)-[r]->(n)
WHERE c.text_raw = 'replace-with-your-concept'
RETURN c, r, n
LIMIT 50;
```

## What To Look For During a Live ARC Run

When an ARC run is active, the most useful checks are:

- the newest `Hypothesis` nodes for the current `task_id`
- the newest `Plan` and `PlanStep` chain
- `Session` rows showing the current working-memory load
- any `Message` rows that correspond to recent consolidation or lesson generation

If you want the step-by-step ARC write trace as well, keep using
`submission_results_single.json` alongside Explorer. Explorer shows the graph state; the JSON
export shows the exact per-step trace that got written into it.
