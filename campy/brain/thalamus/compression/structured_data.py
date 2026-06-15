"""
campy/brain/thalamus/compression/structured_data.py

StructuredDataCompressor — converts flat structured data to TOON format.

Use for: "exact_fact" and "tabular" section types (GlobalConstraints,
GlobalPreferences, Dataset rows). These are flat uniform arrays where
TOON's schema-once, data-many approach gives 30-60% token reduction.

Do NOT use for "semantic" or "graph" sections — those carry graph topology
signals (pathway_strength, node type, relationships) that require
GraphBundleCompressor to prune intelligently before serialization.
"""

from __future__ import annotations
import json
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class StructuredDataCompressor(Compressor):
    """Converts list[dict] content to TOON format via j2toon."""

    def __init__(self, config: dict) -> None:
        fmt = config.get("compression", {}).get("structured_format", "toon")
        self._format = fmt

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        try:
            toon_text = self._to_toon(section.content)
            compressed_content = [{"toon": toon_text}]
            token_estimate = len(toon_text) // 4  # ~4 chars per token
            return BS(
                section_type=section.section_type,
                content=compressed_content,
                token_estimate=token_estimate,
                source_node_ids=section.source_node_ids,
            )
        except Exception:
            return section  # fail-safe: return original

    def _to_toon(self, records: list[dict]) -> str:
        if not records:
            return ""
        try:
            from j2toon import json2toon
            return json2toon(records)
        except (ImportError, Exception):
            return self._fallback_toon(records)

    def _fallback_toon(self, records: list[dict]) -> str:
        """Pure-Python TOON fallback if j2toon unavailable."""
        if not records:
            return ""
        keys = list(records[0].keys())
        header = f"{{{','.join(keys)}}}:"
        rows = [",".join(str(r.get(k, "")) for k in keys) for r in records]
        return header + "\n" + "\n".join(rows)
