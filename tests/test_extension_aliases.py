from pathlib import Path


EXTENSION_SRC = (
    Path(__file__).parent.parent
    / "extensions"
    / "sidequests-brain"
    / "src"
    / "index.ts"
)


def _source() -> str:
    return EXTENSION_SRC.read_text()


def test_extension_registers_memory_search_alias():
    src = _source()
    assert '"memory_search"' in src
    assert '"Alias for memory_recall.' in src


def test_extension_registers_memory_get_alias():
    src = _source()
    assert '"memory_get"' in src
    assert '"Alias for memory_recall.' in src


def test_extension_aliases_route_to_current_truth():
    src = _source()
    assert 'const registerRecallTool = (' in src
    assert 'brain.callTool("current_truth"' in src
    assert 'registerRecallTool(\n      "memory_search"' in src
    assert 'registerRecallTool(\n      "memory_get"' in src
