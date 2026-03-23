# Retrieval Contract — SideQuests Brain

> B42 — Documents the dual-layer Concept→Artifact retrieval design so future work
> doesn't accidentally create competing or ambiguous truth layers.

---

## The Two-Layer Model

SideQuests Brain stores knowledge at two levels:

| Layer | Node Types | Purpose |
|-------|-----------|---------|
| **Concept layer** | `Concept` | Raw extracted entities from conversation (noun chunks, NER). Unconfirmed by default. |
| **Artifact layer** | `Decision`, `Constraint`, `Requirement`, `ActionItem`, `GlobalConstraint`, `GlobalPreference` | Semantically typed, higher-confidence structured knowledge. |

A concept becomes an artifact via reification: `(Concept)-[:REIFIED_AS]->(Artifact)`.

---

## What `current_truth` Searches

`current_truth` uses HNSW vector search across **artifact tables first**, with Concepts included:

```python
VECTOR_SEARCH_TABLES = [
    ("Decision",           "decision_emb_idx"),
    ("Constraint",         "constraint_emb_idx"),
    ("Requirement",        "requirement_emb_idx"),
    ("ActionItem",         "action_emb_idx"),
    ("GlobalConstraint",   "gconstraint_emb_idx"),
    ("GlobalPreference",   "gpref_emb_idx"),
    ("Concept",            "concept_emb_idx"),
]
```

Results from all tables are **merged and ranked** by a combined score:
- **50% semantic similarity** (cosine distance to query embedding)
- **30% strength signal** (`pathway_strength × confidence`, normalized to 0–1)
- **20% recency** (`1 / (1 + days_old)`)

This formula intentionally prevents stale high-strength nodes from dominating over
semantically relevant recent nodes (B31 fix).

---

## When to Stay a Concept vs Promote to Artifact

| Scenario | Treatment |
|----------|-----------|
| Extracted noun chunk, no clear semantic type | Stay as `Concept` (confidence_low=true) |
| NER entity with clear categorical meaning (org, product) | Stay as `Concept` unless explicitly confirmed |
| User/LLM explicitly states a decision | Promote → `Decision` via reification |
| Hard constraint expressed in conversation | Promote → `Constraint` or `GlobalConstraint` |
| Requirement ("needs to", "must have") | Promote → `Requirement` |
| Action item ("will do", "TODO") | Promote → `ActionItem` |

The Gated Consolidation Loop (orchestrator) handles promotion automatically during ingestion.
Manual promotion is available via the Memory Control Panel (M7 — future).

---

## `explore_graph` Entry Points

`explore_graph` operates at the **artifact layer** by default — callers start from a known
artifact node ID. It can traverse through `REIFIED_AS` to reach the concept layer, but this
is not the primary use case.

Recommended traversal starting points:
- Start from `Decision` or `Constraint` nodes (highest confidence, most connected)
- Use `REIFIED_AS` edges to discover related concepts when exploring a topic semantically
- Do **not** use `Session` as a general-purpose hop — Session is a supernode risk (B18 constraint)

---

## Interpreting Mixed-Layer Results

When `current_truth` returns both a `Concept` node and an `Artifact` node for the same idea:

1. **Prefer the artifact** — it has been semantically typed and likely has higher confidence
2. The concept's `pathway_strength` reflects how frequently the raw term has appeared in conversation
3. A concept with `confidence_low=true` was auto-extracted but never confirmed — treat with appropriate skepticism
4. If both appear with similar scores, the artifact is authoritative; the concept is corroborating signal

---

## Panel URL Deep-Links (B15)

`current_truth` responses include a `panel_url` field for the Mission Control UI:

- **Default**: `http://127.0.0.1:7800/thinking` — shows decisions, constraints, concept cloud
- **With quest_id**: `http://127.0.0.1:7800/board` — shows the Kanban board for the active quest
- **Configurable**: Set `mission_control.base_url` in `sidequests.toml` for non-default ports/hosts

LLM adapters are instructed to surface this URL as a markdown link when present.

---

## Future Work

- **B17 (Hippocampus)**: Routing is now fully implemented. `current_truth` can be filtered by quest scope.
- **B18 (Working Memory)**: `LOADED` edges track which nodes are in each context window. Smart deduplication skips already-loaded nodes.
- **M7 (Memory Control Panel)**: Full UI for browsing/editing the artifact layer. Deep-link routes for `panel_url` should be added here.
