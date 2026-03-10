import pytest

# Required for pytest-asyncio < 0.21 compatibility
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
