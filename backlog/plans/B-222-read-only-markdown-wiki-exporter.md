# Plan for B222 - Read-Only Markdown Wiki Exporter from Dreaming

## Card Metadata

- **Card ID**: B222
- **Priority**: P1
- **Dependencies**: B191, B221

## Summary

Implement the default-persona Markdown wiki projection writer. The exporter runs from sweep after Dreaming and writes deterministic read-only pages backed by KuzuDB source node IDs.

The result must be easy to use, not just technically correct: the generated folder is an Obsidian-compatible vault with a home page, index pages, wiki links, and CLI commands for opening or locating it.

## Technical Approach

### Step 1: Add wiki projection module

Create `mcp_engine/wiki_projection.py` with:

- `export_wiki_projection(db, config) -> dict`
- `_select_default_pages(db, limit) -> list[WikiPage]`
- `_render_page(page) -> str`
- `_write_atomic(path, content) -> None`
- `_slugify(title) -> str`
- `_render_home_page(pages, summary) -> str`
- `_render_index_pages(pages) -> dict[str, str]`

Use a small dataclass for page data:

```python
@dataclass
class WikiPage:
    title: str
    persona: str
    source_node_ids: list[str]
    source_edge_ids: list[str]
    body_sections: list[tuple[str, str]]
    backlinks: list[str]
    related_pages: list[str]
```

### Step 2: Select graph-backed pages

For the first implementation, export:

- synthesis Lessons from B191
- Procedures from B194 if present
- active KnowledgeGaps from B193 if present
- high-strength Decisions/Constraints if present

Keep queries defensive. Missing node/relationship types should not crash the sweep.

Use graph-solutions traversal rules:

- start from selective entry points: synthesis lessons, procedures, knowledge gaps, high-strength decisions
- filter by node type/domain/pathway strength before expanding related nodes
- keep relationship expansion to 1 hop for default pages
- cap `related_pages` and backlinks per page
- use stable source IDs in front matter so page identity does not depend only on title text

### Step 3: Render read-only Markdown

Each page starts with front matter:

```yaml
sidequests_projection: true
projection_version: 1
persona: default
generated_at: "..."
source_node_ids: [...]
source_edge_ids: [...]
manual_edits_supported: false
```

Then render compact sections:

- summary
- source graph IDs
- related nodes
- generated backlinks

Also create Obsidian-friendly navigation pages:

```text
wiki/
  Home.md
  Index.md
  Topics.md
  Sources.md
  personas/
    default/
      Home.md
      Index.md
      pages/
```

Use `[[Page Title]]` links for generated pages. Include short "source IDs" sections so users can inspect provenance without calling a tool.

### Step 4: Wire into sweep

In `mcp_engine/sweep.py`, call exporter after Dreaming/procedural/gap/consistency work and before returning the sweep summary.

Skip cleanly when disabled:

```toml
[wiki_projection]
enabled = false
vault_dir = "wiki"
output_dir = "wiki/personas/default"
max_pages_per_sweep = 50
max_chars_per_page = 8000
max_related_pages = 12
max_backlinks = 25
obsidian_vault_name = "SideQuests Brain"
```

### Step 5: Add CLI commands

Add a `wiki` Typer group in `sidequests/cli/main.py` backed by `sidequests/cli/wiki.py`:

- `sidequests wiki path`
- `sidequests wiki status`
- `sidequests wiki open`

`open` behavior:

- macOS: prefer `open "obsidian://open?vault=<vault-name>"`
- if Obsidian URL open fails, open the vault folder
- on unsupported systems, print the vault path and next command to run manually

Do not require Obsidian for tests or for using the generated Markdown.

### Step 6: Tests

Create `tests/test_wiki_projection.py` covering:

- disabled config skips export
- generated front matter includes source IDs
- deterministic slug/path output
- generated `Home.md`, `Index.md`, `Topics.md`, and `Sources.md`
- Obsidian wiki links are generated for related pages
- page size cap is enforced
- related-page and backlink caps are enforced
- atomic write behavior
- exporter does not ingest/read generated Markdown

Create `tests/test_cli_wiki.py` covering:

- `sidequests wiki path` resolves configured/default vault path
- `sidequests wiki status` handles missing vault and existing vault
- `sidequests wiki open` uses mocked platform/open calls and falls back cleanly

## Validation Commands

```bash
pytest -q tests/test_wiki_projection.py tests/test_cli_wiki.py tests/test_b191_dreaming.py tests/test_sweep.py
rg -n "wiki_projection|export_wiki_projection|manual_edits_supported|wiki open|wiki path" mcp_engine sidequests tests docs sidequests.toml
```

## Risks

- Kuzu schema differences between installs may make broad export queries brittle. Defensive query wrappers are required.
- Generated wiki pages can become noisy unless page count and page size are bounded from day one.
- Opening Obsidian is platform-specific. The CLI must degrade gracefully to printing/opening the folder.
