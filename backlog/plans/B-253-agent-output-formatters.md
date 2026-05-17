# Plan for 253 - Agent Output Formatters

## Metadata

- **Card ID**: 253
- **Priority**: P2
- **Dependencies**: 252
- **Risk**: Low - additive, no existing behavior changes (generic formatter is the default)

## Goal

Add adapter-specific output formatters so ContextBundles are delivered in the shape each agent type consumes most efficiently.

## Step 1: Define BundleFormatter Protocol

Create `mcp_engine/formatters/base.py`:

```python
from typing import Protocol
from mcp_engine.bundle_compiler import ContextBundle

class BundleFormatter(Protocol):
    """Protocol for formatting ContextBundles for specific agent types."""

    def format(self, bundle: ContextBundle) -> str:
        """Convert a ContextBundle into agent-specific text."""
        ...

    @property
    def name(self) -> str:
        """Formatter identifier (matches agent_type parameter)."""
        ...
```

## Step 2: Implement Formatters

Create `mcp_engine/formatters/__init__.py` with registry:

```python
_FORMATTERS: dict[str, BundleFormatter] = {}

def register(formatter: BundleFormatter):
    _FORMATTERS[formatter.name] = formatter

def get_formatter(agent_type: str) -> BundleFormatter:
    return _FORMATTERS.get(agent_type, _FORMATTERS["generic"])
```

### `mcp_engine/formatters/generic.py`
- Returns `bundle.to_dict()` as JSON (backwards compatible)
- Default fallback for unknown agent types

### `mcp_engine/formatters/claude_code.py`
- Structured markdown with headers per section type
- Decision lists with confidence indicators
- Constraint blocks with severity
- Code-relevant context highlighted
- Example output:
  ```markdown
  ## Exact Facts
  - **Budget limit**: $50,000 (GlobalConstraint, confidence: 0.95)

  ## Relevant Decisions
  - Use Kuzu for graph storage (confidence: 0.92, strength: 0.88)
    - Requires: embedded database, no server
    - Enables: vector search, Cypher queries

  ## Related Data
  | Category | Amount | Approved |
  |----------|--------|----------|
  | Marketing | $12,000 | Yes |
  ```

### `mcp_engine/formatters/claude_desktop.py`
- Conversational prose with inline citations
- Natural language flow, not lists
- Example: "Based on your previous decisions, you chose Kuzu for graph storage (confirmed with high confidence)..."

### `mcp_engine/formatters/codex.py`
- Ultra-compact, code-focused
- File paths and function references when available
- Constraint-first ordering (what NOT to do, then what to do)
- Minimal prose

### `mcp_engine/formatters/chatgpt_desktop.py`
- Natural language summary with bullet points
- Friendly tone, less technical
- Grouped by topic rather than by memory type

### `mcp_engine/formatters/arc.py`
- Structured JSON matching ARC agent expectations
- Mechanic priors, hypothesis state, world model context
- Specific schema for ARC orchestrator consumption

## Step 3: Integrate with Bundle Compiler

In `mcp_engine/bundle_compiler.py`, add formatting step:

```python
from mcp_engine.formatters import get_formatter

async def compile_bundle(..., output_format: str = "generic") -> dict:
    # ... existing assembly pipeline ...
    bundle = ContextBundle(...)

    formatter = get_formatter(output_format)
    formatted_output = formatter.format(bundle)

    return {
        "bundle": bundle.to_dict(),
        "formatted": formatted_output,
        "format": output_format,
    }
```

Update `compile_context` tool schema to accept `output_format` parameter.

## Step 4: Tests

Create `tests/test_formatters.py`:

- Test generic formatter returns valid JSON
- Test claude_code formatter produces markdown with headers
- Test codex formatter is compact (measure token count)
- Test chatgpt_desktop formatter is conversational prose
- Test unknown agent_type falls back to generic
- Test each formatter handles empty bundles gracefully
- Test each formatter handles bundles with only some sections populated
- Test token budget is respected in formatted output

## Completion Criteria

```bash
.venv/bin/pytest -q tests/test_formatters.py tests/test_bundle_compiler.py
.venv/bin/pytest -q
```
