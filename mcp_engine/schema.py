"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.hippocampus.schema
"""

from campy.brain.hippocampus.schema import *  # noqa: F401,F403
# Private names are not exported by `import *`; re-export them explicitly so
# that test code importing them from the old path continues to work.
from campy.brain.hippocampus.schema import (  # noqa: F401
    _parse_seed_examples,
    _bootstrap_centroids,
)
