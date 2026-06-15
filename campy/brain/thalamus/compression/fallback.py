"""campy/brain/thalamus/compression/fallback.py — NoOp passthrough compressor."""

from __future__ import annotations
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class NoOpCompressor(Compressor):
    """Returns the section unchanged. Used as fallback and opt-out."""

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        return section
