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
    Routes BundleSections to the correct compressor by section_type using
    Two-Lane Thalamic Routing (B374).

    Two lanes:
      - Protected Lane (zero loss): Decisions, active Constraints, Negative Controls,
        and exact facts bypass compression entirely (routed to NoOpCompressor).
      - Bulk Lane (lossy-tolerant): Summaries, concepts, code extracts, and tabular
        data compressed only when exceeding budget.

    section_type → compressor name:
      Protected Lane (0% loss, emitted verbatim):
        "decision"         → "noop"
        "constraint"       → "noop"
        "negative_control" → "noop"
        "exact_fact"       → "noop"
      Bulk Lane:
        "graph"            → "graph_bundle"   (graph-native pruning — do not substitute)
        "semantic"         → "graph_bundle"   (semantic nodes carry graph signals)
        "tabular"          → "structured_data"
        "summary"          → "llm_prose"      (only fires when prose is present)
        "code"             → "ast_code"       (Phase B: fires when code extracts present)
    """

    PROTECTED_SECTION_TYPES: frozenset[str] = frozenset({
        "decision",
        "constraint",
        "negative_control",
        "exact_fact",
    })

    BULK_SECTION_TYPES: frozenset[str] = frozenset({
        "summary",
        "semantic",
        "graph",
        "code",
        "tabular",
    })

    _ROUTE: dict[str, str] = {
        "graph":            "graph_bundle",
        "semantic":         "graph_bundle",
        "tabular":          "structured_data",
        "summary":          "llm_prose",
        "code":             "ast_code",
        "decision":         "noop",
        "constraint":       "noop",
        "negative_control": "noop",
        "exact_fact":       "noop",
    }

    def __init__(self, registry: PluggableCompressorRegistry) -> None:
        self._registry = registry

    def route(self, section: "BundleSection" | str) -> Compressor:
        """
        Return the Compressor instance for this section according to two-lane routing.
        Protected lane -> NoOpCompressor (zero loss).
        Bulk lane -> specialized compressor from registry.
        """
        sec_type = section if isinstance(section, str) else getattr(section, "section_type", "")
        sec_type = str(sec_type).lower()

        if sec_type in self.PROTECTED_SECTION_TYPES:
            return self._registry.get("noop")

        if sec_type in self.BULK_SECTION_TYPES:
            name = self._ROUTE.get(sec_type, "noop")
            return self._registry.get(name)

        name = self._ROUTE.get(sec_type, "noop")
        return self._registry.get(name)

    def is_protected(self, section: "BundleSection" | str) -> bool:
        """Return True if section belongs to Protected Lane."""
        sec_type = section if isinstance(section, str) else getattr(section, "section_type", "")
        return str(sec_type).lower() in self.PROTECTED_SECTION_TYPES

    def compress_section(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        compressor = self.route(section)
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
