"""
Compatibility shim — canonical location is campy/brain/temporal_lobe/dictionary.py

Do not add logic here. Import from the canonical module instead.
"""

from campy.brain.temporal_lobe.dictionary import (  # noqa: F401
    DICTIONARY_PATHS,
    VALID_GIST_CLASSES,
    find_dictionary,
    ingest_dictionary,
    load_dictionary,
)
