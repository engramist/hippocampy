"""tests/test_b424_scope_enforcement.py — B424 proof.

External re-vet (2026-09-11) HIGH finding: `auth.py` defines
`memory.read/write/admin` scopes but `route_tool_call` never consulted them —
any authenticated principal had full write. This enforces tool→scope at the
shared dispatch chokepoint, fail-safe: a method NOT in the read-only allowlist
requires `memory.write`, so a new/unclassified tool can only over-restrict a
read, never silently expose a write.
"""

from __future__ import annotations

import pytest

from campy.brain.auth import (
    Principal,
    SCOPE_MEMORY_READ,
    SCOPE_MEMORY_WRITE,
    READ_ONLY_METHODS,
    required_scope_for,
)
from campy.brain_daemon import route_tool_call
from campy.brain.thalamus.tools import TOOL_HANDLERS


def _principal(*scopes: str) -> Principal:
    return Principal(
        subject_id="test", tenant_id="local", workspace_id="local",
        scopes=frozenset(scopes), client="test", session_id=None,
        derived_from="test",
    )


def test_required_scope_classification():
    assert required_scope_for("current_truth") == SCOPE_MEMORY_READ
    assert required_scope_for("recall_relevant_lessons") == SCOPE_MEMORY_READ
    assert required_scope_for("notify_turn") == SCOPE_MEMORY_WRITE
    assert required_scope_for("upsert_lesson") == SCOPE_MEMORY_WRITE
    # Fail-safe: an unknown/unclassified method requires write, never read.
    assert required_scope_for("some_new_unclassified_tool") == SCOPE_MEMORY_WRITE


def test_every_registered_tool_is_classified_and_allowlist_is_real():
    # No crash for any real tool; allowlist has no stale/typo entries.
    for method in TOOL_HANDLERS:
        assert required_scope_for(method) in (SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE)
    assert READ_ONLY_METHODS <= set(TOOL_HANDLERS), (
        f"READ_ONLY_METHODS has entries that are not registered tools: "
        f"{READ_ONLY_METHODS - set(TOOL_HANDLERS)}"
    )


@pytest.mark.asyncio
async def test_read_only_principal_denied_write_tool_before_dispatch():
    """A read-only principal calling a write tool is rejected BEFORE the handler
    runs (db is None — if dispatch were reached it would blow up differently)."""
    with pytest.raises(PermissionError):
        await route_tool_call("notify_turn", {}, db=None, config={},
                              principal=_principal(SCOPE_MEMORY_READ))


@pytest.mark.asyncio
async def test_write_principal_passes_scope_gate_for_write_tool(monkeypatch):
    """A principal with memory.write clears the gate — proven by swapping in a
    sentinel handler so we don't need a live DB."""
    called = {}

    async def _sentinel(params, db, config, **kw):
        called["yes"] = True
        return {"ok": True}

    monkeypatch.setitem(TOOL_HANDLERS, "notify_turn", _sentinel)
    await route_tool_call("notify_turn", {}, db=None, config={},
                          principal=_principal(SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE))
    assert called.get("yes") is True
