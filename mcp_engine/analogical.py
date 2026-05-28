# Compatibility shim — canonical location is campy/brain/thalamus/analogical.py
from campy.brain.thalamus.analogical import *  # noqa: F401, F403
from campy.brain.thalamus.analogical import (
    analogical_search,
    find_similar_quests,
    _get_quest_for_artifact,
    CROSS_QUEST_TABLES,
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_LIMIT,
)
