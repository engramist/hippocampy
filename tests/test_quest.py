"""
Tests for M5 Quest lifecycle.

Run with: python3 -m pytest tests/test_quest.py -v
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# compute_quest_id
# ---------------------------------------------------------------------------

def test_quest_id_is_deterministic():
    from mcp_engine.quest import compute_quest_id
    id1 = compute_quest_id("/Users/dj/projects/myapp", "main")
    id2 = compute_quest_id("/Users/dj/projects/myapp", "main")
    assert id1 == id2


def test_quest_id_different_branches():
    from mcp_engine.quest import compute_quest_id
    id_main   = compute_quest_id("/Users/dj/projects/myapp", "main")
    id_dev    = compute_quest_id("/Users/dj/projects/myapp", "dev")
    assert id_main != id_dev


def test_quest_id_different_repos():
    from mcp_engine.quest import compute_quest_id
    id_a = compute_quest_id("/Users/dj/projects/alpha", "main")
    id_b = compute_quest_id("/Users/dj/projects/beta",  "main")
    assert id_a != id_b


def test_quest_id_is_32_chars():
    from mcp_engine.quest import compute_quest_id
    qid = compute_quest_id("/repo", "main")
    assert len(qid) == 32
    assert all(c in "0123456789abcdef" for c in qid)


# ---------------------------------------------------------------------------
# get_or_create_main_quest (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_main_quest_creates_on_first_call():
    from mcp_engine.quest import get_or_create_main_quest, compute_quest_id

    writes = []

    class MockQueryResult:
        def has_next(self): return False  # not found

    class MockDB:
        def execute(self, query, params=None):
            return MockQueryResult()
        async def execute_write(self, query, params=None):
            writes.append(params)

    quest_id = await get_or_create_main_quest(
        MockDB(), "/repo/myapp", "main",
        "sentence-transformers/all-MiniLM-L6-v2",
        "2024-01-01T00:00:00+00:00"
    )

    expected = compute_quest_id("/repo/myapp", "main")
    assert quest_id == expected
    assert len(writes) == 1  # one CREATE
    assert writes[0]["quest_id"] == expected
    assert "myapp" in writes[0]["name"]
    assert "main" in writes[0]["name"]


@pytest.mark.asyncio
async def test_get_or_create_main_quest_returns_existing():
    from mcp_engine.quest import get_or_create_main_quest, compute_quest_id

    writes = []

    class MockQueryResult:
        def has_next(self): return True   # already exists
        def get_next(self): return ["existing-id"]

    class MockDB:
        def execute(self, query, params=None):
            return MockQueryResult()
        async def execute_write(self, query, params=None):
            writes.append(params)

    quest_id = await get_or_create_main_quest(
        MockDB(), "/repo/myapp", "main",
        "sentence-transformers/all-MiniLM-L6-v2",
        "2024-01-01T00:00:00+00:00"
    )

    assert quest_id == compute_quest_id("/repo/myapp", "main")
    assert len(writes) == 0  # no write — already existed


# ---------------------------------------------------------------------------
# get_or_create_session (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_session_writes_session_and_link():
    from mcp_engine.quest import get_or_create_session

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append(query)

    await get_or_create_session(MockDB(), "sess-123", "quest-abc",
                                 "2024-01-01T00:00:00+00:00")

    combined = " ".join(writes)
    assert "MERGE" in combined         # idempotent
    assert "WORKING_ON" in combined    # quest link


# ---------------------------------------------------------------------------
# create_side_quest (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_side_quest_creates_node_and_edge():
    from mcp_engine.quest import create_side_quest

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append({"query": query, "params": params})

    side_quest_id = await create_side_quest(
        MockDB(), "Auth Spike", "Explore OAuth2 approach",
        "parent-quest-id",
        "sentence-transformers/all-MiniLM-L6-v2",
        "2024-01-01T00:00:00+00:00"
    )

    assert len(side_quest_id) == 32
    all_queries = " ".join(w["query"] for w in writes)
    assert "SideQuest" in all_queries
    assert "BELONGS_TO" in all_queries

    # SideQuest node should have correct name
    create_write = next(w for w in writes if "SideQuest" in w["query"])
    assert create_write["params"]["name"] == "Auth Spike"
    assert create_write["params"]["purpose"] == "Explore OAuth2 approach"


# ---------------------------------------------------------------------------
# format_context_for_prompt
# ---------------------------------------------------------------------------

def test_format_context_empty_quest_name():
    from mcp_engine.quest import format_context_for_prompt
    result = format_context_for_prompt({"quest_name": "", "status": "active",
                                         "recent_decisions": [], "recent_constraints": [],
                                         "open_loops": [], "side_quests": []})
    assert result == ""


def test_format_context_with_decisions_and_constraints():
    from mcp_engine.quest import format_context_for_prompt
    ctx = {
        "quest_name": "myapp [main]",
        "status":     "active",
        "recent_decisions": [
            {"text_raw": "Use PostgreSQL", "confidence_low": False},
        ],
        "recent_constraints": [
            {"text_raw": "No external APIs", "confidence_low": True},
        ],
        "open_loops":  [],
        "side_quests": [],
    }
    result = format_context_for_prompt(ctx)
    assert "myapp [main]" in result
    assert "PostgreSQL" in result
    assert "No external APIs" in result
    assert "✓" in result   # confirmed decision
    assert "?" in result   # uncertain constraint


def test_format_context_shows_open_loops_count():
    from mcp_engine.quest import format_context_for_prompt
    ctx = {
        "quest_name": "myapp [main]",
        "status":     "active",
        "recent_decisions": [],
        "recent_constraints": [],
        "open_loops":  [{"concept_id": "x", "text_raw": "a"}, {"concept_id": "y", "text_raw": "b"}],
        "side_quests": [],
    }
    result = format_context_for_prompt(ctx)
    assert "2" in result
    assert "Open loops" in result


def test_format_context_shows_side_quests():
    from mcp_engine.quest import format_context_for_prompt
    ctx = {
        "quest_name": "myapp [main]",
        "status":     "active",
        "recent_decisions": [],
        "recent_constraints": [],
        "open_loops":  [],
        "side_quests": [
            {"quest_id": "sq1", "name": "Auth Spike", "purpose": "OAuth"},
        ],
    }
    result = format_context_for_prompt(ctx)
    assert "Auth Spike" in result


# ---------------------------------------------------------------------------
# git context detection (adapter)
# ---------------------------------------------------------------------------

def test_detect_git_context_returns_strings():
    from adapters.claude_code.adapter import detect_git_context
    repo_root, git_branch = detect_git_context()
    # May be empty strings if run outside a git repo — just check types
    assert isinstance(repo_root, str)
    assert isinstance(git_branch, str)


def test_detect_git_context_in_known_repo():
    """Running inside the sidequests-brain repo — should detect it."""
    from adapters.claude_code.adapter import detect_git_context
    repo_root, git_branch = detect_git_context()
    # We know we're in a git repo
    assert repo_root != ""
    assert git_branch != ""
    assert "sidequests-brain" in repo_root


def test_inject_git_context_adds_fields():
    from adapters.claude_code.adapter import _inject_git_context, _REPO_ROOT, _GIT_BRANCH
    params = {"query": "test", "session_id": "s1"}
    result = _inject_git_context(params)
    assert result["repo_root"]  == _REPO_ROOT
    assert result["git_branch"] == _GIT_BRANCH
    assert result["query"]      == "test"   # original keys preserved


# ---------------------------------------------------------------------------
# branch_quest tool (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_branch_quest_tool_creates_side_quest():
    from mcp_engine.tools import branch_quest

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append({"query": query, "params": params})

    result = await branch_quest(
        {
            "name": "Auth Spike",
            "purpose": "Explore OAuth2",
            "parent_quest_id": "abc123",
        },
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )

    assert "side_quest_id" in result
    assert result["name"] == "Auth Spike"
    assert result["parent_quest_id"] == "abc123"
    all_q = " ".join(w["query"] for w in writes)
    assert "SideQuest" in all_q
    assert "BELONGS_TO" in all_q


@pytest.mark.asyncio
async def test_branch_quest_missing_name_returns_error():
    from mcp_engine.tools import branch_quest

    class MockDB:
        async def execute_write(self, query, params=None): pass

    result = await branch_quest({"purpose": "x", "parent_quest_id": "y"},
                                 MockDB(), {})
    assert "error" in result


# ---------------------------------------------------------------------------
# get_open_loops tool (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_open_loops_returns_list():
    from mcp_engine.tools import get_open_loops

    class MockQueryResult:
        _rows = [
            ["cid1", "some concept", "Restriction", "Demand", 0.72, 0.50, "2024-01-01"],
        ]
        _idx = 0
        def has_next(self): return self._idx < len(self._rows)
        def get_next(self):
            row = self._rows[self._idx]; self._idx += 1; return row

    class MockDB:
        def execute(self, query, params=None): return MockQueryResult()

    result = await get_open_loops({}, MockDB(), {})
    assert "open_loops" in result
    assert len(result["open_loops"]) == 1
    assert result["open_loops"][0]["concept_id"] == "cid1"
    assert result["open_loops"][0]["gist_class"] == "Restriction"


# ---------------------------------------------------------------------------
# diff_since tool (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diff_since_missing_timestamp_returns_error():
    from mcp_engine.tools import diff_since

    class MockDB:
        def execute(self, query, params=None): return None

    result = await diff_since({}, MockDB(), {})
    assert "error" in result


@pytest.mark.asyncio
async def test_diff_since_returns_structured_keys():
    from mcp_engine.tools import diff_since

    class MockQueryResult:
        def has_next(self): return False

    class MockDB:
        def execute(self, query, params=None): return MockQueryResult()

    result = await diff_since({"since_iso": "2024-01-01T00:00:00"}, MockDB(), {})
    assert "decisions" in result
    assert "constraints" in result
    assert "requirements" in result
    assert "action_items" in result
    assert result["since_iso"] == "2024-01-01T00:00:00"
