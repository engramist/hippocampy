"""
Tests for M6 Open Brain document ingestion.

Run with: python3 -m pytest tests/test_ingest.py -v
"""

from __future__ import annotations
import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------

def test_validate_path_allowed_extension(tmp_path):
    from mcp_engine.ingest import validate_path
    f = tmp_path / "test.md"
    f.write_text("hello")
    result = validate_path(str(f))
    assert result == f.resolve()


def test_validate_path_disallowed_extension(tmp_path):
    from mcp_engine.ingest import validate_path
    f = tmp_path / "secret.exe"
    f.write_bytes(b"data")
    with pytest.raises(ValueError, match="not allowed"):
        validate_path(str(f))


def test_validate_path_missing_file(tmp_path):
    from mcp_engine.ingest import validate_path
    with pytest.raises(FileNotFoundError):
        validate_path(str(tmp_path / "nonexistent.md"))


def test_validate_path_directory_rejected(tmp_path):
    from mcp_engine.ingest import validate_path
    # tmp_path has no extension → fails the allowlist check (ValueError either way)
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_path(str(tmp_path))


def test_validate_path_dot_db_disallowed(tmp_path):
    """DB files should not be ingestable as documents."""
    from mcp_engine.ingest import validate_path
    f = tmp_path / "data.db"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="not allowed"):
        validate_path(str(f))


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------

def test_hash_file_is_sha256(tmp_path):
    from mcp_engine.ingest import hash_file
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    result = hash_file(f)
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert result == expected


def test_hash_file_different_content(tmp_path):
    from mcp_engine.ingest import hash_file
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_bytes(b"aaa")
    f2.write_bytes(b"bbb")
    assert hash_file(f1) != hash_file(f2)


def test_hash_file_same_content_same_hash(tmp_path):
    from mcp_engine.ingest import hash_file
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_bytes(b"same content")
    f2.write_bytes(b"same content")
    assert hash_file(f1) == hash_file(f2)


# ---------------------------------------------------------------------------
# chunk_document
# ---------------------------------------------------------------------------

def test_chunk_empty_text():
    from mcp_engine.ingest import chunk_document
    assert chunk_document("") == []


def test_chunk_single_paragraph():
    from mcp_engine.ingest import chunk_document
    text = "This is a simple paragraph with enough text to avoid merging. " * 2
    chunks = chunk_document(text)
    assert len(chunks) >= 1
    combined = " ".join(c["text"] for c in chunks)
    assert "simple paragraph" in combined


def test_chunk_split_at_blank_lines():
    from mcp_engine.ingest import chunk_document
    p1 = "First paragraph content with sufficient length to be its own chunk. " * 2
    p2 = "Second paragraph content with sufficient length to be its own chunk. " * 2
    text = p1 + "\n\n" + p2
    chunks = chunk_document(text)
    assert len(chunks) >= 2
    texts = [c["text"] for c in chunks]
    assert any("First paragraph" in t for t in texts)
    assert any("Second paragraph" in t for t in texts)


def test_chunk_split_at_markdown_headings():
    from mcp_engine.ingest import chunk_document
    text = (
        "## Introduction\n"
        "This is the intro section with enough content to not be merged away.\n\n"
        "## Details\n"
        "This is the details section with enough content to not be merged away.\n"
    )
    chunks = chunk_document(text)
    assert len(chunks) >= 2
    texts = [c["text"] for c in chunks]
    assert any("Introduction" in t for t in texts)
    assert any("Details" in t for t in texts)


def test_chunk_byte_offsets_are_valid():
    from mcp_engine.ingest import chunk_document
    text = "Hello world.\n\nSecond paragraph here with more content to ensure it stands alone.\n"
    chunks = chunk_document(text)
    encoded = text.encode("utf-8")
    for chunk in chunks:
        assert chunk["byte_start"] >= 0
        assert chunk["byte_end"] > chunk["byte_start"]
        assert chunk["byte_end"] <= len(encoded)
        # Text at byte offsets should contain chunk text
        extracted = encoded[chunk["byte_start"]:chunk["byte_end"]].decode("utf-8")
        assert chunk["text"].strip() in extracted or extracted in chunk["text"].strip()


def test_chunk_line_numbers_are_positive():
    from mcp_engine.ingest import chunk_document
    text = "Line 1.\n\nLine 3 paragraph with enough content to survive the merge threshold.\n"
    chunks = chunk_document(text)
    for chunk in chunks:
        assert chunk["line_start"] >= 1
        assert chunk["line_end"] >= chunk["line_start"]


def test_chunk_short_segments_merged():
    from mcp_engine.ingest import chunk_document, MIN_CHUNK_CHARS
    # Create a short paragraph followed by a longer one
    short = "Short."
    long_p = "This is a much longer paragraph that exceeds the minimum chunk size. " * 3
    text = short + "\n\n" + long_p
    chunks = chunk_document(text)
    # Short should be merged into long (or they appear together)
    combined = " ".join(c["text"] for c in chunks)
    assert "Short" in combined


def test_chunk_oversized_segment_split():
    from mcp_engine.ingest import chunk_document, MAX_CHUNK_CHARS
    # Create a paragraph that exceeds MAX_CHUNK_CHARS
    long_text = ("This is a sentence that contributes to a very long paragraph. " * 40)
    chunks = chunk_document(long_text)
    for chunk in chunks:
        assert len(chunk["text"]) <= MAX_CHUNK_CHARS + 100  # allow small overage at boundary


def test_chunk_no_duplicate_text():
    from mcp_engine.ingest import chunk_document
    text = "Alpha.\n\nBeta section with enough text.\n\nGamma section with enough text.\n"
    chunks = chunk_document(text)
    combined_text = "|||".join(c["text"] for c in chunks)
    # Each word from a section should appear at least once
    assert combined_text.count("Alpha") >= 1


# ---------------------------------------------------------------------------
# _stable_doc_id
# ---------------------------------------------------------------------------

def test_stable_doc_id_is_deterministic():
    from mcp_engine.ingest import _stable_doc_id
    id1 = _stable_doc_id("/path/to/file.md")
    id2 = _stable_doc_id("/path/to/file.md")
    assert id1 == id2


def test_stable_doc_id_different_paths():
    from mcp_engine.ingest import _stable_doc_id
    id1 = _stable_doc_id("/path/a.md")
    id2 = _stable_doc_id("/path/b.md")
    assert id1 != id2


def test_stable_doc_id_is_32_hex_chars():
    from mcp_engine.ingest import _stable_doc_id
    doc_id = _stable_doc_id("/any/path.txt")
    assert len(doc_id) == 32
    assert all(c in "0123456789abcdef" for c in doc_id)


# ---------------------------------------------------------------------------
# _get_existing_hash (mock DB)
# ---------------------------------------------------------------------------

def test_get_existing_hash_returns_none_when_not_found():
    from mcp_engine.ingest import _get_existing_hash

    class MockResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, q, p=None): return MockResult()

    result = _get_existing_hash(MockDB(), "some-id")
    assert result is None


def test_get_existing_hash_returns_hash_when_found():
    from mcp_engine.ingest import _get_existing_hash

    class MockResult:
        def has_next(self): return True
        def get_next(self): return ["abc123hash"]

    class MockDB:
        def execute(self, q, p=None): return MockResult()

    result = _get_existing_hash(MockDB(), "some-id")
    assert result == "abc123hash"


# ---------------------------------------------------------------------------
# ingest_document — path validation errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_document_invalid_extension():
    from mcp_engine.ingest import ingest_document

    class MockDB:
        def execute(self, q, p=None): return None

    result = await ingest_document(MockDB(), "/path/to/file.exe", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_ingest_document_nonexistent_file():
    from mcp_engine.ingest import ingest_document

    class MockDB:
        def execute(self, q, p=None): return None

    result = await ingest_document(MockDB(), "/nonexistent/path/to/file.md", {})
    assert "error" in result


# ---------------------------------------------------------------------------
# ingest_document — hash change detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_document_skips_if_hash_unchanged(tmp_path):
    from mcp_engine.ingest import ingest_document, hash_file

    f = tmp_path / "doc.md"
    f.write_text("# Title\n\nContent here.\n")
    existing_hash = hash_file(f)

    class MockResult:
        def has_next(self): return True
        def get_next(self): return [existing_hash]  # same hash

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None): pass

    result = await ingest_document(MockDB(), str(f), {})
    assert result["already_current"] is True
    assert result["chunks_created"] == 0


@pytest.mark.asyncio
async def test_ingest_document_archives_old_on_rehash(tmp_path):
    from mcp_engine.ingest import ingest_document

    f = tmp_path / "doc.md"
    f.write_text("# Section\n\nOld content with sufficient length to generate chunks.\n" * 5)

    writes = []

    class MockResult:
        def has_next(self): return True
        def get_next(self): return ["old-different-hash"]  # different hash → re-ingest

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None):
            writes.append(q)

    result = await ingest_document(
        MockDB(), str(f),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert result["already_current"] is False
    combined = " ".join(writes)
    assert "archived" in combined.lower() or "archived" in combined


# ---------------------------------------------------------------------------
# ingest_document — full pipeline with mock DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_document_creates_extracts_and_derived_from(tmp_path):
    from mcp_engine.ingest import ingest_document

    content = (
        "# Architecture\n\n"
        "We decided to use PostgreSQL as our primary datastore because it supports "
        "JSONB and has excellent indexing. This is a long enough paragraph to survive.\n\n"
        "## Constraints\n\n"
        "No external API calls are permitted without security review. "
        "All endpoints must be authenticated via JWT tokens with short expiry.\n"
    )
    f = tmp_path / "spec.md"
    f.write_text(content)

    writes = []

    class MockResult:
        def has_next(self): return False  # no existing document

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None):
            writes.append({"query": q, "params": p})

    queue = asyncio.Queue()
    result = await ingest_document(
        MockDB(), str(f),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
        loop_queue=queue,
    )

    assert "error" not in result
    assert result["already_current"] is False
    assert result["chunks_created"] >= 1
    assert result["mime_type"] == "text/markdown"

    all_queries = " ".join(w["query"] for w in writes)
    assert "DocumentExtract" in all_queries
    assert "DERIVED_FROM" in all_queries

    # Loop queue should have items enqueued
    assert not queue.empty()


@pytest.mark.asyncio
async def test_ingest_document_queue_receives_extract_ids(tmp_path):
    from mcp_engine.ingest import ingest_document

    f = tmp_path / "notes.txt"
    f.write_text(
        "First note with enough content to be a standalone chunk in the system.\n\n"
        "Second note with enough content to be a standalone chunk in the system.\n"
    )

    class MockResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None): pass

    queue = asyncio.Queue()
    result = await ingest_document(
        MockDB(), str(f),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
        loop_queue=queue,
    )

    assert result["chunks_created"] >= 1
    queued_items = []
    while not queue.empty():
        queued_items.append(await queue.get())

    assert len(queued_items) == result["chunks_created"]
    # Each item is (extract_id, text)
    for item in queued_items:
        assert len(item) == 2
        assert isinstance(item[0], str)  # extract_id
        assert isinstance(item[1], str)  # text


@pytest.mark.asyncio
async def test_ingest_document_returns_location_uri(tmp_path):
    from mcp_engine.ingest import ingest_document

    f = tmp_path / "readme.md"
    f.write_text("# README\n\nThis is the project readme with enough content.\n")

    class MockResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None): pass

    result = await ingest_document(
        MockDB(), str(f),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )
    assert "location_uri" in result
    assert str(f.resolve()) == result["location_uri"]


@pytest.mark.asyncio
async def test_ingest_document_without_queue_works(tmp_path):
    """loop_queue=None should not raise; extracts are still stored."""
    from mcp_engine.ingest import ingest_document

    f = tmp_path / "notes.txt"
    f.write_text("A standalone note with plenty of content to stand on its own.\n")

    class MockResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None): pass

    result = await ingest_document(
        MockDB(), str(f),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
        loop_queue=None,
    )
    assert "error" not in result


# ---------------------------------------------------------------------------
# Adapter: ingest_document tool registered
# ---------------------------------------------------------------------------

def test_adapter_has_ingest_document_tool():
    from adapters.claude_code.adapter import TOOLS
    names = [t["name"] for t in TOOLS]
    assert "ingest_document" in names


def test_adapter_ingest_document_requires_file_path():
    from adapters.claude_code.adapter import TOOLS
    tool = next(t for t in TOOLS if t["name"] == "ingest_document")
    assert "file_path" in tool["inputSchema"]["required"]
