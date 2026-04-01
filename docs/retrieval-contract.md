# Concept→Artifact Retrieval Contract

This document defines the normative behavior for retrieval across the SideQuest Brain’s dual-layer graph (Concept layer and Artifact layer). It ensures predictable results for MCP adapters, tests, and future ranking implementations.

## 1. Purpose and Scope
The SideQuest Brain maintains knowledge at two levels of abstraction:
1.  **Concept Layer:** High-recall, low-precision nodes extracted via NER and Hebbian co-occurrence.
2.  **Artifact Layer:** High-precision, high-confidence nodes (Decisions, Constraints, etc.) reified from concepts.

The **Retrieval Contract** defines how these layers interact during a `current_truth` or `explore_graph` call.

## 2. Data Layers and Identity

### 2.1 The Concept Layer (`Concept`)
*   **Identity:** Every distinct entity mentioned in conversation becomes a `Concept` node.
*   **Relationships:** Concepts are linked via semantic named edges (e.g., `REQUIRES`, `ENABLES`) or implicit `CO_OCCURS_WITH` edges.
*   **Searchability:** Concepts carry their own embeddings and SKOS-inspired `Label` nodes (`prefLabel`, `altLabel`).

### 2.2 The Artifact Layer (`Decision`, `Constraint`, etc.)
*   **Identity:** When a Concept (or a group of concepts in a message) is classified at >90% confidence as an architectural artifact, an Artifact node is created.
*   **The Bridge (`REIFIED_AS`):** Artifact nodes are linked back to their source Concept(s) via `(Concept)-[REIFIED_AS]->(Artifact)`.
*   **Provenance:** Artifacts are also linked to the `Message` or `DocumentExtract` that established them.

## 3. `current_truth` Retrieval Rules

`current_truth` is the primary interface for LLMs to query the Brain. It performs a unified vector search across both layers.

### 3.1 Return-Shape Rules
*   **Mixed Results:** `current_truth` MUST return a flat list of results from all artifact tables PLUS the `Concept` table.
*   **Node Inclusion:** A node is included if it matches the vector query and is NOT `archived`.
*   **No Auto-Expansion:** `current_truth` returns the specific matching node. It does NOT automatically traverse `REIFIED_AS` to find the linked artifact if a Concept matches (traversal is the role of `explore_graph`).

### 3.2 Ranking Semantics
Results are ranked using a multi-factor scoring formula:
1.  **Semantic Similarity (50%):** Vector cosine similarity to the query.
2.  **Strength Signal (30%):** `pathway_strength × confidence`.
3.  **Recency (20%):** A decay function based on the `created_at` timestamp.

**Rule:** Highly relevant new concepts can outrank old high-strength artifacts if the semantic match is significantly stronger.

## 4. `explore_graph` Traversal Behavior

`explore_graph` allows for directed movement through the graph structure.

*   **Layer Hopping:** Callers SHOULD use `explore_graph` to move between layers.
    *   Example: Find a `Concept` via `current_truth`, then `explore_graph` with `relationship_type="REIFIED_AS"` to find associated Decisions.
*   **Directionality:**
    *   `Concept → Artifact` is an **outgoing** `REIFIED_AS` edge.
    *   `Artifact → Concept` is an **incoming** `REIFIED_AS` edge.
*   **Constraint:** Traversal is limited to allowlisted relationship types (see `mcp_engine/tools.py`) and a maximum depth of 3.

## 5. Concrete Query Examples

### Example 1: Artifact-First Question
**Query:** "What did we decide about the database?"
1.  `current_truth` matches a `Decision` node: *"We chose Kùzu as our embedded graph DB."*
2.  **Result Shape:** Artifact-only (Decision table).
3.  **Interpretation:** High confidence. LLM presents this as the "resolved truth."

### Example 2: Concept-Only Fallback
**Query:** "Tell me about RyuGraph."
1.  No reified Decision or Constraint exists yet.
2.  `current_truth` matches a `Concept` node: *"RyuGraph"* (gist:Product).
3.  **Result Shape:** Concept-only.
4.  **Interpretation:** LLM sees the concept exists in the graph but lacks a formal artifact status. It can mention it as a "known concept" from past turns.

### Example 3: Mixed Result Interpretation
**Query:** "Database performance constraints."
1.  `current_truth` returns:
    *   `Constraint`: *"Must support <50ms local reads."* (Rank 1, similarity 0.95)
    *   `Concept`: *"HNSW Indexing"* (Rank 2, similarity 0.88)
2.  **Result Shape:** Mixed (Constraint + Concept).
3.  **Interpretation:** The LLM should prioritize the `Constraint` as a hard rule, while using the `Concept` to provide technical context about how that constraint is met.

## 6. Known Limits and Non-Goals
*   **Non-Goal: Deduplication.** If a Concept and its reified Decision both match a query with high similarity, both may appear in the results. The LLM is responsible for synthesizing these into a coherent answer.
*   **Limit: Deep Traversal.** `current_truth` does not perform graph-walking; it is a vector-first entry point. Use `explore_graph` for relational discovery.
*   **Limit: Schema Evolution.** If a relationship type is not in the allowlist in `tools.py`, it cannot be traversed via `explore_graph` even if it exists in the Kùzu DB.

## 7. Meta-Harness Experience Store Queries (B104)

The **Meta-Harness** is an outer loop that evolves the **ARC Harness**. It uses a separate experience store in SideQuests to support the following retrieval questions:

1.  **Harness Improvement**: Which `HarnessCandidate` versions improved scores without exceeding the token/runtime budget?
2.  **Failure Modes**: Which `HarnessMutation` (e.g., "aggressive prompting") repeatedly caused the same `HarnessFailureCluster` across multiple puzzle sets?
3.  **Cross-Puzzle Relevance**: Which prior `HarnessCandidate` performed best on puzzles with a similar failure signature to the current one?
4.  **Trace Analysis**: Which `PuzzleTraceRef` promoted action facts or path hypotheses that later correlated with a successful solve?
5.  **Policy Regressions**: Which regressions are linked to `HarnessMutation` in the retrieval policy versus the solve-policy?

The Experience Store maintains relationships between harness versions, eval runs, and traces to make these lineage-heavy queries possible.
