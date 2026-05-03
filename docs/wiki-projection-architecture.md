# SideQuests Wiki Projection Architecture

**Status:** Draft / Architectural Specification (B221)
**Date:** April 28, 2026

## 1. Goal and Non-Goals

### Goal
To provide humans with a tactile, browsable, and emotionally trustworthy knowledge surface (a "Wiki") that mirrors the internal graph-native memory of SideQuests Brain without introducing data drift or stale sources of truth.

### Non-Goals
- To build a full-featured web-based Wiki engine.
- To support direct editing of Markdown files as the primary way to update the graph.
- To replace KuzuDB as the authoritative state.
- To provide real-time, per-keystroke wiki updates (updates happen during Dreaming/sweep phases).

## 2. Easy Wiki User Journeys

SideQuests provides a simple CLI interface to interact with the wiki:

- **Open the Wiki:** `sidequests wiki open`
  - If Obsidian is installed, opens the generated vault at `wiki/`.
  - Otherwise, opens the local file browser to the `wiki/` directory.
- **Get Wiki Path:** `sidequests wiki path`
  - Prints the absolute path to the current vault for use in other tools.
- **Browse Home:** User opens `Home.md` and sees a high-level index of active Quests, recent Decisions, and top-level Concepts.
- **Follow Backlinks:** User navigates to a Decision page and sees "Linked From" sections showing which Sessions or Plans referenced it.
- **Switch Persona:** User navigates to `personas/researcher/Home.md` to see a research-optimized view of the same underlying graph.

## 3. Graph-Native Source of Truth (Invariant)

**KuzuDB is the single source of truth.**

The Wiki is a **read-only projection** of the graph. Any information appearing in the Wiki must exist in KuzuDB first. Changes to knowledge must be ingested through the standard SideQuests ingestion pipeline (`notify_turn`, document ingestion, or specialized tools) and consolidated into the graph before they are projected into Markdown.

### ARC Artifact Ingestion (B225)

ARC_AGI artifacts are evidence inputs and must be imported into KuzuDB before they become browseable in the Wiki. The system provides a focused ingestion tool (`ingest_arc_artifacts`) that imports selected ARC run artifacts into durable ArcRun/ArcTaskResult/ArcEvent graph records. The Wiki MUST project from those graph records; it MUST NOT scrape or treat raw ARC JSON files as an authoritative memory store.

## 4. Obsidian as the Default UI Target

Obsidians is the recommended human interface because it provides:
- High-quality local Markdown rendering.
- Automatic backlink tracking.
- Interactive graph visualization.
- Fast local search.
- A "Memory Palace" feel through its file-based vault structure.

**Portability Fallback:** If Obsidian is not used, the projection remains 100% plain Markdown and is fully usable in any text editor, VS Code, or standard file browser.

## 5. Read-Only Markdown Projection Contract

Every generated Markdown page is a **cache artifact**.

### Page Front Matter
Each page MUST include metadata identifying it as a projection and a hash for drift detection:

```yaml
---
sidequests_projection: true
projection_version: 1
persona: "default"
generated_at: "2026-04-28T14:30:00Z"
projection_hash: "sha256:..."
source_node_ids: ["dec_123", "req_456"]
manual_edits_supported: false
---
```

### Drift Detection and Hygiene
Before overwriting a generated page, SideQuests checks for manual edits:
- **Hash Verification:** If the content below the front matter has changed, it is treated as "drift."
- **Conflict Handling:** The existing edited file is moved to `<slug>.conflict.md` to preserve the user's work, and the canonical page is regenerated from the graph.
- **Reporting:** Drift events are reported in the sweep summary and logged by the daemon.

## 6. Manual Notes (Human-Authored Content)

To prevent drift and keep the wiki interactive, SideQuests provides a dedicated area for human writing:

- **Location:** `wiki/manual-notes/`
- **Behavior:** Files in this directory are **never** overwritten by the `WikiExporter`.
- **Ingestion:** Users can write thoughts, scratchpads, or deep-dives here. These notes are ingested into the graph through normal SideQuests ingestion paths, allowing human insights to influence future "Dreaming" and automated projections.

## 7. Dreaming/Sweep as Projection Writer

The **Dreaming phase** (implemented via `mcp_engine/sweep.py`) is the primary driver for wiki updates.

- **Passive Ingestion:** Turns are ingested into the graph continuously.
- **Active Dreaming:** Periodically (or on-demand), the sweep process runs.
- **Projection Step:** As part of the sweep, the `WikiExporter` (B222) traverses the graph, filters by persona, and overwrites the Markdown projection with fresh state.

## 7. Persona Isolation

SideQuests supports multiple "lenses" into the same graph state through personas.

### Directory Structure
```text
wiki/
  Home.md (Global Redirect/Index)
  personas/
    default/
    engineer/
    researcher/
    product/
```

### Persona Definition
A persona defines how the graph is projected:
- **Scope Filters:** Which node types or domains are visible.
- **Ranking Rules:** Which information appears first (e.g., Researchers want "Hypotheses" high; Engineers want "Constraints" high).
- **Templates:** Markdown layout preferences.
- **Page Budget:** Limits on the number of related pages or backlink depth to keep the view focused.

## 8. Graph Projection Model

The wiki maps graph entities to file structures:

| Graph Entity | Wiki Mapping |
|---|---|
| `MainQuest` | Directory (e.g., `quests/my-project/`) |
| `Decision`, `Requirement`, `Constraint` | Individual `.md` page |
| `Concept` | Individual `.md` page (if confidence > threshold) |
| `Lesson` | Section within a related page or dedicated index |
| `Message` | Not projected directly (remains in private transcript) |

### Relationship Projections
- **`GENERATED_FROM`**: Provenance links in front matter.
- **`MENTIONS`**: Wiki-style `[[Internal Links]]` within page content.
- **`RELATED_PAGE`**: A "See Also" section generated from 1-2 hop graph neighborhoods.

## 9. Traversal and Performance Guardrails

To prevent "Graph Bloat" and "Obsidian Noise":
- **Bounded Neighborhoods:** Related-page links are capped (e.g., top 5 most relevant by pathway strength).
- **Depth Limits:** Projections only traverse 1-2 hops from the primary node.
- **Deduplication:** The exporter ensures a single canonical page per stable graph identity.
- **Lazy Loading:** For extremely large graphs, only the most "active" (high pathway strength) nodes are projected into the wiki.

## 10. Token and Context Efficiency

The Wiki projection also serves as a **context compression engine**:
- Agents can read the generated Wiki pages instead of performing raw graph traversals to get a "human-readable" summary of a project.
- The same summaries shown to humans in the Wiki are used for agent decision support, ensuring alignment between human and AI mental models.

## 11. Failure Modes and Guardrails

- **Stale Projection:** If the daemon isn't running, the Wiki won't update. The `generated_at` timestamp warns the user.
- **Broken Links:** If a node is archived or deleted in the graph, the exporter must remove the corresponding Wiki page and update links in other pages.
- **Information Leakage:** Persona isolation must be rigorously applied during the export phase to prevent "Researcher" data from appearing in a "Public" persona projection.

## 12. Relation to Competitors

- **Obsidian/Quartz:** SideQuests is the *engine* that feeds them. It isn't a competitor to the renderer.
- **Flat-File Wikis:** SideQuests neutralizes the "drift" problem of manual wikis by generating the surface from an auditable, structured graph.
- **Memory Palace:** The directory structure and persona isolation provide the spatial anchoring missing from flat vector stores.
