# SideQuests Graph Schema Review

## Summary

SideQuests is a strong graph fit. The core workloads are relationship-centric rather than purely set-based: cross-session recall, quest routing, artifact provenance, semantic links between concepts, and directed exploration of connected knowledge. The current choice of a labeled property graph backed by Kuzu is a good match for the application-facing, traversal-first behavior in this repo.

The schema also follows several good graph-design instincts already:

- Traversal-first operational model rather than BI-first analytics
- Native relationship types for semantic meaning like `REQUIRES`, `CHOSEN_OVER`, `PART_OF`, `WORKING_ON`, and `LOADED`
- Edge properties where the relationship itself carries facts such as confidence, timestamps, source, count, and strength
- Separate artifact types for operational use (`Decision`, `Constraint`, `Requirement`, `ActionItem`) instead of flattening everything into one table
- A clear session/quest layer that can support context continuity and handoff behavior

## Architecture Fit

From a graph-solutions perspective, the strongest graph-native use cases in SideQuests are:

- Knowledge graph / metadata graph:
  Concepts, ontology routing, schema.org typing, labels, and semantic relations all benefit from traversable structure.
- Dependency and impact analysis:
  Quests, side quests, lessons, constraints, and future `explore_graph` queries are naturally graph-shaped.
- Provenance and lineage:
  Messages, document extracts, merge events, and establishment relationships are building blocks for explainable memory.
- Recommendation and routing:
  Hippocampus session routing and analogical search both benefit from connected graph state, not just flat vector recall.

This means the repo is not just "using a graph database because the data is connected." The hot queries genuinely depend on traversing meaningful relationships.

## What Looks Strong

### 1. LPG is the right model here

The current model is operational and developer-facing, so a labeled property graph is a better fit than RDF:

- direct node and edge modeling
- native edge metadata
- traversal-oriented recall and exploration
- practical application integration through Cypher-like access patterns

That matches the repo's current Kuzu abstraction and avoids forcing RDF-style semantics where they are not needed for the core product.

### 2. Relationship semantics are explicit

The schema has a healthy set of named relationship tables in [mcp_engine/schema.py](/Users/djshelton/Desktop/GitProjects/sidequests-brain/mcp_engine/schema.py), especially:

- session provenance: `WORKING_ON`, `SENT_IN`, `LOADED`, `USED`
- knowledge evolution: `CO_OCCURS_WITH`, `REIFIED_AS`, `DEPRECATED_BY`, `TRIGGERED`, `UPDATES_PATHWAY`
- semantic meaning: `REQUIRES`, `ENABLES`, `REPLACES`, `CONTRADICTS`, `PART_OF`, `CHOSEN_OVER`, `IMPLEMENTS`, `EXTENDS`, `ALTERNATIVE_TO`

This is exactly the kind of relationship-first modeling a graph system should exploit.

### 3. Edge properties are used correctly

The graph does not over-promote every fact to a node. Important relationship-scoped facts remain edge properties:

- `LOADED.injected_at`, `LOADED.token_estimate`, `LOADED.source`
- `CO_OCCURS_WITH.count`, `CO_OCCURS_WITH.strength`
- semantic edge confidence/timestamps/inference source
- `REROUTED_FROM.rerouted_at` and `reason`

That is good LPG discipline.

## Findings

### Finding 1. Concept is doing too much work as the canonical junction layer

The schema and loop design make `Concept` the center of most semantic relationships, while also reifying some concepts into `Decision`, `Constraint`, `Requirement`, and `ActionItem`. This is a reasonable bootstrap pattern, but it creates a structural risk:

- one user-visible idea may exist as both a `Concept` and an artifact node
- semantic edges are all `Concept -> Concept`
- operational recall often wants artifact nodes
- deduplication and retrieval quality can degrade when both layers compete for "truth"

This already shows up in the repo history via duplicate or confusing representations such as the same idea surfacing as both generic concept and specific artifact.

Recommendation:

- define a stricter canonical rule for when something should stay a `Concept` versus when it should be promoted and primarily retrieved as an artifact
- consider whether some semantic relationships should also exist between artifact nodes, or whether artifact recall should consistently hop through `REIFIED_AS`
- document the intended retrieval contract so future work does not create parallel truth layers

### Finding 2. Session may become a dense operational hub

`Session` is accumulating several high-value relationships:

- `WORKING_ON`
- `SENT_IN`
- `LOADED`
- `USED`
- `IN_WORKSPACE`
- `REROUTED_FROM`

This is useful, but it creates supernode risk if session-centric queries become broad or unbounded. The graph-solutions guidance says to watch dense hubs early, and `Session` is one of the most likely candidates in this schema.

Recommendation:

- keep session traversals narrow and task-specific
- avoid using Session as a general-purpose hop for exploratory queries
- archive or prune stale session-adjacent edges aggressively where product behavior allows
- make sure any graph exploration tool caps depth and starts from selective entry points

### Finding 3. Quest identity semantics are slightly muddy

The legacy git-based quest path in [mcp_engine/quest.py](/Users/djshelton/Desktop/GitProjects/sidequests-brain/mcp_engine/quest.py) says the quest is based on repo + branch, but `compute_quest_id()` currently hashes only `repo_root`. At the same time, Hippocampus introduces semantic quest creation and routing. That creates a mixed identity model:

- some quests are legacy deterministic git quests
- some are semantic UUID-backed quests
- branch naming still appears in quest names
- the actual identity rule is no longer obvious from a quick read

That is manageable, but it is an architectural sharp edge.

Recommendation:

- explicitly document the quest identity model in one place
- decide whether branch should remain presentation-only or identity-bearing
- avoid letting old and new quest identity schemes drift into subtly different semantics

### Finding 4. Provenance is good, but still selective

The graph has useful provenance edges like `ESTABLISHED`, `TRIGGERED`, `UPDATES_PATHWAY`, and `DERIVED_FROM`, but the provenance story is stronger for some artifact classes than others. For example, `ESTABLISHED_IN` only covers `Decision` and `Constraint`.

Recommendation:

- decide whether `Requirement` and `ActionItem` should participate in the same provenance patterns
- define which node classes are expected to be explainable back to source turns and which are intentionally lighter-weight

### Finding 5. Stable business identity is still mostly in application logic, not graph constraints

The graph uses UUID-like primary keys for most nodes, which is fine operationally, but semantic identity often depends on `text_raw` plus context. That is why deduplication fixes have lived mostly in loop logic rather than the schema itself.

Recommendation:

- keep semantic deduplication in application logic, but document which fields constitute canonical identity by node type
- consider adding more explicit normalized identity properties where duplicates are costly
- treat label/alias infrastructure as part of identity strategy, not just display metadata

## Recommendations

### Near-term

1. Write down the canonical promotion rules for `Concept` versus artifact nodes.
2. Document the quest identity model and legacy/semantic coexistence.
3. Keep `explore_graph` and any session-centric queries tightly bounded to avoid dense-hub blowups.
4. Extend provenance expectations consistently across artifact classes where product behavior needs explainability.

### Medium-term

1. Decide whether artifact nodes need first-class semantic edges, or whether `Concept` remains the only semantic layer.
2. Add a schema/design note on canonical identity per node type.
3. Review retrieval paths to make sure concept-layer and artifact-layer results do not compete in confusing ways.

## Bottom Line

The current schema is directionally strong and graph-native for the right reasons. The main design risk is not "should this be graph or relational?" The answer there is clearly graph. The real risk is internal graph shape discipline:

- keeping `Concept` from becoming an overloaded catch-all
- keeping `Session` from becoming a dense traversal bottleneck
- keeping quest identity and provenance semantics crisp as the system evolves

Those are healthy, solvable graph-design problems, and they are exactly the right next level of refinement for SideQuests.
