# B-102 — Local Graph Visibility UI with Kuzu Explorer

## Metadata
- Card: B102
- Priority: P2
- Dependencies: B92, B93, B94

## Summary

Create a local graph-debugging workflow for SideQuests using the official Kùzu Explorer project as
the base UI, so we can directly inspect graph writes during ARC runs.

This is explicitly an optional install/debugging path. It must not become part of the default
SideQuests install, runtime startup path, or core product surface.

## Technical Approach

1. Use the official Kùzu Explorer repository/image as the base:
   - [kuzudb/explorer](https://github.com/kuzudb/explorer)
2. Prefer a minimal integration layer:
   - documented Docker launch command(s)
   - SideQuests database path mapping
   - read-only mode by default
   - optional/manual launch only
3. Add SideQuests-focused debugging documentation:
   - which database file/path to open
   - how to inspect recent writes
   - how to inspect `Plan`, `PlanStep`, `Lesson`, `Hypothesis`, and ARC-specific artifacts
4. Add starter Cypher/SQL-style query snippets for common debugging tasks.
5. If needed, add a lightweight helper script or docs page in this repo that launches Explorer
   against the local SideQuests database safely.

## Concrete File Changes

- `tools/graph_viewer/README.md`
  - add a graph-visibility guide for SideQuests
- `tools/graph_viewer/open_kuzu_explorer.sh`
  - optional helper launcher for Kùzu Explorer in read-only mode
- `README.md` or a focused debug doc
  - link the workflow as an optional debug tool if appropriate
- `backlog/masterBacklogTracker.md`
  - track the plan linkage

## API/Schema/Test Updates

- No SideQuests schema changes required.
- No core memory-semantics changes required.
- Verification can be manual/documented rather than pytest-heavy, unless a helper script is added.

## Acceptance Criteria

1. The repo contains a documented SideQuests graph-visibility workflow based on Kùzu Explorer.
2. The default workflow opens the database in read-only mode.
3. The docs include the database mount/path and launch command(s).
4. The docs include starter queries for plans, lessons, hypotheses, and ARC debug artifacts.
5. A real local SideQuests database from this project can be opened and inspected with the
   documented workflow.
6. Nothing in the default `sidequests setup`, daemon startup path, or core runtime depends on this
   UI being installed.

## Validation Commands

Primary validation is manual:

```bash
docker run -p 8000:8000 \
  -v {sidequests database directory}:/database \
  -e KUZU_FILE={database file name} \
  -e MODE=READ_ONLY \
  --rm kuzudb/explorer:latest
```

Then verify in browser:
- Explorer opens on `http://localhost:8000`
- the SideQuests database loads
- starter queries return expected nodes/edges

## Risks / Constraints

- The official `kuzudb/explorer` repository is archived as of October 10, 2025, so this effort
  should treat it as a stable base rather than something we expect to upstream into.
- Read-only mode should be the default because this UI is for graph inspection/debugging, not
  mutation.
- Keep this effort out of the main product path. The goal is optional developer visibility, not a
  required application dependency.
