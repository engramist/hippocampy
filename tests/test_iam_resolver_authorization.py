from __future__ import annotations

import pytest

from campy.brain.auth import IAMConfigError, IAMPrincipalResolver, KNOWN_SCOPES, TransportContext


_TEST_ARN = "arn:aws:iam::123456789012:role/test"


async def _verifier(_headers):
    return _TEST_ARN


@pytest.mark.asyncio
async def test_workspace_map_cannot_be_overridden_by_header():
    resolver = IAMPrincipalResolver(
        workspace_id="ws-default",
        workspace_map={_TEST_ARN: "ws-mapped"},
        verifier=_verifier,
    )

    with pytest.raises(IAMConfigError, match="workspace header override rejected"):
        await resolver.resolve(
            TransportContext(
                transport="http",
                headers={"x-campy-workspace-id": "ws-attacker"},
            )
        )


@pytest.mark.asyncio
async def test_unmapped_caller_header_cannot_select_arbitrary_workspace():
    resolver = IAMPrincipalResolver(
        workspace_id="ws-default",
        verifier=_verifier,
    )

    with pytest.raises(IAMConfigError, match="requires explicit iam_workspace_map grant"):
        await resolver.resolve(
            TransportContext(
                transport="http",
                headers={"x-campy-workspace-id": "ws-attacker"},
            )
        )


@pytest.mark.asyncio
async def test_scope_tiering_can_deny_admin_scope():
    resolver = IAMPrincipalResolver(
        principal_scope_map={_TEST_ARN: ["memory.read"]},
        verifier=_verifier,
    )

    principal = await resolver.resolve(TransportContext(transport="http", headers={}))
    assert principal.workspace_id == "default"
    assert principal.scopes == frozenset({"memory.read"})
    with pytest.raises(PermissionError):
        principal.require("memory.admin")


@pytest.mark.asyncio
async def test_default_scopes_remain_unchanged_without_scope_map():
    resolver = IAMPrincipalResolver(verifier=_verifier)

    principal = await resolver.resolve(TransportContext(transport="http", headers={}))
    assert principal.scopes == KNOWN_SCOPES
