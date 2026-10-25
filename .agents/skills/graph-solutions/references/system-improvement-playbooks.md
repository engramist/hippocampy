# System Improvement Playbooks

Source status:

- Skill distilled: 2026-03-20
- Web sources reviewed: 2026-03-20

Use this file when the user is not merely asking about graph databases, but about how a graph could improve an existing system, workflow, or operational architecture.

## How to spot a graph-enabled system improvement

Graph is often a system-improvement tool when the pain is one of these:

- too many joins or hand-built links across systems
- poor visibility into dependencies, approvals, or lineage
- hard-to-explain access decisions
- duplicate or fragmented identity records
- weak recommendation or routing quality
- metadata silos that make discovery or impact analysis slow

## Playbook 1: Identity Resolution and Master Data

Use graph when the system must connect many identifiers, source records, and matching signals into an explainable identity view.

Starter model:

- `Entity`
- `Identifier`
- `SourceRecord`
- `Assertion`
- `PossibleMatch`
- `ResolvedProfile`

Why graph helps:

- match evidence can stay explicit and inspectable
- cross-source relationships can be traversed instead of manually joined
- resolution decisions are easier to explain and review

Recommend this for customer, product, supplier, account, and language or metadata master-data unification.

## Playbook 2: Authorization and Approval Graphs

Use graph when access or approval depends on relationships such as membership, inheritance, delegation, ownership, role chaining, or policy exceptions.

Starter model:

- `User`
- `Group`
- `Role`
- `Resource`
- `Policy`
- `ApprovalGate`
- relationships like `MEMBER_OF`, `CAN_APPROVE`, `OWNS`, `DEPENDS_ON`, `OVERRIDES`

Why graph helps:

- complex relationship-based access is easier to express and explain
- inherited permissions and chained approvals become traversals
- impact of policy changes becomes visible

For large-scale relationship-based authorization, use Zanzibar-style thinking as a pattern reference, not a mandatory implementation.

## Playbook 3: Content Lineage and Provenance

Use graph when the team needs to trace where content came from, which assets and policies affected it, who approved it, what translations exist, and where it was published.

Starter model:

- `Document`
- `Section`
- `Asset`
- `Revision`
- `Translation`
- `Approval`
- `Publication`
- `System`
- `Policy`

Good relationships:

- `USES_ASSET`
- `DERIVED_FROM`
- `APPROVED_BY`
- `TRANSLATED_TO`
- `PUBLISHED_TO`
- `VALIDATED_AGAINST`
- `SYNCED_FROM`

When provenance rigor matters, use W3C PROV concepts to structure lineage thinking, especially for RDF-oriented graphs.

## Playbook 4: Metadata and Knowledge Graphs

Use graph when the problem is fragmented metadata, weak discoverability, disconnected taxonomies, or hard-to-reuse knowledge across systems.

Starter model:

- `Topic`
- `Person`
- `Organization`
- `Policy`
- `Audience`
- `Language`
- `Asset`
- `Document`

Why graph helps:

- metadata becomes traversable context instead of disconnected tags
- taxonomies, synonyms, and related concepts can coexist
- downstream search, recommendation, and AI grounding improve when context is connected

## Playbook 5: Dependency and Impact Analysis

Use graph when teams need to know what breaks or must be reviewed when a service, policy, schema, asset, or content item changes.

Starter model:

- `Service`
- `Workflow`
- `Document`
- `Schema`
- `Policy`
- `PublishTarget`
- `Asset`

Good relationships:

- `DEPENDS_ON`
- `CALLS`
- `VALIDATES_WITH`
- `PUBLISHES_TO`
- `REQUIRES_POLICY`
- `USES_SCHEMA`

This is often the best way to make hidden operational dependencies visible before a migration or release.

## Playbook 6: Recommendation and Routing

Use graph when relevance depends on connections among users, content, assets, skills, history, or similarity.

Starter model:

- `User`
- `Content`
- `Asset`
- `Topic`
- `Role`
- `Interaction`

Typical outputs:

- recommend assets for a document
- recommend reviewers or approvers
- route work to the best connected expert
- suggest related content or translations

## Workspace-Flavored Examples

Use these examples when the user is working in this ecosystem:

- Nuxeo and DocMCP lineage graph:
  - trace a managed document through versions, sections, assets, and audit artifacts
- Brightspot publishing dependency graph:
  - show which content items, schemas, and approvals feed a publish target
- translation readiness graph:
  - connect source documents, language metadata, translation policies, and downstream publish requirements
- approval and policy graph:
  - model who can review, who can approve, which policy gates apply, and what exceptions exist
- asset reuse graph:
  - connect assets to topics, documents, audiences, and prior usage to improve reuse and reduce duplicate searches

## Use this answer pattern for system-improvement requests

1. name the current system pain
2. say whether graph addresses that pain directly
3. show the smallest useful graph model
4. name the first query or operational question the graph unlocks
5. state the risk if the team uses graph too broadly
6. recommend a pilot using one bounded workflow and a representative dataset

## Source links

- Neo4j use cases: <https://neo4j.com/use-cases/>
- Neo4j fraud detection use case: <https://neo4j.com/use-cases/fraud-detection/>
- Neo4j recommendation tutorial: <https://neo4j.com/docs/getting-started/appendix/tutorials/guide-build-a-recommendation-engine/>
- Neo4j IAM and MDM discussion: <https://neo4j.com/blog/graph-database/neo4j-as-an-embedded-database-the-key-use-cases-of-graph-databases/>
- W3C PROV overview: <https://www.w3.org/TR/prov-overview/>
- Zanzibar paper landing page: <https://www.usenix.org/conference/atc19/presentation/pang>
