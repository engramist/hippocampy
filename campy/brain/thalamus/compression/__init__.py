"""
campy/brain/thalamus/compression/__init__.py

Pluggable compression infrastructure for Campy's thalamic emit path.

WHY GRAPH-NATIVE MATTERS:
Campy bundles are subgraphs, not JSON arrays. GraphBundleCompressor prunes
semantically irrelevant nodes using graph signals (pathway_strength × query
similarity). TOON/ONTO handles flat structured data. LLMCompressor handles
prose. ASTCodeCompressor handles code. ContentRouter dispatches by section_type.
Do NOT replace GraphBundleCompressor with a generic JSON compressor — they
solve different problems (semantic pruning vs syntax elimination).
"""

from __future__ import annotations
import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class Compressor(abc.ABC):
    """Abstract base for all compression strategies."""

    @abc.abstractmethod
    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        """
        Compress a bundle section. Always returns a BundleSection (never None).
        The returned section may have the same content (NoOp) or a reduced version.
        """


class PluggableCompressorRegistry:
    """Holds registered compressors and returns them by name."""

    def __init__(self) -> None:
        self._compressors: dict[str, Compressor] = {}

    def register(self, name: str, compressor: Compressor) -> None:
        self._compressors[name] = compressor

    def get(self, name: str) -> Compressor:
        """Return named compressor, or NoOpCompressor if not found."""
        from campy.brain.thalamus.compression.fallback import NoOpCompressor
        return self._compressors.get(name, NoOpCompressor())


class ContentRouter:
    """
    Routes BundleSections to the correct compressor by section_type.

    section_type → compressor name:
      "graph"      → "graph_bundle"   (graph-native pruning — do not substitute)
      "semantic"   → "graph_bundle"   (semantic nodes carry graph signals)
      "tabular"    → "structured_data"
      "exact_fact" → "structured_data"
      "summary"    → "llm_prose"      (only fires when prose is present)
      "code"       → "ast_code"       (Phase B: fires when code extracts present)
    """

    _ROUTE: dict[str, str] = {
        "graph":      "graph_bundle",
        "semantic":   "graph_bundle",
        "tabular":    "structured_data",
        "exact_fact": "structured_data",
        "summary":    "llm_prose",
        "code":       "ast_code",
    }

    def __init__(self, registry: PluggableCompressorRegistry) -> None:
        self._registry = registry

    def compress_section(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        name = self._ROUTE.get(section.section_type, "noop")
        compressor = self._registry.get(name)
        return compressor.compress(section, query, config)


def build_default_registry(config: dict) -> tuple[PluggableCompressorRegistry, ContentRouter]:
    """
    Construct the default registry with all four compressors registered.
    Returns (registry, router).
    """
    from campy.brain.thalamus.compression.fallback import NoOpCompressor
    from campy.brain.thalamus.compression.structured_data import StructuredDataCompressor
    from campy.brain.thalamus.compression.llm_prose import LLMCompressor
    from campy.brain.thalamus.compression.graph_bundle import GraphBundleCompressor

    registry = PluggableCompressorRegistry()
    registry.register("noop", NoOpCompressor())
    registry.register("structured_data", StructuredDataCompressor(config))
    registry.register("llm_prose", LLMCompressor(config))
    registry.register("graph_bundle", GraphBundleCompressor(config))

    ast_enabled = config.get("compression", {}).get("ast_compression", True)
    if ast_enabled:
        try:
            from campy.brain.thalamus.compression.ast_mapper import ASTCodeCompressor
            registry.register("ast_code", ASTCodeCompressor())
        except ImportError:
            registry.register("ast_code", NoOpCompressor())
    else:
        registry.register("ast_code", NoOpCompressor())

    router = ContentRouter(registry)
    return registry, router
