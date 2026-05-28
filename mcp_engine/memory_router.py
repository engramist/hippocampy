"""
Compatibility shim — canonical location is campy/brain/temporal_lobe/memory_router.py

Do not add logic here. Import from the canonical module instead.
"""

from campy.brain.temporal_lobe.memory_router import (  # noqa: F401
    DOCUMENT_EXTENSIONS,
    TABULAR_EXTENSIONS,
    MemoryRoute,
    _looks_tabular,
    classify_input,
)
