"""
mcp_engine/memory_router.py — Intelligent Data Classification & Routing

Routes incoming data to optimal storage strategy based on type and content.
Determines whether to store as graph (conversational), tabular (data), or hybrid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MemoryRoute:
    """Route recommendation for incoming data."""
    storage_type: str  # "graph", "tabular", "document", "graph+tabular"
    reason: str
    confidence: float
    suggested_tool: str  # "notify_turn", "ingest_document", "ingest_tabular", "ingest_data"


TABULAR_EXTENSIONS = {".csv", ".xlsx", ".tsv", ".xls"}
DOCUMENT_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".toml", ".html", ".rst", ".js", ".ts", ".css"}


def classify_input(
    content: Optional[str] = None,
    file_path: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> MemoryRoute:
    """
    Classify incoming data and recommend storage strategy.
    
    Rules applied in order of priority:
    1. File extension (highest confidence if present)
    2. MIME type (high confidence)
    3. Content structure detection (medium confidence)
    4. Default (conversational text → graph)
    
    Returns:
        MemoryRoute with storage_type and suggested_tool
    """

    # Rule 1: File extension (highest confidence)
    if file_path:
        ext = Path(file_path).suffix.lower()
        if ext in TABULAR_EXTENSIONS:
            return MemoryRoute(
                storage_type="tabular",
                reason=f"File extension {ext} is tabular data",
                confidence=0.95,
                suggested_tool="ingest_tabular"
            )
        if ext in DOCUMENT_EXTENSIONS:
            return MemoryRoute(
                storage_type="document",
                reason=f"File extension {ext} is document",
                confidence=0.95,
                suggested_tool="ingest_document"
            )

    # Rule 2: MIME type
    if mime_type:
        if "spreadsheet" in mime_type or "csv" in mime_type or "excel" in mime_type:
            return MemoryRoute(
                storage_type="tabular",
                reason=f"MIME type {mime_type} is tabular",
                confidence=0.90,
                suggested_tool="ingest_tabular"
            )
        if "document" in mime_type or "text" in mime_type:
            return MemoryRoute(
                storage_type="document",
                reason=f"MIME type {mime_type} is document",
                confidence=0.85,
                suggested_tool="ingest_document"
            )

    # Rule 3: Content structure detection (for raw content)
    if content:
        if _looks_tabular(content):
            return MemoryRoute(
                storage_type="graph+tabular",
                reason="Content has tabular structure",
                confidence=0.75,
                suggested_tool="ingest_tabular"
            )
        if len(content) > 2000:
            return MemoryRoute(
                storage_type="document",
                reason="Long content (>2000 chars) suitable for document ingestion",
                confidence=0.70,
                suggested_tool="ingest_document"
            )

    # Default: conversational text → graph
    return MemoryRoute(
        storage_type="graph",
        reason="Default: conversational content to graph memory",
        confidence=0.60,
        suggested_tool="notify_turn"
    )


def _looks_tabular(content: str) -> bool:
    """
    Heuristic: does this content look like tabular data?
    
    Checks for:
    - Consistent delimiter (tab or comma) across multiple lines
    - JSON array structure
    """
    stripped = content.strip()
    
    # Check for JSON array of objects first (can be single line)
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            import json
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, ValueError):
            pass

    lines = stripped.split("\n")
    
    # Need at least 3 lines for delimiter-based detection
    if len(lines) < 3:
        return False

    # Check for consistent delimiter (tab or comma) across lines
    for delimiter in ["\t", ","]:
        counts = [line.count(delimiter) for line in lines[:10] if line.strip()]
        if not counts:
            continue
        # If all lines have the same column count, likely tabular
        if counts[0] > 0 and len(set(counts)) <= 2:  # Allow small variance
            return True

    return False
