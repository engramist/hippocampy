# B-288 — Reconcile Adapter Tool Surfaces

Card: backlog/B288.md
Priority: P2
Dependencies: none

## Summary

Two canonical tools (`compile_context` from B252, `ingest_data` from B250) never got propagated to the OpenClaw extension, and the Codex adapter test uses a hardcoded tool list that went stale. Add the two OpenClaw definitions and make the Codex test registry-derived. Pure surface reconciliation — no handler or schema logic changes.

## Background facts (verified)

- The Codex adapter (`adapters/codex/adapter.py:32`) does `from campy.brain.thalamus.tool_schemas import TOOLS` — it already exposes all 51 canonical tools. **Do not touch the adapter.** Only its test is stale.
- `TOOL_HANDLERS` (in `campy/brain/thalamus/tools/__init__.py`) has 51 entries including the 15 ARC tools, `compile_context`, and `ingest_data`.
- `extensions/hippocampy/src/index.ts` already has the 15 ARC tools (added by B278) but is missing `compile_context` and `ingest_data`.
- Canonical input schemas (from `tool_schemas.TOOLS`):
  - `compile_context`: required `["query", "session_id"]`; properties `query, token_budget (int, default 32000), agent_type (str), include_tabular (bool, default true), include_summaries (bool, default true), session_id, quest_id`
  - `ingest_data`: required `["session_id"]`; properties `file_path, content, mime_type, session_id, quest_id`

## Step 1: Add the two OpenClaw param schemas

In `extensions/hippocampy/src/index.ts`, near the other `Type.Object` param definitions (the block spanning ~line 271–530, e.g. right after `ingestArcArtifactsParams` at ~line 368), add:

```typescript
    const compileContextParams = Type.Object({
      query: Type.String({ description: "What context is needed" }),
      session_id: Type.String({ description: "Session identifier" }),
      token_budget: Type.Optional(
        Type.Number({ description: "Max tokens for the bundle", default: 32000 })
      ),
      agent_type: Type.Optional(
        Type.String({ description: "Requesting agent type for output formatting" })
      ),
      include_tabular: Type.Optional(
        Type.Boolean({ description: "Include tabular data", default: true })
      ),
      include_summaries: Type.Optional(
        Type.Boolean({ description: "Include summaries", default: true })
      ),
      quest_id: Type.Optional(
        Type.String({ description: "Optional quest_id scope" })
      ),
    });

    const ingestDataParams = Type.Object({
      session_id: Type.String({ description: "Session identifier" }),
      file_path: Type.Optional(
        Type.String({ description: "Path to file to ingest (if not providing content)" })
      ),
      content: Type.Optional(
        Type.String({ description: "Raw content to ingest (if not providing a file)" })
      ),
      mime_type: Type.Optional(
        Type.String({ description: "Optional MIME type hint" })
      ),
      quest_id: Type.Optional(
        Type.String({ description: "Optional quest_id to tag the artifact" })
      ),
    });
```

Match the surrounding style exactly (the repo uses `Type.Optional(Type.X({...}))` for optional fields; required fields are bare `Type.X`).

## Step 2: Add the two entries to `toolDefinitions`

In the `toolDefinitions` array (entries look like the `ingest_document` block at ~line 1094–1104), add two primary tool entries. Place them near the other ingestion/context tools:

```typescript
      {
        name: "compile_context",
        label: "Compile Context (HippoCampy)",
        description:
          "Compile a context bundle from all memory types (graph, exact facts, tabular data, summaries). Returns shaped context optimized for the requesting agent's token budget. Use for complex queries needing assembled context; use current_truth for simple fact lookups.",
        parameters: compileContextParams,
        transformParams: (params: any = {}) => ({
          query: params.query,
          session_id: params.session_id,
          token_budget: params.token_budget ?? 32000,
          agent_type: params.agent_type,
          include_tabular: params.include_tabular ?? true,
          include_summaries: params.include_summaries ?? true,
          quest_id: params.quest_id,
        }),
      },
      {
        name: "ingest_data",
        label: "Ingest Data (HippoCampy)",
        description:
          "Unified data ingestion. Automatically classifies input and routes to optimal storage (graph, tabular, or document). Use instead of calling ingest_document or notify_turn directly.",
        parameters: ingestDataParams,
        transformParams: (params: any = {}) => ({
          session_id: params.session_id,
          file_path: params.file_path,
          content: params.content,
          mime_type: params.mime_type,
          quest_id: params.quest_id,
        }),
      },
```

Note: these are **primary** tools (the tool `name` equals the Brain `callName`), not aliases — so do NOT add a `callName` field. The alias entries (the `callName: "current_truth"` ones at ~line 883+) are a different shape; don't copy those.

Verify against the test's regex extractors in `tests/test_openclaw_tool_surfacing.py`:
- `_extract_registered_tool_names` matches `name:\s*"([^"]+)"` — satisfied by the `name:` field.
- `test_openclaw_extension_has_proper_descriptions` requires `description:` after the name — satisfied.
- `test_openclaw_extension_has_proper_parameters` requires `parameters:\s*\w+Params` — satisfied by `parameters: compileContextParams` / `ingestDataParams`.
- `tests/test_openclaw_tool_aliases.py::_extract_tool_definitions` parses `{ name: "...", ... callName: "..." }` into `{name: callName}`. For a primary tool with no explicit `callName`, check how existing primary tools (e.g. `notify_turn`, `current_truth` primary) expose `callName` — **read an existing primary entry in `toolDefinitions` and match its shape.** If primaries carry an explicit `callName: "<same name>"`, add that to the two new entries too so `_extract_tool_definitions` records them. (This is the critical detail — the aliases test reads `tool["callName"]`, so the new entries must expose a `callName` the regex can capture, even if it equals the name.)

**Action:** before writing, grep a known-passing primary tool to confirm the exact field set:
```bash
grep -n -A8 'name: "explore_graph"' extensions/hippocampy/src/index.ts
```
Mirror that structure precisely (including whether `callName` is present on primaries).

## Step 3: Make the Codex adapter test registry-derived

In `tests/test_analogical.py`, replace `test_codex_adapter_has_all_tools`:

```python
def test_codex_adapter_has_all_tools():
    """The Codex adapter must expose exactly the canonical tool set.

    Derived from tool_schemas.TOOLS (not a hardcoded list) so adding a tool
    can't silently desync this assertion — that staleness is exactly what
    broke when B250/B252/B278 landed.
    """
    from adapters.codex.adapter import TOOLS as ADAPTER_TOOLS
    from campy.brain.thalamus.tool_schemas import TOOLS as CANONICAL_TOOLS

    adapter_names = {t["name"] for t in ADAPTER_TOOLS}
    canonical_names = {t["name"] for t in CANONICAL_TOOLS}
    assert adapter_names == canonical_names, (
        f"Codex adapter desynced from canonical registry. "
        f"Missing: {sorted(canonical_names - adapter_names)}; "
        f"Extra: {sorted(adapter_names - canonical_names)}"
    )
    # Sanity floor so an empty registry can't vacuously pass.
    assert len(adapter_names) >= 49
```

Leave the other tests in the file (`test_codex_adapter_analogical_search_schema`, `test_codex_adapter_git_context_functions_exist`) unchanged.

## Step 4: Update docs/tool-catalog.md

Open `docs/tool-catalog.md`. If it enumerates tools, add rows for any canonical tool not present — at minimum `compile_context`, `ingest_data`, and the 15 `arc_*` tools (if B278 didn't already add them). Cross-check with:
```bash
python3 -c "
from campy.brain.thalamus.tool_schemas import TOOLS
from pathlib import Path
cat = Path('docs/tool-catalog.md').read_text()
for t in sorted(t['name'] for t in TOOLS):
    if t not in cat:
        print('MISSING FROM CATALOG:', t)
"
```
Add any printed names with a one-line description drawn from the tool's schema `description`.

## Validation

```bash
pytest tests/test_openclaw_tool_surfacing.py tests/test_openclaw_tool_aliases.py tests/test_analogical.py -q
# parity check
python3 -c "
import re
from pathlib import Path
from campy.brain.thalamus.tools import TOOL_HANDLERS
src = Path('extensions/hippocampy/src/index.ts').read_text()
names = set(re.findall(r'name:\s*\"([^\"]+)\"', src))
missing = set(TOOL_HANDLERS) - names
assert not missing, f'still missing: {sorted(missing)}'
print('PARITY OK', len(TOOL_HANDLERS), 'handlers all surfaced')
"
```

## Risks / notes

- **TypeScript is not compiled in CI here** — the tests parse `index.ts` as text via regex, so a syntax error won't be caught by pytest. After editing, optionally run `cd extensions/hippocampy && npx tsc --noEmit` if a toolchain is available; otherwise eyeball brace/comma balance against the neighboring entries.
- The single most likely failure mode is the `callName` detail in Step 2 — if `_extract_tool_definitions` returns the new tools but the aliases test still reports them missing, it's because the regex needs a `callName` field. Resolve by matching an existing primary's exact shape.
- Do not modify `adapters/codex/adapter.py` — it is already correct (dynamic registry import).
- Do not add aliases for these two tools unless `EXPECTED_ALIASES` in the aliases test expects them (it does not) — primaries are sufficient.
