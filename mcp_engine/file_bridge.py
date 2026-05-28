# Compatibility shim — canonical location is campy/brain/thalamus/file_bridge.py
from campy.brain.thalamus.file_bridge import *  # noqa: F401, F403
from campy.brain.thalamus.file_bridge import (
    generate_context_md,
    generate_adrs,
    generate_agent_pointers,
    regen_all,
    check_file_changes,
    _resolve_project_child,
    _slugify,
    _truncate_to_sentences,
    CAMPY_POINTER,
)
