# Compatibility shim — canonical location is campy/brain/thalamus/wiki_projection.py
from campy.brain.thalamus.wiki_projection import *  # noqa: F401, F403
from campy.brain.thalamus.wiki_projection import (
    WikiPage,
    export_wiki_projection,
    _load_personas,
    _export_single_persona,
    _select_pages_for_persona,
    _compute_hash,
    _render_page,
    _render_home_page,
    _render_index_pages,
    _write_atomic,
    _slugify,
)
