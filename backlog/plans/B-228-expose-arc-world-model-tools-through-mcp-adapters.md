# Plan for B228 - Expose ARC World-Model Tools Through MCP Adapters

## Card Metadata

- **Card ID**: B228
- **Priority**: P0
- **Dependencies**: B226, B227

## Summary

Ensure the new ARC world-model tools are visible and callable over all relevant MCP adapter paths.

This card exists because ARC observed `Unknown tool: recall_mechanic_priors` during live smoke. Handler implementation alone is not enough; the tool must also be discoverable and routed.

## Technical Approach

### Step 1: Verify canonical schemas

In `mcp_engine/tool_schemas.py`, ensure both schemas exist:

- `publish_mechanic_summary`
- `recall_mechanic_priors`

Schemas must include strict object input definitions and examples in comments/docs where local style supports it.

### Step 2: Verify handler registry

In `mcp_engine/tools/__init__.py`, ensure both handlers are present in the canonical tool-handler map.

Run:

```bash
rg -n "TOOL_HANDLERS|publish_mechanic_summary|recall_mechanic_priors" mcp_engine/tools/__init__.py mcp_engine/tool_schemas.py
```

### Step 3: Verify adapters

Inspect:

- `sidequests/adapters/mcp_server.py`
- `sidequests/adapters/claude_desktop/adapter.py`
- top-level `adapters/`

If an adapter uses `tool_schemas.TOOLS`, no manual update may be needed. If any adapter has explicit pass-through allow-lists, add both tool names there.

### Step 4: Add MCP route tests

Create `tests/test_arc_world_model_tools_mcp.py`.

Tests should cover:

- `tools/list` includes both tools.
- `tools/call` for `recall_mechanic_priors` reaches the handler and returns a normalized result.
- `tools/call` for `publish_mechanic_summary` reaches the handler and returns a normalized result.
- Unknown tools still return the existing unknown-tool behavior.

Use existing fake daemon/MCP test helpers if present.

### Step 5: Update smoke/readiness

Modify `sidequests/cli/smoke_test.py` to optionally check ARC world-model tools without forcing all users to need ARC-specific tools in the default smoke.

Suggested flag:

```bash
sidequests smoke --arc-world-model-tools
```

If the CLI structure does not support flags easily, add a test helper function only and leave CLI behavior unchanged.

### Step 6: Docs

Update `docs/tool-catalog.md` with:

- tool name
- purpose
- input shape
- output shape
- phase guidance: ARC should call publish at safe boundaries and recall outside execute/macro hot paths

## Validation Commands

```bash
pytest -q tests/test_arc_world_model_tools_mcp.py tests/test_adapters.py tests/test_arc_mechanic_memory.py
rg -n "publish_mechanic_summary|recall_mechanic_priors" mcp_engine sidequests adapters tests docs
```

## Risks

- Some adapters may still have historical allow-lists despite B71 centralization. Check explicitly.
- Do not make ARC-specific tools required for every non-ARC installation smoke unless the project wants that stronger contract.
