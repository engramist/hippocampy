"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.sensory_cortex.ingest
"""

from campy.brain.sensory_cortex.ingest import *  # noqa: F401,F403
from campy.brain.sensory_cortex.ingest import (  # noqa: F401
    _stable_doc_id,
    _get_existing_hash,
)
