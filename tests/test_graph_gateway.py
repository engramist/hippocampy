"""
Tests for B314 — GraphGateway: Named-Query Chokepoint + Raw-Cypher Ratchet.

Three layers:
  1. `NamedQuery`/`QueryRegistry` validation — static Cypher, declared
     params, duplicate-name rejection, all enforced at registration time.
  2. `GraphGateway.run()`/`execute_raw()` routing — mutating queries go
     through `KuzuClient.execute_write()` (write-lock discipline
     preserved), reads through `execute_read()`, param mismatches raise
     before the database is touched, unregistered names raise `KeyError`.
  3. The migrated slice + the ratchet script: `lessons.py` contains no
     more raw Cypher, and `scripts/check_cypher_ratchet.py`'s counting
     function is exercised directly against fixture files (not by
     committing a deliberately-failing file to this repo).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway, NamedQuery, QueryRegistry
from campy.brain.hippocampus.graph.queries import REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# NamedQuery / QueryRegistry validation (Task 1)
# ---------------------------------------------------------------------------


def test_named_query_with_bare_brace_raises_at_construction():
    """AC: registering a NamedQuery whose cypher contains a bare '{' (not
    part of a Kùzu literal map — i.e. an unresolved format placeholder)
    raises at import/construction time, not in production."""
    with pytest.raises(ValueError, match=r"\{"):
        NamedQuery(
            name="bad.interpolated_table",
            cypher="MATCH (a:{table}) RETURN a",
            params=(),
            mutating=False,
            description="deliberately broken — table name left as a template placeholder",
        )


def test_named_query_kuzu_literal_map_is_allowed():
    """A genuine Kùzu property map (`{key: value}`) must NOT be rejected —
    only an unresolved template/format placeholder should be."""
    query = NamedQuery(
        name="ok.match_by_id",
        cypher="MATCH (l:Lesson {lesson_id: $lid}) RETURN l.lesson_id AS lesson_id",
        params=("lid",),
        mutating=False,
        description="fine — this is a real Kùzu map literal",
    )
    assert query.name == "ok.match_by_id"


def test_named_query_empty_map_literal_is_allowed():
    query = NamedQuery(
        name="ok.empty_map",
        cypher="MATCH (l:Lesson {}) RETURN l",
        params=(),
        mutating=False,
        description="fine — empty map literal",
    )
    assert query.params == ()


def test_named_query_requires_description():
    with pytest.raises(ValueError):
        NamedQuery(name="bad.no_description", cypher="MATCH (n) RETURN n", params=(), mutating=False, description="")


def test_named_query_params_must_be_tuple():
    with pytest.raises(TypeError):
        NamedQuery(
            name="bad.params_not_tuple",
            cypher="MATCH (n) RETURN n",
            params=["not", "a", "tuple"],  # type: ignore[arg-type]
            mutating=False,
            description="params must be tuple[str, ...]",
        )


def test_query_registry_rejects_duplicate_names():
    registry = QueryRegistry()
    q1 = NamedQuery(name="dup.name", cypher="MATCH (n) RETURN n", params=(), mutating=False, description="first")
    q2 = NamedQuery(name="dup.name", cypher="MATCH (m) RETURN m", params=(), mutating=False, description="second")
    registry.register(q1)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(q2)


def test_query_registry_get_unregistered_name_raises_keyerror_with_name():
    registry = QueryRegistry()
    with pytest.raises(KeyError, match="never.registered"):
        registry.get("never.registered")


# ---------------------------------------------------------------------------
# GraphGateway.run() / execute_raw() routing (Task 1 acceptance criteria)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> QueryRegistry:
    reg = QueryRegistry()
    reg.register(NamedQuery(
        name="test.read_thing",
        cypher="MATCH (n:Thing {id: $id}) RETURN n.id AS id",
        params=("id",),
        mutating=False,
        description="read a Thing by id",
    ))
    reg.register(NamedQuery(
        name="test.write_thing",
        cypher="CREATE (n:Thing {id: $id, label: $label})",
        params=("id", "label"),
        mutating=True,
        description="create a Thing",
    ))
    return reg


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.execute_read = AsyncMock(return_value=[{"id": "t1"}])
    client.execute_write = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_run_unregistered_name_raises_keyerror_with_name(mock_client, registry):
    gateway = GraphGateway(mock_client, registry)
    with pytest.raises(KeyError, match="test.does_not_exist"):
        await gateway.run("test.does_not_exist")
    mock_client.execute_read.assert_not_awaited()
    mock_client.execute_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_missing_declared_param_raises_before_touching_db(mock_client, registry):
    """AC: a missing declared param raises before the database is touched."""
    gateway = GraphGateway(mock_client, registry)
    with pytest.raises(TypeError, match="id"):
        await gateway.run("test.read_thing")  # missing required `id`
    mock_client.execute_read.assert_not_awaited()
    mock_client.execute_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_unexpected_param_raises_before_touching_db(mock_client, registry):
    gateway = GraphGateway(mock_client, registry)
    with pytest.raises(TypeError):
        await gateway.run("test.read_thing", id="t1", surprise="nope")
    mock_client.execute_read.assert_not_awaited()
    mock_client.execute_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_mutating_query_routes_through_execute_write(mock_client, registry):
    """AC: mutating queries route through execute_write — spy on
    KuzuClient.execute_write (not just "the query ran")."""
    gateway = GraphGateway(mock_client, registry)
    await gateway.run("test.write_thing", id="t1", label="hello")

    mock_client.execute_write.assert_awaited_once()
    mock_client.execute_read.assert_not_awaited()
    call_cypher, call_params = mock_client.execute_write.await_args.args
    assert "CREATE" in call_cypher
    assert call_params == {"id": "t1", "label": "hello"}


@pytest.mark.asyncio
async def test_run_read_query_routes_through_execute_read(mock_client, registry):
    """AC: read queries route through execute_read."""
    gateway = GraphGateway(mock_client, registry)
    result = await gateway.run("test.read_thing", id="t1")

    mock_client.execute_read.assert_awaited_once()
    mock_client.execute_write.assert_not_awaited()
    call_cypher, call_params = mock_client.execute_read.await_args.args
    assert "MATCH" in call_cypher
    assert call_params == {"id": "t1"}
    assert result == [{"id": "t1"}]


@pytest.mark.asyncio
async def test_execute_raw_without_reason_raises_typeerror(mock_client, registry):
    """AC: execute_raw() without a `reason` raises TypeError."""
    gateway = GraphGateway(mock_client, registry)
    with pytest.raises(TypeError):
        await gateway.execute_raw("MATCH (n) RETURN n", mutating=False)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_execute_raw_routes_by_mutating_flag(mock_client, registry):
    gateway = GraphGateway(mock_client, registry)

    await gateway.execute_raw("MATCH (n) RETURN n", mutating=False, reason="pre-migration escape hatch, B314 debt")
    mock_client.execute_read.assert_awaited_once()

    await gateway.execute_raw("CREATE (n:X)", mutating=True, reason="pre-migration escape hatch, B314 debt")
    mock_client.execute_write.assert_awaited_once()


# ---------------------------------------------------------------------------
# The real lessons.py registry loads cleanly (Task 1 assembly + Task 2 slice)
# ---------------------------------------------------------------------------


def test_lessons_registry_loads_without_raising():
    """Importing campy.brain.hippocampus.graph.queries registers every
    lessons.py NamedQuery — if any violated the static-Cypher/declared-param
    rules this would already have raised at collection time, but assert the
    registry is non-trivially populated as a direct check too."""
    names = {q.name for q in REGISTRY}
    assert any(name.startswith("lessons.") for name in names)
    assert len(names) >= 20  # the B314 slice migrated 27 named queries


# ---------------------------------------------------------------------------
# Task 2 acceptance criterion: lessons.py has no more raw Cypher driving
# ---------------------------------------------------------------------------


def test_lessons_module_calls_no_raw_kuzu_execute_methods():
    """AC: 'All Cypher in campy/brain/thalamus/tools/lessons.py is gone —
    assert by grepping the file in the test, so the migration cannot
    silently regress.'

    Grepping for MATCH/CREATE/MERGE directly would false-positive on this
    file's own prose comments (e.g. "B68: Create each PlanStep
    individually", "MERGE is incompatible with vector-indexed tables") —
    English words, not Cypher. The precise, regression-proof check is that
    the file no longer *drives* Cypher into the client directly: no
    `db.execute(`, `db.execute_write(`, or `db.execute_read(` call sites
    remain — every query now goes through `gateway.run()` /
    `GraphGateway.execute_raw()`.
    """
    text = (REPO_ROOT / "campy" / "brain" / "thalamus" / "tools" / "lessons.py").read_text(encoding="utf-8")
    forbidden = re.compile(r"\bdb\.execute(_read|_write)?\s*\(")
    matches = forbidden.findall(text)
    assert not matches, f"lessons.py still drives Cypher directly via db.execute*(): {matches}"


# ---------------------------------------------------------------------------
# Ratchet script (Task 4) — unit-test the counting function against
# fixtures, per the card's explicit guidance not to commit a deliberately
# failing file.
# ---------------------------------------------------------------------------


@pytest.fixture
def ratchet_module():
    import importlib
    return importlib.import_module("scripts.check_cypher_ratchet")


def test_ratchet_counts_cypher_outside_allowlist(tmp_path, ratchet_module):
    (tmp_path / "campy").mkdir()
    violating = tmp_path / "campy" / "not_migrated.py"
    violating.write_text(
        'db.execute("MATCH (n:Foo) RETURN n")\n'
        'db.execute("CREATE (n:Bar {id: $id})", {"id": "x"})\n'
    )

    cypher_total, raw_total, per_file = ratchet_module.scan(tmp_path)

    assert cypher_total == 2
    assert raw_total == 0
    assert per_file["campy/not_migrated.py"] == 2


def test_ratchet_skips_allowlisted_files(tmp_path, ratchet_module):
    (tmp_path / "campy" / "brain" / "hippocampus").mkdir(parents=True)
    schema_stub = tmp_path / "campy" / "brain" / "hippocampus" / "schema.py"
    schema_stub.write_text('db.execute("CREATE NODE TABLE Foo(id STRING, PRIMARY KEY(id))")\n')

    cypher_total, raw_total, per_file = ratchet_module.scan(tmp_path)

    assert cypher_total == 0
    assert per_file == {}


def test_ratchet_skips_named_query_registry_directory(tmp_path, ratchet_module):
    queries_dir = tmp_path / "campy" / "brain" / "hippocampus" / "graph" / "queries"
    queries_dir.mkdir(parents=True)
    (queries_dir / "widgets.py").write_text('cypher = "MATCH (n:Widget) RETURN n"\n')

    cypher_total, raw_total, per_file = ratchet_module.scan(tmp_path)

    assert cypher_total == 0


def test_ratchet_does_not_scan_tests_directory(tmp_path, ratchet_module):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_something.py").write_text('db.execute("MATCH (n) RETURN n")\n')

    cypher_total, raw_total, per_file = ratchet_module.scan(tmp_path)

    assert cypher_total == 0
    assert per_file == {}


def test_ratchet_counts_execute_raw_call_sites(tmp_path, ratchet_module):
    (tmp_path / "campy").mkdir()
    (tmp_path / "campy" / "some_tool.py").write_text(
        'await gateway.execute_raw("MATCH (n) RETURN n", mutating=False, reason="debt")\n'
        'await gateway.execute_raw("CREATE (n:X)", mutating=True, reason="debt")\n'
    )

    cypher_total, raw_total, per_file = ratchet_module.scan(tmp_path)

    assert raw_total == 2


def test_ratchet_main_exits_nonzero_when_cypher_increases(tmp_path, ratchet_module, monkeypatch, capsys):
    """AC: the ratchet script exits non-zero when a Cypher line is added
    to a non-allowlisted file (relative to the baseline)."""
    (tmp_path / "campy").mkdir()
    (tmp_path / "campy" / "regressed.py").write_text('db.execute("MATCH (n) RETURN n")\n')

    baseline_path = tmp_path / "cypher_baseline.json"
    baseline_path.write_text('{"cypher_lines": 0, "execute_raw_calls": 0}\n')

    monkeypatch.setattr(ratchet_module, "BASELINE_PATH", baseline_path)

    exit_code = ratchet_module.main(["--root", str(tmp_path)])

    assert exit_code != 0
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_ratchet_main_exits_zero_when_unchanged(tmp_path, ratchet_module, monkeypatch):
    (tmp_path / "campy").mkdir()
    (tmp_path / "campy" / "clean.py").write_text('print("no cypher here")\n')

    baseline_path = tmp_path / "cypher_baseline.json"
    baseline_path.write_text('{"cypher_lines": 0, "execute_raw_calls": 0}\n')
    monkeypatch.setattr(ratchet_module, "BASELINE_PATH", baseline_path)

    assert ratchet_module.main(["--root", str(tmp_path)]) == 0


def test_ratchet_main_update_rewrites_baseline(tmp_path, ratchet_module, monkeypatch):
    (tmp_path / "campy").mkdir()
    (tmp_path / "campy" / "some.py").write_text('db.execute("MATCH (n) RETURN n")\n')

    baseline_path = tmp_path / "cypher_baseline.json"
    baseline_path.write_text('{"cypher_lines": 99, "execute_raw_calls": 5}\n')
    monkeypatch.setattr(ratchet_module, "BASELINE_PATH", baseline_path)

    exit_code = ratchet_module.main(["--root", str(tmp_path), "--update"])

    assert exit_code == 0
    import json
    written = json.loads(baseline_path.read_text())
    assert written == {"cypher_lines": 1, "execute_raw_calls": 0}


def test_ratchet_exits_zero_on_the_current_tree(ratchet_module):
    """AC: ratchet script exits 0 on the current tree (real repo, real
    checked-in baseline)."""
    assert ratchet_module.main([]) == 0
