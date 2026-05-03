# Plan for B221 - Graph-Native Wiki Projection Architecture

## Card Metadata

- **Card ID**: B221
- **Priority**: P0
- **Dependencies**: B191

## Summary

Document the architecture for a read-only Markdown wiki projection generated from graph memory during Dreaming. The projection gives humans a tactile browsing surface while keeping KuzuDB as the only authoritative state.

Graph-solutions classification: decision + model selection + implementation. Graph is the right fit because the user journey is relationship-heavy browsing: multi-hop related pages, provenance, backlinks, persona-scoped neighborhoods, and source-node explanation. The recommended model remains labeled property graph in KuzuDB because SideQuests already stores relationship-scoped confidence, pathway strength, timestamps, and source IDs as edge/node properties.

## Technical Approach

### Step 1: Create architecture doc

Create `docs/wiki-projection-architecture.md` with these sections:

- goal and non-goals
- easy wiki user journeys
- graph-native source of truth
- Obsidian as the default UI target
- read-only Markdown projection contract
- Dreaming/sweep as projection writer
- persona isolation
- graph projection model
- page taxonomy
- drift prevention
- token budget strategy
- traversal and performance guardrails
- failure modes
- relation to Obsidian/Karpathy Wiki/Memory Palace style competitors

The document must answer this directly:

- Default UI: Obsidian vault generated at `wiki/`.
- Fallback UI: any Markdown editor or file browser.
- SideQuests-owned UI: optional later web view, not required for the first useful wiki.

Hot user journeys:

- `sidequests wiki open` opens the generated Obsidian vault when Obsidian is installed.
- `sidequests wiki path` prints the vault path when Obsidian is not installed.
- User lands on `Home.md`, then browses persona indexes, topic pages, source-backed pages, backlinks, and related pages.
- User can inspect the Kuzu source IDs and generated timestamp from page front matter.
- User can switch persona by opening `personas/<persona>/Home.md`.

### Step 2: Define projection contract

Every generated Markdown page should include front matter:

```yaml
sidequests_projection: true
projection_version: 1
persona: "default"
generated_at: "..."
source_node_ids: [...]
source_edge_ids: [...]
source_query_hash: "..."
manual_edits_supported: false
open_in_obsidian_supported: true
```

The document must state that generated pages are cache artifacts. Manual edits may be allowed in a separate notes area later, but they must be ingested through normal `notify_turn` or document ingestion paths and reconciled into KuzuDB before appearing in generated projection pages.

### Step 3: Define persona isolation

Proposed output layout:

```text
wiki/
  personas/
    default/
    engineer/
    researcher/
    product/
```

Each persona defines:

- scope filters
- preferred page templates
- redaction rules
- sort/ranking rules
- page budget limits

### Step 4: Define graph projection model

Prefer no new durable source-of-truth nodes unless implementation needs projection history. The architecture should start with generated Markdown as a cache over existing nodes, but it must define these conceptual entities:

- `PersonaProjection`: config/runtime object for one projection lens
- `WikiPage`: generated file backed by one or more graph nodes
- `WikiSection`: bounded rendered section inside a page
- `GENERATED_FROM`: page provenance to source nodes
- `MENTIONS`: page links to concepts/entities
- `RELATED_PAGE`: bounded related-page link generated from graph neighborhoods

If implementation persists projection metadata, it must use stable page IDs and source graph IDs, not filesystem paths as identity.

### Step 5: Define traversal guardrails

Document graph query rules:

- index entry points by stable IDs, node type, domain, persona, and pathway strength where available
- bound related-page traversal depth to 1-2 hops for generated pages
- filter early by persona/domain/node type and expand late
- cap backlinks and related pages per page to avoid dense-node fan-out
- never generate global "everything related to everything" pages

### Step 6: Update main architecture doc

Add a concise section to `docs/ARCHITECTURE.md` pointing to the new wiki architecture doc and stating the core invariant: graph first, Markdown projection second.

## Acceptance Criteria

- Architecture doc exists and is internally consistent with `docs/ARCHITECTURE.md`.
- It clearly forbids Markdown projection drift.
- It states Obsidian is the default UI target and Markdown portability is the fallback.
- It defines the first 3-5 user journeys and the graph projection model.
- Persona isolation is concrete enough for implementation cards B222 and B223.

## Validation Commands

```bash
rg -n "wiki|projection|persona|Dreaming|KuzuDB|single source" docs/wiki-projection-architecture.md docs/ARCHITECTURE.md
pytest -q tests/test_b191_dreaming.py tests/test_sweep.py
```

## Risks

- If generated Markdown looks editable, users may treat it as source-of-truth. The design must make read-only status obvious.
- Persona filters can become security theater unless their limits are documented honestly.
- Obsidian graph view can become noisy if every page links to too many pages. Bound links and related-page fan-out from the start.
