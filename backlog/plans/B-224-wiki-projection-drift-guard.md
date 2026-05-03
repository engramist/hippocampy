# Plan for B224 - Wiki Projection Drift Guard and Obsidian Hygiene

## Card Metadata

- **Card ID**: B224
- **Priority**: P2
- **Dependencies**: B222

## Summary

Add drift detection and Obsidian hygiene rules for generated Markdown wiki projections.

This keeps the wiki easy to browse while preventing Obsidian/local edits from becoming a hidden second database.

## Technical Approach

### Step 1: Add projection hash

The exporter should compute a stable hash over the rendered graph-backed content before writing:

```yaml
projection_hash: "sha256:..."
```

The hash should exclude volatile fields like `generated_at`.

### Step 2: Detect manual edits

Before overwriting an existing generated page:

1. Parse front matter.
2. Confirm `sidequests_projection: true`.
3. Recompute hash from existing body.
4. If it differs from front matter, treat it as drift.

Drift handling:

- write current edited file to `<slug>.conflict.md` or `wiki/conflicts/...`
- regenerate canonical page from graph
- record drift in exporter summary

### Step 3: Separate manual notes

Document and optionally create:

```text
wiki/
  Home.md
  manual-notes/
  personas/
  conflicts/
```

Manual notes are for human writing. They are not authoritative until explicitly ingested and consolidated into KuzuDB.

### Step 4: Add Obsidian hygiene

Generated pages should include a compact read-only notice after front matter:

```markdown
> Generated from SideQuests graph memory. Edit `manual-notes/` for human notes; generated pages are overwritten by Dreaming.
```

Optional Obsidian settings may be generated only when config enables it. Keep them minimal and plugin-free:

```toml
[wiki_projection.obsidian]
write_recommended_settings = false
```

Ignore common workspace/cache files and avoid depending on community plugins.

### Step 5: Git hygiene

Add generated wiki output to `.gitignore` by default:

```gitignore
wiki/personas/
wiki/conflicts/
wiki/.obsidian/workspace*
wiki/.obsidian/cache/
```

Do not ignore `docs/wiki-projection-architecture.md` or backlog cards.

### Step 6: Tests

Create `tests/test_wiki_projection_drift.py`:

- unchanged generated file overwrites cleanly
- manually edited generated file creates conflict copy
- generated page is restored from graph content
- manual notes directory is not scanned or overwritten
- projection hash ignores `generated_at`
- generated pages include the read-only notice
- Obsidian workspace/cache ignore patterns exist

## Validation Commands

```bash
pytest -q tests/test_wiki_projection.py tests/test_wiki_projection_drift.py tests/test_sweep.py
rg -n "projection_hash|manual-notes|drift|conflict|.obsidian" mcp_engine tests docs .gitignore
```

## Risks

- Conflict copies can accumulate. A future cleanup card may add retention limits.
- Hash parsing must be robust enough not to crash the sweep on malformed manual edits.
- Obsidian settings can become user-specific quickly. Generate only minimal recommended settings and ignore workspace state.
