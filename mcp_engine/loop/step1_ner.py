"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.temporal_lobe.loop.step1_ner
"""

from campy.brain.temporal_lobe.loop.step1_ner import *  # noqa: F401,F403
from campy.brain.temporal_lobe.loop.step1_ner import (  # noqa: F401
    _is_junk_entity,
    _nlp,
    _SKIP_CHUNKS,
    _UUID_RE,
    _HEX_HASH_RE,
    _ORDINAL_RE,
    _SYSTEM_TERMS,
)
