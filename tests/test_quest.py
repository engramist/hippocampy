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

    class MockDB:
        def execute(self, query, params=None):
            # MERGE doesn't call execute() — this mock is unused but kept for clarity
            class R:
                def has_next(self): return False
                def get_next(self): return []
            return R()
        async def execute_write(self, query, params=None):
            writes.append(params)

    quest_id = await get_or_create_main_quest(
        MockDB(), "/repo/myapp", "main",
        "sentence-transformers/all-MiniLM-L6-v2",
        "2024-01-01T00:00:00+00:00"
    )

    assert quest_id == compute_quest_id("/repo/myapp", "main")
    # MERGE always writes (ON MATCH updates last_active_at) — idempotent, not skipped
    assert len(writes) == 1
    assert writes[0]["quest_id"] == quest_id


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


# ---------------------------------------------------------------------------
# notify_turn M5 quest wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_turn_creates_main_quest_when_repo_provided():
    """notify_turn with repo_root triggers MainQuest creation."""
    from mcp_engine.tools import notify_turn, init_loop_queue
    import asyncio

    init_loop_queue(asyncio.Queue())

    writes = []

    class MockQueryResult:
        def has_next(self): return False  # quest doesn't exist yet

    class MockDB:
        def execute(self, query, params=None):
            return MockQueryResult()
        async def execute_write(self, query, params=None):
            writes.append(query)

    result = await notify_turn(
        {
            "role":       "user",
            "content":    "We decided to use PostgreSQL",
            "session_id": "sess-001",
            "repo_root":  "/repo/myapp",
            "git_branch": "main",
        },
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
         "ingestion": {"max_ingest_chars": 4000}}
    )

    assert result["status"] == "queued"
    assert result["quest_id"] != ""  # quest_id returned

    combined = " ".join(writes)
    assert "MainQuest" in combined       # quest was created
    assert "WORKING_ON" in combined      # session linked to quest
    assert "Message" in combined         # message was stored
    assert "SENT_IN" in combined         # message linked to session


@pytest.mark.asyncio
async def test_notify_turn_skips_quest_wiring_without_repo():
    """notify_turn without repo_root skips quest creation (legacy mode)."""
    from mcp_engine.tools import notify_turn, init_loop_queue
    import asyncio

    init_loop_queue(asyncio.Queue())

    writes = []

    class MockDB:
        def execute(self, query, params=None): return None
        async def execute_write(self, query, params=None):
            writes.append(query)

    result = await notify_turn(
        {"role": "user", "content": "Some message", "session_id": "sess-002"},
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
         "ingestion": {"max_ingest_chars": 4000}}
    )

    assert result["status"] == "queued"
    assert result["quest_id"] == ""      # no quest resolved

    combined = " ".join(writes)
    assert "MainQuest" not in combined   # no quest creation attempted
    assert "Message" in combined         # message still stored


@pytest.mark.asyncio
async def test_notify_turn_empty_content_skipped():
    """Empty content returns skipped without any DB writes."""
    from mcp_engine.tools import notify_turn

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append(query)

    result = await notify_turn(
        {"role": "user", "content": "   ", "session_id": "s"},
        MockDB(),
        {}
    )

    assert result["status"] == "skipped"
    assert len(writes) == 0


# ---------------------------------------------------------------------------
# current_truth M5 quest_context in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_current_truth_returns_quest_context_for_branch_scope():
    """current_truth with quest_id returns quest_context in response."""
    from mcp_engine.tools import current_truth

    class MockQueryResult:
        def has_next(self): return False

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return []
        def execute(self, query, params=None):
            return MockQueryResult()

    result = await current_truth(
        {
            "query":      "database choice",
            "session_id": "s1",
            "scope":      "branch",
            "quest_id":   "abc123",
        },
        MockDB(),
        {"embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"}}
    )

    assert "results" in result
    assert "quest_context" in result
    assert isinstance(result["quest_context"], dict)


@pytest.mark.asyncio
async def test_current_truth_empty_query_returns_empty():
    from mcp_engine.tools import current_truth

    class MockDB:
        pass

    result = await current_truth(
        {"query": "", "session_id": "s1"},
        MockDB(),
        {}
    )
    assert result["results"] == []
    assert result["quest_context"] == {}


# ---------------------------------------------------------------------------
# maybe_synthesize_purpose — T4 coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maybe_synthesize_purpose_skips_when_no_llm():
    """Returns False immediately when llm_client is None."""
    from mcp_engine.quest import maybe_synthesize_purpose

    class MockDB:
        def execute(self, q, p=None): return None

    result = await maybe_synthesize_purpose(
        MockDB(), "msg-1", "artifact text", None,
        "sentence-transformers/all-MiniLM-L6-v2", "2024-01-01T00:00:00+00:00"
    )
    assert result is False


@pytest.mark.asyncio
async def test_maybe_synthesize_purpose_skips_when_session_not_found():
    """Returns False when message has no linked session."""
    from mcp_engine.quest import maybe_synthesize_purpose

    class MockResult:
        def has_next(self): return False   # no session found

    class MockDB:
        def execute(self, q, p=None): return MockResult()

    class FakeLLM:
        async def achat(self, messages): return "some purpose"

    result = await maybe_synthesize_purpose(
        MockDB(), "msg-1", "artifact", FakeLLM(),
        "sentence-transformers/all-MiniLM-L6-v2", "2024-01-01T00:00:00+00:00"
    )
    assert result is False


@pytest.mark.asyncio
async def test_maybe_synthesize_purpose_skips_when_already_set():
    """Returns False when Session.purpose is already non-empty."""
    from mcp_engine.quest import maybe_synthesize_purpose

    call_count = [0]

    class MockResult:
        def has_next(self): return True
        def get_next(self): return ["sess-1", "Already synthesized purpose."]

    class MockDB:
        def execute(self, q, p=None): return MockResult()
        async def execute_write(self, q, p=None):
            call_count[0] += 1

    class FakeLLM:
        async def achat(self, messages): return "new purpose"

    result = await maybe_synthesize_purpose(
        MockDB(), "msg-1", "artifact", FakeLLM(),
        "sentence-transformers/all-MiniLM-L6-v2", "2024-01-01T00:00:00+00:00"
    )
    assert result is False
    assert call_count[0] == 0   # no writes performed


@pytest.mark.asyncio
async def test_maybe_synthesize_purpose_writes_on_empty_session():
    """Returns True and writes purpose to Session when session has no purpose."""
    from mcp_engine.quest import maybe_synthesize_purpose

    writes = []
    query_idx = [0]

    def mock_execute(q, p=None):
        idx = query_idx[0]
        query_idx[0] += 1

        class R:
            _row = None
            def has_next(self): return self._row is not None
            def get_next(self): return self._row

        r = R()
        if idx == 0:
            # First query: look up session — found, purpose empty
            r._row = ["sess-1", ""]
            r.has_next = lambda: True
            r.get_next = lambda: ["sess-1", ""]
        elif idx == 1:
            # Second query: look up MainQuest for session
            r._row = ["quest-1", "myapp [main]"]
            r.has_next = lambda: True
            r.get_next = lambda: ["quest-1", "myapp [main]"]
        else:
            # Third query: context messages
            r.has_next = lambda: False
        return r

    class MockDB:
        def execute(self, q, p=None): return mock_execute(q, p)
        async def execute_write(self, q, p=None): writes.append({"query": q, "params": p})

    class FakeLLM:
        async def achat(self, messages):
            return "Building an AI memory system for local use."

    result = await maybe_synthesize_purpose(
        MockDB(), "msg-1", "Use Kùzu as primary database", FakeLLM(),
        "sentence-transformers/all-MiniLM-L6-v2", "2024-01-01T00:00:00+00:00"
    )
    assert result is True
    # At least one write to Session.purpose
    combined = " ".join(w["query"] for w in writes)
    assert "Session" in combined or "session" in combined.lower()
    # Purpose text should appear in write params
    assert any(
        w["params"] is not None and "Building an AI memory system" in str(w["params"])
        for w in writes
    )


@pytest.mark.asyncio
async def test_maybe_synthesize_purpose_uses_achat_when_available():
    """Uses achat() (async) when the LLM client supports it."""
    from mcp_engine.quest import maybe_synthesize_purpose

    achat_called = [False]
    query_idx = [0]

    def mock_execute(q, p=None):
        idx = query_idx[0]
        query_idx[0] += 1

        class R:
            def has_next(self): return False

        if idx == 0:
            class R:  # noqa: F811
                def has_next(self): return True
                def get_next(self): return ["sess-x", ""]
        elif idx == 1:
            class R:  # noqa: F811
                def has_next(self): return True
                def get_next(self): return ["q-x", "project"]
        return R()

    class MockDB:
        def execute(self, q, p=None): return mock_execute(q, p)
        async def execute_write(self, q, p=None): pass

    class FakeLLM:
        async def achat(self, messages):
            achat_called[0] = True
            return "Some purpose."

    await maybe_synthesize_purpose(
        MockDB(), "msg-2", "artifact", FakeLLM(),
        "sentence-transformers/all-MiniLM-L6-v2", "2024-01-01T00:00:00+00:00"
    )
    assert achat_called[0] is True
