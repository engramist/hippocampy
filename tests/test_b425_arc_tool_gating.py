"""tests/test_b425_arc_tool_gating.py — B425 proof: arc_* tools are gateable.

Re-vet finding: 17 of 61 advertised tools are arc_* puzzle leftovers, ungated on
tools/list. They now default to exposed (the ARC client keeps working) but a
deployment can drop them via config["arc"]["expose_tools"] = False — off both
tools/list and the callable surface.
"""

from __future__ import annotations

import pytest

from campy.brain.auth import Principal, SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE
from campy.brain_daemon import arc_tools_exposed, route_tool_call, UnknownMethodError


def _principal():
    return Principal(
        subject_id="t", tenant_id="local", workspace_id="local",
        scopes=frozenset({SCOPE_MEMORY_READ, SCOPE_MEMORY_WRITE}),
        client="t", session_id=None, derived_from="t",
    )


def test_default_exposes_arc_tools():
    assert arc_tools_exposed(None) is True
    assert arc_tools_exposed({}) is True
    assert arc_tools_exposed({"arc": {}}) is True


def test_config_can_disable_arc_tools():
    assert arc_tools_exposed({"arc": {"expose_tools": False}}) is False


@pytest.mark.asyncio
async def test_disabled_arc_tool_is_rejected_as_unknown():
    with pytest.raises(UnknownMethodError):
        await route_tool_call(
            "arc_perceive_state", {}, db=None,
            config={"arc": {"expose_tools": False}}, principal=_principal(),
        )


@pytest.mark.asyncio
async def test_non_arc_tool_unaffected_by_arc_gate(monkeypatch):
    import campy.brain_daemon as bd
    called = {}

    async def _sentinel(params, db, config, **kw):
        called["yes"] = True
        return {"ok": True}

    monkeypatch.setitem(bd.TOOL_HANDLERS, "notify_turn", _sentinel)
    await route_tool_call("notify_turn", {}, db=None,
                          config={"arc": {"expose_tools": False}}, principal=_principal())
    assert called.get("yes") is True
