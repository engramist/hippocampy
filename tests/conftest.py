import pytest

# Required for pytest-asyncio < 0.21 compatibility
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )

# B387: spaCy (and the pydantic.v1/Python-3.14 compatibility shim that used
# to live here to keep it importable) has been removed entirely — NER now
# runs on campy/brain/temporal_lobe/loop/onnx_ner_engine.py. SPACY_AVAILABLE
# is kept as a permanently-False alias only so any straggling
# `@pytest.mark.skipif(not SPACY_AVAILABLE, ...)` elsewhere fails closed
# (skips) instead of raising ImportError; new tests should not use it.
SPACY_AVAILABLE = False
