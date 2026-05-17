# Plan for 251 - Memory Router (Ingestion Classification)

## Metadata

- **Card ID**: 251
- **Priority**: P2
- **Dependencies**: 249, 250
- **Risk**: Low - classification wrapper, no existing behavior changes

## Goal

Build an intelligent ingestion router that classifies incoming data and routes it to the optimal storage strategy. Add a unified `ingest_data` MCP tool.

## Step 1: Create memory_router.py

New module `mcp_engine/memory_router.py`:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class MemoryRoute:
    storage_type: str  # "graph", "tabular", "document", "graph+tabular"
    reason: str
    confidence: float
    suggested_tool: str  # "notify_turn", "ingest_document", "ingest_tabular"

TABULAR_EXTENSIONS = {".csv", ".xlsx", ".tsv", ".xls"}
DOCUMENT_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".toml", ".html", ".rst", ".js", ".ts"}

def classify_input(
    content: Optional[str] = None,
    file_path: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> MemoryRoute:
    """Classify incoming data and recommend storage strategy."""

    # Rule 1: File extension (highest confidence)
    if file_path:
        ext = Path(file_path).suffix.lower()
        if ext in TABULAR_EXTENSIONS:
            return MemoryRoute("tabular", f"File extension {ext} is tabular", 0.95, "ingest_tabular")
        if ext in DOCUMENT_EXTENSIONS:
            return MemoryRoute("document", f"File extension {ext} is document", 0.95, "ingest_document")

    # Rule 2: MIME type
    if mime_type:
        if "spreadsheet" in mime_type or "csv" in mime_type:
            return MemoryRoute("tabular", f"MIME type {mime_type} is tabular", 0.90, "ingest_tabular")

    # Rule 3: Content structure detection (for raw content)
    if content:
        if _looks_tabular(content):
            return MemoryRoute("graph+tabular", "Content has tabular structure", 0.75, "ingest_tabular")
        if len(content) > 2000:
            return MemoryRoute("document", "Long content suitable for document ingestion", 0.70, "ingest_document")

    # Default: conversational text → graph
    return MemoryRoute("graph", "Default: conversational content to graph", 0.60, "notify_turn")

def _looks_tabular(content: str) -> bool:
    """Heuristic: does this content look like tabular data?"""
    lines = content.strip().split("\n")
    if len(lines) < 3:
        return False
    # Check for consistent delimiter (tab or comma) across lines
    for delimiter in ["\t", ","]:
        counts = [line.count(delimiter) for line in lines[:10]]
        if counts[0] > 0 and len(set(counts)) <= 2:  # consistent column count
            return True
    # Check for JSON array
    stripped = content.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    return False
```

## Step 2: Add ingest_data MCP Tool

In `mcp_engine/tool_schemas.py`, add `ingest_data` schema:

```json
{
    "name": "ingest_data",
    "description": "Unified data ingestion. Automatically classifies input and routes to optimal storage (graph, tabular, or document). Use this instead of calling ingest_document or notify_turn directly.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to file to ingest"},
            "content": {"type": "string", "description": "Raw content to ingest (if no file)"},
            "mime_type": {"type": "string", "description": "Optional MIME type hint"},
            "session_id": {"type": "string"}
        }
    }
}
```

In `mcp_engine/tools/__init__.py`, implement handler:
1. Call `classify_input()` with provided parameters
2. Dispatch to appropriate ingestion function based on route
3. Return result including classification metadata

## Step 3: Integrate with Existing Ingestion

Modify `mcp_engine/ingest.py`:
- `ingest_document()` calls `classify_input()` as a pre-check
- If classification says tabular, redirect to `tabular_ingest.ingest_tabular()`
- If classification says document, continue existing path
- Log classification decision to activity feed

## Step 4: Tests

Create `tests/test_memory_router.py`:

- Test file extension routing (CSV → tabular, MD → document)
- Test MIME type routing
- Test content structure detection (tab-delimited → tabular)
- Test JSON array detection
- Test short conversational text → graph
- Test long text → document
- Test `ingest_data` tool end-to-end routing
- Test backwards compat: `ingest_document` still works directly

## Completion Criteria

```bash
.venv/bin/pytest -q tests/test_memory_router.py
.venv/bin/pytest -q
```
