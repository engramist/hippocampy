# Plan for B223 - Persona-Isolated Wiki Projections

## Card Metadata

- **Card ID**: B223
- **Priority**: P1
- **Dependencies**: B221, B222

## Summary

Add persona-specific wiki projections. Each persona is a read-only lens over KuzuDB with separate output directory, filters, templates, and budgets.

Each persona should feel like a usable wiki section in Obsidian, not a raw export folder.

## Technical Approach

### Step 1: Define persona config

Support config like:

```toml
[[wiki_projection.personas]]
name = "engineer"
output_dir = "wiki/personas/engineer"
include_domains = ["architecture", "implementation", "testing"]
include_node_types = ["Decision", "Constraint", "Procedure", "Lesson"]
max_pages_per_sweep = 50
max_chars_per_page = 8000
max_related_pages = 12
home_title = "Engineering Memory"

[[wiki_projection.personas]]
name = "researcher"
output_dir = "wiki/personas/researcher"
include_domains = ["research", "evaluation", "benchmarks"]
include_node_types = ["Lesson", "KnowledgeGap", "Procedure"]
max_pages_per_sweep = 40
max_chars_per_page = 7000
max_related_pages = 10
home_title = "Research Memory"
```

### Step 2: Extend exporter

Refactor exporter so default export is equivalent to one implicit persona:

```python
personas = _load_personas(config)
for persona in personas:
    pages = _select_pages_for_persona(db, persona)
    pages = _rank_pages_for_persona(pages, persona)
    write_pages(persona, pages)
```

Selection must filter first and expand later:

- apply persona include/exclude domains and node types first
- start from high-strength/synthesis/procedure/gap entry points
- expand related nodes only after the entry page set is chosen
- cap related pages per persona page

### Step 3: Prevent cross-persona leakage

Rules:

- generated links are relative within the persona tree
- front matter identifies persona
- no persona writes outside its configured output root
- source graph IDs can overlap because the graph is shared
- generated Markdown files are never re-ingested as persona-specific memory
- cross-persona links are omitted by default unless marked as `shared: true`

### Step 4: Add persona CLI support

Extend B222 CLI commands:

- `sidequests wiki path --persona engineer`
- `sidequests wiki open --persona engineer`
- `sidequests wiki status --persona engineer`

If deep-linking to a specific file in Obsidian is not reliable on a platform, print the persona home path.

### Step 5: Tests

Create `tests/test_wiki_projection_personas.py`:

- two personas write to separate directories
- filters produce different page sets
- persona home and index pages are generated
- front matter persona is correct
- default persona works with no explicit persona blocks
- path traversal in persona names/output dirs is rejected or normalized
- related-page caps are enforced after filtering
- mocked `sidequests wiki open --persona` resolves the persona home path

## Validation Commands

```bash
pytest -q tests/test_wiki_projection.py tests/test_wiki_projection_personas.py tests/test_sweep.py
rg -n "wiki_projection.personas|persona|wiki open" mcp_engine sidequests tests docs sidequests.toml
```

## Risks

- Personas can look like permissions. Document them as browsing lenses unless a later security card adds access control.
- Too many persona pages can cause file churn. Enforce per-persona budgets.
- Filtering after traversal can create accidental fan-out. Apply persona filters before expansion.
