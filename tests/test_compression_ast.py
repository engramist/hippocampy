# tests/test_compression_ast.py
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.ast_mapper import ASTCodeCompressor

_PYTHON_SOURCE = '''
class UserManager:
    """Manages user authentication."""
    def __init__(self, db):
        self.db = db
        self._cache = {}
        self._session_store = {}

    def authenticate(self, username, password):
        # Expensive validation
        user = self.db.query("SELECT * FROM users WHERE username=?", username)
        if user and verify_hash(password, user.hash):
            return UserSession(user.id)
        return None

    def logout(self, session_id):
        if session_id in self._session_store:
            del self._session_store[session_id]
'''


def _code_section(source: str) -> BundleSection:
    return BundleSection(
        section_type="code",
        content=[{"source": source, "language": "python"}],
        token_estimate=len(source) // 4,
        source_node_ids=[],
    )


def test_ast_folds_function_bodies():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    text = result.content[0]["source"]
    assert "def authenticate" in text
    assert "verify_hash" not in text  # body stripped
    assert "def logout" in text
    assert "del self._session_store" not in text  # body stripped


def test_ast_preserves_class_and_signatures():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    text = result.content[0]["source"]
    assert "class UserManager" in text
    assert "def authenticate(self, username, password)" in text


def test_ast_reduces_token_count():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    assert result.token_estimate < section.token_estimate


def test_empty_section_returns_unchanged():
    section = BundleSection(
        section_type="code", content=[], token_estimate=0, source_node_ids=[]
    )
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    assert result.content == []
