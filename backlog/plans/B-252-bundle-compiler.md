# Plan for 252 - Bundle Compiler (Retrieval Assembly)

## Metadata

- **Card ID**: 252
- **Priority**: P1
- **Dependencies**: 249 (optional, enriches bundles)
- **Risk**: Medium - new retrieval layer, must not break existing `current_truth`

## Goal

Build the retrieval intelligence layer that assembles heterogeneous context from all memory types into a shaped `ContextBundle`, compressed to fit the requesting agent's token budget.

## Step 1: Define ContextBundle Dataclass

In new module `mcp_engine/bundle_compiler.py`:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BundleSection:
    section_type: str  # "exact_fact", "semantic", "graph", "tabular", "summary"
    content: list[dict]
    token_estimate: int
    source_node_ids: list[str] = field(default_factory=list)

@dataclass
class ContextBundle:
    query: str
    sections: list[BundleSection]
    total_token_estimate: int
    token_budget: int
    truncated: bool  # True if budget forced compression
    sources: list[str] = field(default_factory=list)
    compilation_ms: float = 0.0

    def to_dict(self) -> dict:
        """Serialize for MCP response."""
        return {
            "query": self.query,
            "sections": [
                {
                    "type": s.section_type,
                    "content": s.content,
                    "token_estimate": s.token_estimate,
                    "source_node_ids": s.source_node_ids,
                }
                for s in self.sections
            ],
            "total_token_estimate": self.total_token_estimate,
            "token_budget": self.token_budget,
            "truncated": self.truncated,
            "sources": self.sources,
            "compilation_ms": self.compilation_ms,
        }
```

## Step 2: Implement Assembly Pipeline

```python
async def compile_bundle(
    query: str,
    db,
    config: dict,
    token_budget: int = 32000,
    agent_type: Optional[str] = None,
    quest_id: Optional[str] = None,
    session_id: Optional[str] = None,
    include_tabular: bool = True,
    include_summaries: bool = True,
) -> ContextBundle:
```

### Pipeline stages (in priority order):

**Stage 1: Exact facts** (GlobalConstraint + GlobalPreference)
- Cypher query for GlobalConstraint/GlobalPreference nodes matching query embedding
- Similarity threshold: 0.70 (lower than current_truth's default because exact facts are high-value)
- These are cheap (short text, high confidence) — always included first

**Stage 2: Semantic context** (current_truth results)
- Call existing `current_truth` logic internally (not via MCP, direct function call)
- Top-k results ranked by `pathway_strength * confidence * (1 + outcome_boost)`
- Respect warm frontier and working memory deduplication

**Stage 3: Graph structure** (relationship traversals)
- For top semantic results, do 1-2 hop traversal via `explore_graph` logic
- Extract relationship types and connected entities
- Format as structured connections: "Decision X → REQUIRES → Concept Y"

**Stage 4: Tabular data** (if 249 complete and include_tabular=True)
- Check if any semantic results link to Dataset nodes via `DESCRIBED_BY_DATASET`
- If yes, call `tabular_store.get_table_summary()` for relevant datasets
- For high-relevance datasets, include filtered rows if within token budget

**Stage 5: Summaries** (wiki projection, if available)
- Check if wiki projection has pages for relevant entities
- If yes, include the rendered summary text
- Fallback: LLM-generated summary of the top results

### Token budget management:

```python
BUDGET_TIERS = {
    "small": {"max_semantic": 3, "max_graph_hops": 1, "include_tabular_summary": True, "include_raw_tabular": False},
    "medium": {"max_semantic": 10, "max_graph_hops": 2, "include_tabular_summary": True, "include_raw_tabular": True, "max_tabular_rows": 20},
    "large": {"max_semantic": 25, "max_graph_hops": 2, "include_tabular_summary": True, "include_raw_tabular": True, "max_tabular_rows": 100},
}

def _get_tier(token_budget: int) -> str:
    if token_budget <= 8000:
        return "small"
    elif token_budget <= 128000:
        return "medium"
    return "large"
```

After each stage, check cumulative token estimate. If over budget, truncate remaining stages. Mark `truncated=True` on the bundle.

## Step 3: Add compile_context MCP Tool

In `mcp_engine/tool_schemas.py`:

```json
{
    "name": "compile_context",
    "description": "Compile a context bundle from all memory types (graph, exact facts, tabular data, summaries). Returns shaped context optimized for the requesting agent's token budget. Use this for complex queries that need assembled context; use current_truth for simple fact lookups.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What context is needed"},
            "token_budget": {"type": "integer", "description": "Max tokens for the bundle (default: 32000)"},
            "agent_type": {"type": "string", "description": "Requesting agent type for output formatting"},
            "include_tabular": {"type": "boolean", "default": true},
            "include_summaries": {"type": "boolean", "default": true},
            "session_id": {"type": "string"}
        },
        "required": ["query"]
    }
}
```

## Step 4: Integration Points

- `compile_bundle()` reuses existing retrieval internals, not MCP tool calls
- Import and call `_vector_search()`, `_exact_match_search()` etc. from tools/__init__.py
- If these are currently tightly coupled to the MCP handler, extract shared helpers first
- `current_truth` remains completely unchanged — no modifications to existing tool

## Step 5: Tests

Create `tests/test_bundle_compiler.py`:

- Test empty graph returns empty bundle
- Test exact facts included when relevant GlobalConstraints exist
- Test semantic results included and ranked correctly
- Test graph structure traversal adds relationships
- Test tabular data included when Dataset nodes linked (mock or real 249)
- Test token budget small tier compresses output
- Test token budget large tier includes full detail
- Test truncation flag set when budget exceeded
- Test provenance sources populated
- Test `compile_context` MCP tool end-to-end
- Test `current_truth` still works unchanged (regression)

## Completion Criteria

```bash
.venv/bin/pytest -q tests/test_bundle_compiler.py
.venv/bin/pytest -q
```
