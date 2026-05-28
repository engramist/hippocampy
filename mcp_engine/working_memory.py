# Compatibility shim — canonical location is campy/brain/thalamus/working_memory.py
from campy.brain.thalamus.working_memory import *  # noqa: F401, F403
from campy.brain.thalamus.working_memory import (
    estimate_tokens,
    track_loaded,
    get_loaded_node_ids,
    deduplicate_results,
    update_token_estimate,
    get_session_token_state,
    check_context_health,
    get_handoff_context,
    get_session_token_timeline,
    _count_loaded,
    NODE_PK_MAP,
    BLOAT_WARNING_THRESHOLD,
    DEDUP_DEMOTION_FACTOR,
    DEFAULT_TOKEN_LIMIT,
    CHARS_PER_TOKEN,
)
