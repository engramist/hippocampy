# Compatibility shim — canonical location is campy/brain/thalamus/trigger_manifest.py
from campy.brain.thalamus.trigger_manifest import *  # noqa: F401, F403
from campy.brain.thalamus.trigger_manifest import (
    get_manifest_path,
    _build_snippet,
    _procedure_snippet,
)

import sys
import campy.brain.thalamus.trigger_manifest as _canonical_trigger


async def compile_manifest(db, config: dict) -> dict:
    """Thin shim so that patching mcp_engine.trigger_manifest.get_manifest_path works in tests."""
    _shim = sys.modules[__name__]
    _orig = _canonical_trigger.get_manifest_path
    _canonical_trigger.get_manifest_path = _shim.get_manifest_path
    try:
        return await _canonical_trigger.compile_manifest(db, config)
    finally:
        _canonical_trigger.get_manifest_path = _orig
