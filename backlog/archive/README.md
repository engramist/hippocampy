# Archived / Migrated Backlog Material

This folder records backlog material that was intentionally removed from `sidequests-brain`
after the ARC-AGI solver/runtime was extracted into the sibling `ARC_AGI` repository.

The canonical copies of ARC-specific cards and plans now live with the ARC codebase. This
repo keeps the graph-memory engine roadmap, plus ARC-facing memory integration cards when
they describe SideQuests-owned ingestion, schema, retrieval, or wiki projection behavior.

## Migrated To `ARC_AGI`

The following tracked SideQuests backlog ranges were removed from this repository because
they describe ARC solver/runtime, benchmark harness, puzzle execution policy, or ARC-only
evaluation work:

- B54-B60
- B87-B126
- B130-B159
- B161-B190
- B197-B218
- Matching `backlog/plans/` files for those ARC-focused cards

## Retained Here

SideQuests keeps cards/plans for memory-engine work that external ARC consumers use through
the graph-native interface:

- B220: Post ARC-AGI extraction cleanup audit
- B221-B224: graph-native wiki projection
- B225: ARC artifact ingestion into graph memory
- B226-B229: ARC mechanic/world-model memory integration

## Rule Of Thumb

If a card changes ARC gameplay, puzzle solving, benchmark submission, or agent orchestration,
it belongs in `ARC_AGI`. If it changes Kuzu schema, MCP tools, adapters, retrieval, ingestion,
or wiki projection owned by SideQuests, it belongs here.
