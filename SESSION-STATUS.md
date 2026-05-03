# SideQuests Brain — Session Status

> Repo-tracked handoff doc so any machine can pick up where work left off.
> Update this at the end of every working session.

---

## Last Updated: 2026-04-28

### Current State
- Backlog tracker is current: [backlog/masterBacklogTracker.md](backlog/masterBacklogTracker.md) shows 185 complete.
- B220 (ARC Extraction Cleanup) is complete, stabilizing the repo after the ARC split.
- B221-B224 (Wiki Projection System) is complete and validated:
  - Graph-native architecture documented in `docs/wiki-projection-architecture.md`.
  - Read-only Markdown exporter implemented in `mcp_engine/wiki_projection.py` and wired into background Dreaming/sweep.
  - Persona isolation allows multiple lenses (Engineer, Researcher) over the same graph.
  - Drift guard prevents accidental data loss from local edits via conflict copies.
  - CLI surface extended: `sidequests wiki path|status|open` with `--persona` support.

### Verified This Session
- Wiki Projection test suite is green:
  - `pytest -q tests/test_wiki_projection.py tests/test_wiki_projection_personas.py tests/test_wiki_projection_drift.py tests/test_cli_wiki.py`
  - Result: `41 passed`
- Core Dreaming/Sweep regression is green:
  - `pytest -q tests/test_b191_dreaming.py tests/test_sweep.py`
  - Result: `28 passed`
- ARC Cleanup regression (selected):
  - `pytest -q tests/test_adapters.py tests/test_b128_dag_tools.py tests/test_schema.py`
  - Result: `200 passed (6 skipped)`

### Stabilization Notes
- `mcp_engine/wiki_projection.py` uses atomic writes with temp files.
- Drift detection uses a stable hash in front matter, ignoring the `generated_at` timestamp.
- CLI `open` command uses `obsidian://` URIs on macOS with fallback to folder opening.
- `sidequests.toml` updated with example persona configurations.

### Important Context
- KuzuDB version is pinned at `0.11.3`. Ensure `.venv` has it installed (`pip3` or `python -m pip` may be required if `pip` is missing).
- The Wiki projection is **read-only**. Human edits should live in `wiki/manual-notes/` to be ingested into the graph later.
- `.gitignore` updated to ignore generated wiki artifacts by default.

### Next Recommended Work
1. **Refine Clustering**: Improve the "Topics" and "Sources" automatic clustering in the wiki index pages.
2. **Wiki-as-RAG**: Test if agents can use the generated wiki pages as a high-quality RAG source to reduce raw graph traversal costs.
3. **Manual Note Ingestion**: Implement the bridge to ingest `wiki/manual-notes/` back into the graph.
4. **Obsidian Plugin-Free UX**: Audit the generated vault for a better "out of the box" experience in Obsidian (e.g., folder notes, pre-configured graph view filters).

### Immediate Next Step
- Active next step: Verify wiki projection utility in a real multi-agent workflow (e.g., have one agent solve a task and another browse the resulting wiki to confirm handoff quality).
- Focus files: `mcp_engine/wiki_projection.py`, `docs/wiki-projection-architecture.md`, `sidequests.toml`.
