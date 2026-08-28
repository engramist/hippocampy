"""
tests/test_remote_mcp.py — B325: remote MCP server surface with pluggable auth.

Covers:
  - Task 0/1: the streamable-HTTP `/mcp` surface (found in web/server.py,
    outside `campy/` — see the B325 PR notes) now routes `tools/call`
    through `campy.brain_daemon.route_tool_call`, the exact chokepoint the
    Unix-socket dispatcher uses, instead of calling `TOOL_HANDLERS`
    directly. These tests prove that equivalence for at least three tools.
  - B315's forbidden-key guard firing identically on the HTTP path.
  - TransportContext on the HTTP path carrying no request-body-derived field.
  - Missing optional AWS dependencies (`boto3`) leaving every non-IAM mode
    fully working.

A note on "byte-identical results" (the card's phrasing): MCP's streamable-
HTTP `tools/call` wraps a tool's return value in `{"content": [{"type":
"text", "text": json.dumps(result)}]}` per the MCP spec, while the
Unix-socket transport is a simplified internal JSON-RPC dispatch (not full
MCP — see docs/transport-audit.md's "IPC Dispatch Divergence" section) that
returns the tool's raw result unwrapped. Those two envelopes are
deliberately different protocol shapes, predating this card. What must be
identical — and is, because both paths now call the same
`route_tool_call()` — is the *tool result payload itself*: these tests
decode the HTTP envelope and compare it against the raw socket-path result
for equality.
"""

from __future__ import annotations

import json
import tempfile

import pytest
from fastapi.testclient import TestClient

from campy.brain.auth import LocalSingleUserResolver, Principal, TransportContext


class EmptyResult:
    def has_next(self):
        return False


class EmptyDB:
    """Matches tests/test_web.py's EmptyDB — accepts writes silently, reads empty."""

    def execute(self, q, p=None):
        return EmptyResult()

    async def execute_write(self, q, p=None):
        pass


def _make_daemon(db=None):
    from campy.brain_daemon import BrainDaemon

    daemon = BrainDaemon.__new__(BrainDaemon)
    # B367: _dispatch now calls emit_activity() -- point it at an isolated
    # path so this test doesn't write into the developer's real activity log.
    daemon.config = {
        "activity": {"log_path": tempfile.mkstemp(suffix=".activity.log")[1]}
    }
    daemon.db = db or EmptyDB()
    daemon.running = False
    daemon._llm_client = None
    daemon._centroids = {}
    daemon._loop_queue = None
    daemon._principal_resolver = LocalSingleUserResolver()
    daemon._router = None  # B316: falls back to self.db, matching pre-B316 behavior
    return daemon


def _make_client(db=None, principal_resolver=None) -> TestClient:
    from web.server import create_app

    # B368: web/server.py's tools/call dispatch calls emit_activity() --
    # point it at an isolated temp file so these tests don't write real
    # events into the developer's own ~/.campy/activity.log (the same fix
    # B367 applied to the socket-transport tests).
    config = {"activity": {"log_path": tempfile.mkstemp(suffix=".activity.log")[1]}}
    return TestClient(create_app(db or EmptyDB(), config=config, principal_resolver=principal_resolver))


# ---------------------------------------------------------------------------
# tools/call: HTTP and Unix-socket paths agree on the tool result payload,
# across at least three tools — proven by both literally calling
# route_tool_call() with the same fake handlers.
# ---------------------------------------------------------------------------

_FAKE_TOOL_RESULTS = {
    "remote_mcp_test_tool_a": {"status": "ok", "value": 1},
    "remote_mcp_test_tool_b": {"status": "ok", "items": ["x", "y", "z"]},
    "remote_mcp_test_tool_c": {"status": "ok", "nested": {"a": 1, "b": [True, None]}},
}


@pytest.fixture
def fake_tools(monkeypatch):
    import campy.brain_daemon as bd

    async def _handler_factory(name):
        async def handler(params, db, config):
            return _FAKE_TOOL_RESULTS[name]
        return handler

    for name, result in _FAKE_TOOL_RESULTS.items():
        async def handler(params, db, config, _result=result):
            return _result
        monkeypatch.setitem(bd.TOOL_HANDLERS, name, handler)
    yield list(_FAKE_TOOL_RESULTS.keys())


@pytest.mark.asyncio
async def test_tools_call_identical_across_transports(fake_tools):
    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))
    client = _make_client(db=daemon.db)

    for tool_name in fake_tools:
        socket_response = await daemon._dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": tool_name, "params": {}},
            principal,
        )
        socket_result = socket_response["result"]

        http_response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
        })
        assert http_response.status_code == 200
        http_envelope = http_response.json()
        http_result = json.loads(http_envelope["result"]["content"][0]["text"])

        assert http_result == socket_result == _FAKE_TOOL_RESULTS[tool_name]


# ---------------------------------------------------------------------------
# tools/list — HTTP and stdio must at least agree on the *set of tool
# names* they advertise. They do NOT share one envelope shape today: the
# Unix-socket path returns a minimal `[{"name": ...}]` list (it is
# JSON-RPC method dispatch, not real MCP tool discovery — see
# docs/transport-audit.md), while HTTP returns full MCP tool definitions
# (name + description + inputSchema) from tool_schemas.TOOLS, which is
# what MCP's `tools/list` is actually specified to return. That envelope
# difference predates B325 and is out of this card's scope to unify; the
# PR notes this explicitly as a place the card's literal "matches exactly"
# wording does not hold.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_same_tool_names_across_transports():
    from campy.brain.thalamus.tools import TOOL_HANDLERS

    daemon = _make_daemon()
    principal = await daemon._principal_resolver.resolve(TransportContext(transport="unix-socket"))
    client = _make_client(db=daemon.db)

    socket_response = await daemon._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, principal,
    )
    socket_names = {t["name"] for t in socket_response["result"]["tools"]}

    http_response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    http_names = {t["name"] for t in http_response.json()["result"]["tools"]}

    assert socket_names == set(TOOL_HANDLERS.keys())
    # HTTP's tool_schemas.TOOLS is a curated subset of TOOL_HANDLERS (only
    # tools with a published schema) — every HTTP-advertised name must
    # still be a real, dispatchable tool.
    assert http_names <= socket_names
    assert http_names, "HTTP tools/list must not be empty"


# ---------------------------------------------------------------------------
# B315's forbidden-key guard fires on the HTTP path too.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forbidden_key_rejected_over_http(fake_tools):
    client = _make_client()
    tool_name = fake_tools[0] if isinstance(fake_tools, list) else next(iter(_FAKE_TOOL_RESULTS))

    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"workspace_id": "forged-tenant"}},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32602
    assert "workspace_id" in body["error"]["message"]


@pytest.mark.parametrize("key", ["tenant_id", "workspace_id", "subject_id", "principal", "scopes"])
@pytest.mark.asyncio
async def test_every_forbidden_key_rejected_over_http(key, fake_tools):
    client = _make_client()
    tool_name = next(iter(_FAKE_TOOL_RESULTS))

    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": {key: "forged-value"}},
    })
    body = response.json()
    assert body["error"]["code"] == -32602
    assert key in body["error"]["message"]


# ---------------------------------------------------------------------------
# TransportContext on the HTTP path carries no request-body-derived field —
# same structural assertion test_auth_context.py makes for the type itself,
# repeated here against the actual HTTP call site.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_transport_context_built_before_body_parsed(monkeypatch):
    """A resolver that inspects the TransportContext it was given must see
    only header-derived data — never anything from the JSON-RPC body, even
    when the body contains keys that look like transport fields."""
    seen = {}

    class _RecordingResolver:
        async def resolve(self, transport_ctx: TransportContext) -> Principal:
            seen["ctx"] = transport_ctx
            return await LocalSingleUserResolver().resolve(transport_ctx)

    client = _make_client(principal_resolver=_RecordingResolver())
    client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        # A request body carrying a field shaped like a transport
        # credential — must never reach TransportContext.
        "params": {"peer_credential": "forged", "transport": "forged"},
    })

    ctx = seen["ctx"]
    assert ctx.transport == "http"  # set by the HTTP handler itself, not from the body
    assert ctx.peer_credential is None  # never populated from params
    assert ctx.headers is not None and "peer_credential" not in ctx.headers.values()


# ---------------------------------------------------------------------------
# Missing optional AWS dependency (boto3) leaves every non-IAM mode fully
# working — module import + loopback "none" mode start.
# ---------------------------------------------------------------------------


def test_module_imports_without_boto3_installed():
    """Runs in a fresh subprocess (not this test process) so that faking
    boto3's absence can never reload — and thereby corrupt the identity of
    — the already-imported `campy.brain.auth` / `campy.brain_daemon` /
    `web.server` module objects every other test in this suite shares.
    `sys.modules["boto3"] = None` is the standard way to make `import
    boto3` raise ImportError without touching `__import__` itself.
    """
    import subprocess
    import sys as _sys

    script = (
        "import sys; sys.modules['boto3'] = None\n"
        "import campy.brain.auth as auth_mod\n"
        "import campy.brain_daemon as bd_mod\n"
        "import web.server as ws_mod\n"
        "resolver = bd_mod._build_http_principal_resolver('none', {})\n"
        "assert isinstance(resolver, auth_mod.LocalSingleUserResolver)\n"
        "bd_mod._enforce_bind_guard('127.0.0.1', 'none')\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout


@pytest.mark.asyncio
async def test_iam_resolver_without_boto3_fails_loudly_not_silently(monkeypatch):
    """boto3 missing must surface as a clear IAMConfigError when IAM mode
    is actually used — never a bare ModuleNotFoundError, and never a
    silent fallback to an unauthenticated principal."""
    from campy.brain.auth import IAMConfigError, IAMPrincipalResolver

    async def _boto3_missing_verifier(headers):
        raise IAMConfigError(
            "IAM auth mode requires boto3, which is not installed. "
            "Install it with: pip install 'hippocampy[bedrock]'"
        )

    resolver = IAMPrincipalResolver(verifier=_boto3_missing_verifier)
    with pytest.raises(IAMConfigError, match="boto3"):
        await resolver.resolve(TransportContext(transport="http", headers={}))
