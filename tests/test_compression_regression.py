"""
Regression guard: runs all four compressors on canonical fixtures and
asserts compression ratios do not regress by more than 5%.

If this test fails after a code change, the compression pipeline has
regressed. Check which compressor is affected and restore or improve it.
"""

import json
import math
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRUCTURED_CONTENT = [
    {"key": f"setting_{i}", "value": f"value_{i}", "node_type": "GlobalConstraint"}
    for i in range(20)
]

_GRAPH_CONTENT = [
    {
        "text": f"concept about {'auth' if i < 5 else 'unrelated topic'} {i}",
        "type": "Concept" if i % 2 == 0 else "Decision",
        "pathway_strength": 0.9 if i < 5 else 0.05,
        "confidence": 0.85,
    }
    for i in range(20)
]

_PYTHON_SOURCE = '''
class AuthManager:
    def __init__(self, db, cache):
        self.db = db
        self.cache = cache
        self._sessions = {}

    def authenticate(self, username, password):
        if username in self.cache:
            return self.cache[username]
        user = self.db.find(username)
        if user and verify(password, user.hash):
            token = generate_token(user.id)
            self.cache[username] = token
            return token
        return None

    def logout(self, token):
        for key, val in list(self._sessions.items()):
            if val == token:
                del self._sessions[key]
'''


def _make_section(section_type: str, content: list) -> BundleSection:
    return BundleSection(
        section_type=section_type,
        content=content,
        token_estimate=max(1, len(json.dumps(content)) // 4),
        source_node_ids=[],
    )


# ---------------------------------------------------------------------------
# Minimum compression ratios (token_estimate_after / token_estimate_before)
# A ratio < 1.0 means compression reduced token count.
# The guard fails if the ratio exceeds the threshold (i.e., not enough compression).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("compressor_name,section_type,content,max_ratio", [
    (
        "structured_data",
        "exact_fact",
        _STRUCTURED_CONTENT,
        0.75,  # must reduce by at least 25%
    ),
    (
        "graph_bundle",
        "semantic",
        _GRAPH_CONTENT,
        0.70,  # must reduce by at least 30% (pruning + compact notation)
    ),
    (
        "ast_code",
        "code",
        [{"source": _PYTHON_SOURCE, "language": "python"}],
        0.40,  # must reduce by at least 60%
    ),
])
def test_compression_ratio_not_regressed(compressor_name, section_type, content, max_ratio):
    from campy.brain.thalamus.compression import build_default_registry

    config = {
        "compression": {
            "graph_prune_threshold": 0.50,
            "structured_format": "toon",
            "ast_compression": True,
        }
    }
    registry, _ = build_default_registry(config)
    compressor = registry.get(compressor_name)

    section = _make_section(section_type, content)
    result = compressor.compress(section, "auth", config)

    ratio = result.token_estimate / section.token_estimate
    assert ratio <= max_ratio, (
        f"{compressor_name} compression ratio {ratio:.2f} exceeds max {max_ratio:.2f}. "
        f"Before: {section.token_estimate} tokens, After: {result.token_estimate} tokens."
    )
