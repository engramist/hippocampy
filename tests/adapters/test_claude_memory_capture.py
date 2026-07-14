from pathlib import Path

from adapters.claude_code.hooks.claude_memory_capture import (
    build_notify_turn_payload,
    is_claude_memory_file,
    parse_memory_markdown,
    should_capture_memory_file,
)


def test_detects_claude_memory_file():
    path = "/Users/me/.claude/projects/my-repo/memory/project_example.md"
    assert is_claude_memory_file(path)


def test_skips_memory_index_file():
    path = "/Users/me/.claude/projects/my-repo/memory/MEMORY.md"
    assert not should_capture_memory_file(path)


def test_parses_memory_frontmatter_and_body(tmp_path: Path):
    mem_file = tmp_path / "project_rule.md"
    mem_file.write_text(
        "---\n"
        "name: project_rule\n"
        "description: Keep hooks non-blocking\n"
        "metadata:\n"
        "  type: project\n"
        "---\n\n"
        "Rule: Never block agent responses in hooks.\n"
        "Why: Keep UX smooth.\n"
        "How to apply: Use try/except pass.\n"
    )

    parsed = parse_memory_markdown(str(mem_file))

    assert parsed is not None
    assert parsed["name"] == "project_rule"
    assert parsed["description"] == "Keep hooks non-blocking"
    assert parsed["memory_type"] == "project"
    assert "Rule:" in parsed["body"]


def test_build_notify_payload_is_structured_and_stable():
    payload1 = build_notify_turn_payload(
        {
            "name": "project_rule",
            "description": "Keep hooks non-blocking",
            "memory_type": "project",
            "body": "Rule: x\nWhy: y\nHow to apply: z",
        },
        session_id="sess-1",
    )
    payload2 = build_notify_turn_payload(
        {
            "name": "project_rule",
            "description": "Keep hooks non-blocking",
            "memory_type": "project",
            "body": "Rule: x updated\nWhy: y\nHow to apply: z",
        },
        session_id="sess-1",
    )

    assert payload1["role"] == "system"
    assert payload1["source"] == "claude_auto_memory"
    assert payload1["source_memory_class"] == "project"
    assert payload1["source_memory_name"] == "project_rule"
    assert "source_memory_class: project" in payload1["content"]
    # Idempotency key should be stable across edits to body when name is unchanged.
    assert payload1["source_memory_key"] == payload2["source_memory_key"]


# ---------------------------------------------------------------------------
# B298 decision #3: upsert, not append — notify_turn must archive the previous
# live version of the same memory (matched by the stable memory_key marker)
# before writing the new one.
# ---------------------------------------------------------------------------

import pytest
from unittest.mock import MagicMock


class _EmptyResult:
    """Query result stub: MagicMock's truthy has_next() would spin forever
    in the while-loops inside route_session and friends."""

    def has_next(self):
        return False


def _make_capture_db(written):
    mock_db = MagicMock()
    mock_db.execute = lambda *a, **k: _EmptyResult()
    mock_db.vector_search = lambda *a, **k: []

    async def capture_write(q, p=None):
        written.append((q, p or {}))

    mock_db.execute_write = capture_write
    return mock_db


@pytest.mark.asyncio
async def test_notify_turn_supersedes_prior_memory_version(monkeypatch):
    from campy.brain.thalamus.tools import capture as capture_mod

    monkeypatch.setattr(capture_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)

    written = []
    mock_db = _make_capture_db(written)

    payload = build_notify_turn_payload(
        {
            "name": "project_rule",
            "description": "Keep hooks non-blocking",
            "memory_type": "project",
            "body": "Rule: v2 of the rule",
        },
        session_id="unknown",
    )

    result = await capture_mod.notify_turn(payload, mock_db, {})
    assert result["status"] == "ingested"

    key = payload["source_memory_key"]
    supersede_writes = [
        (q, p) for q, p in written
        if "archived = true" in q and p.get("marker") == f"memory_key: {key}"
    ]
    assert len(supersede_writes) == 1, (
        "notify_turn must archive prior live Messages carrying the same "
        "memory_key before creating the new version"
    )

    # The archive must be issued BEFORE the new Message CREATE.
    create_idx = next(i for i, (q, _) in enumerate(written) if "CREATE (m:Message" in q)
    supersede_idx = next(
        i for i, (q, p) in enumerate(written)
        if "archived = true" in q and p.get("marker") == f"memory_key: {key}"
    )
    assert supersede_idx < create_idx


@pytest.mark.asyncio
async def test_notify_turn_without_memory_key_never_archives(monkeypatch):
    from campy.brain.thalamus.tools import capture as capture_mod

    monkeypatch.setattr(capture_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)

    written = []
    mock_db = _make_capture_db(written)

    result = await capture_mod.notify_turn(
        {"role": "user", "content": "an ordinary turn", "session_id": "unknown"},
        mock_db,
        {},
    )
    assert result["status"] == "ingested"
    assert not any("archived = true" in q for q, _ in written)
