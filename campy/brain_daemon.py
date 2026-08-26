"""
brain_daemon.py — HippoCampy Daemon

Entry point. On startup:
  1. Load campy.toml
  2. Pre-warm sentence-transformers model
  3. Initialize Kùzu schema (idempotent)
  4. Load gist centroids + schema.org routing table
  5. Initialize LLM client (Ollama default; degrades gracefully if unavailable)
  6. Start Loop worker asyncio task (Gated Consolidation Loop, M3+)
  7. Start Unix domain socket IPC server (JSON-RPC 2.0)
  8. Start background sweep asyncio task

IPC: JSON-RPC 2.0 over the active Campy runtime socket.
Concurrency: single asyncio event loop, asyncio.Lock for all Kùzu writes.
"""

import asyncio
import inspect
import json
import logging
import os
import random
import signal
import socket
from pathlib import Path

_logger = logging.getLogger(__name__)

import uvicorn

from campy.brain.auth import (
    FORBIDDEN_PARAM_KEYS,
    IAMPrincipalResolver,
    LocalSingleUserResolver,
    Principal,
    TransportContext,
)
from campy.brain.brainstem.config import load_config
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.hippocampus.graph.router import WorkspaceRouter
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools import TOOL_HANDLERS, init_loop_queue
from campy.brain.llm.provider import create_llm_client
from campy.brain.temporal_lobe.loop import step2_gist, step3_schema_org
from campy.brain.temporal_lobe.loop.orchestrator import run_loop
from campy.brain.brainstem.sweep import run_sweep
from campy.paths import get_daemon_socket_path, get_database_path, get_workspace_root

SOCKET_PATH = get_daemon_socket_path()
DB_PATH     = get_database_path()
# D3 fix: package-relative seed path — GistSeedExamples.md lives alongside
# the repo, not in a hardcoded OneDrive path that only works on DJ's machine.
SEED_PATH   = Path(__file__).parent / "InvertorsDocs" / "GistSeedExamples.md"

# B315 Task 3 — incremental adoption via signature inspection. Computed once
# at import rather than per-dispatch: a handler "wants" a principal if its
# real signature (see _shared.py::_with_phase's `__wrapped__` note — most
# TOOL_HANDLERS entries are wrapped, and inspect.signature() follows
# `__wrapped__` to the underlying function automatically) declares a
# `principal` parameter. This is a deliberate tradeoff: slightly implicit,
# in exchange for not rewriting ~40 handler signatures in one commit. The
# end state is mandatory — scripts/check_principal_ratchet.py drives the
# non-adopting count to zero, at which point this inspection branch and the
# `principal` default go away and the parameter becomes required on every
# handler.
_WANTS_PRINCIPAL = {
    name for name, fn in TOOL_HANDLERS.items()
    if "principal" in inspect.signature(fn).parameters
}

# B315 Task 5 — forbidden-key guard. Re-exported from campy.brain.auth (the
# canonical set) under the name the card's pseudocode uses at the call site.
_FORBIDDEN_PARAM_KEYS = FORBIDDEN_PARAM_KEYS


class ForbiddenParamError(Exception):
    """Raised by `route_tool_call` when `params` contains a B315 forbidden key."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Invalid params: {key!r} must not be supplied by the caller")


class UnknownMethodError(Exception):
    """Raised by `route_tool_call` when `method` is not a registered tool."""

    def __init__(self, method: str):
        self.method = method
        super().__init__(f"Unknown method: {method}")


async def route_tool_call(method: str, params: dict, db, config: dict, principal: Principal):
    """Shared chokepoint for invoking a `TOOL_HANDLERS` entry.

    B325: used by BOTH the Unix-socket JSON-RPC dispatcher (`_dispatch`,
    below) and the streamable-HTTP MCP transport
    (`web/server.py::_dispatch_mcp`) — see docs/transport-audit.md's
    "IPC Dispatch Divergence" section, which this function exists to
    close. Applies B315's forbidden-key guard and Task 3's
    principal-threading convention identically on every transport, so
    principal derivation, the forbidden-key guard, and (B316) workspace
    routing cannot drift between transports the way the two dispatch
    paths already had before this card.

    Raises `ForbiddenParamError` if `params` contains a B315 forbidden
    key, `UnknownMethodError` if `method` is not registered. Any exception
    a handler itself raises propagates unchanged — callers translate both
    into their own transport's error envelope.
    """
    if isinstance(params, dict):
        offending = _FORBIDDEN_PARAM_KEYS & params.keys()
        if offending:
            offending_key = sorted(offending)[0]
            _logger.warning(
                "Rejected request: forbidden param key %r (method=%s, subject_id=%s)",
                offending_key, method, principal.subject_id,
            )
            raise ForbiddenParamError(offending_key)

    handler = TOOL_HANDLERS.get(method)
    if not handler:
        raise UnknownMethodError(method)

    if method in _WANTS_PRINCIPAL:
        return await handler(params, db, config, principal=principal)
    return await handler(params, db, config)


def _socket_path() -> Path:
    """Return the daemon socket path, allowing sandbox-safe overrides."""
    configured = (
        os.environ.get("SIDEQUESTS_BRAIN_SOCKET")
        or os.environ.get("SIDEQUESTS_SOCKET_PATH")
        or os.environ.get("CAMPY_BRAIN_SOCKET")
        or os.environ.get("CAMPY_SOCKET_PATH")
    )
    if configured:
        return Path(configured).expanduser()
    return SOCKET_PATH


# B325 Task 2 — bind address as explicit, guarded configuration.
#
# Loopback addresses a bind_host is allowed to sit on without any auth
# resolver configured. Kept as a positive allowlist (rather than checking
# for specific non-loopback literals) so the guard below is correct for
# every non-loopback address there is, not just the handful anyone thought
# to list — see the module-level comment in tests/test_bind_guard.py for
# why a blocklist of "known-bad" hosts is the wrong shape for this check.
_LOOPBACK_BIND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class BindGuardError(RuntimeError):
    """Raised at startup when the configured bind address would expose
    Campy's memory surface without authentication.

    This must be a HARD STARTUP FAILURE — refuse to listen, not warn —
    because Campy stores a customer's accumulated memory, and exposing it
    on a non-loopback interface without auth is a one-environment-variable
    mistake away from a serious breach. Raised synchronously from
    `BrainDaemon.start()`, before any socket or web server task is
    created, so the process never binds anything: an uncaught exception
    here propagates out of `main()` and exits the process instead of being
    logged-and-retried by the background-task restart machinery (which
    would turn a misconfiguration into a crash loop, not a hard failure).
    """


def _enforce_bind_guard(bind_host: str, auth_mode: str) -> None:
    """B325's single most important check: binding to any non-loopback
    address while no auth resolver is configured (`auth = "none"`) is a
    hard startup failure. Loopback + "none" (today's only supported local
    configuration) and non-loopback + a real auth mode ("iam"/"oidc") are
    both fine — this only rejects the one combination that would expose
    unauthenticated memory to the network.
    """
    if bind_host not in _LOOPBACK_BIND_HOSTS and auth_mode == "none":
        raise BindGuardError(
            f"Refusing to start: [server].bind_host={bind_host!r} is not "
            f"loopback ({sorted(_LOOPBACK_BIND_HOSTS)}) and [server].auth="
            f"{auth_mode!r}. Configure [server].auth to \"iam\" or \"oidc\" "
            "before binding to a non-loopback address, or leave bind_host "
            "on loopback for local-only use."
        )


def _build_http_principal_resolver(auth_mode: str, server_cfg: dict):
    """B325 Task 2/3 — the PrincipalResolver the streamable-HTTP transport
    uses, chosen from `[server].auth`. Mirrors `_enforce_bind_guard`'s
    view of the same config: "none" is only ever reachable on loopback (the
    guard already enforced that), so it is safe to reuse the same
    all-scopes local Principal the Unix socket uses. "iam" builds a real
    `IAMPrincipalResolver` (B325 Task 3). "oidc" is accepted as
    configuration (per the card) but has no resolver yet — fail loudly at
    startup rather than silently falling back to an unauthenticated mode.
    """
    if auth_mode == "none":
        return LocalSingleUserResolver()
    if auth_mode == "iam":
        return IAMPrincipalResolver(
            tenant_id=server_cfg.get("iam_tenant_id", "default"),
            workspace_id=server_cfg.get("iam_workspace_id", "default"),
            workspace_map=server_cfg.get("iam_workspace_map"),
            tenant_map=server_cfg.get("iam_tenant_map"),
            principal_scope_map=server_cfg.get("iam_principal_scope_map"),
            default_scopes=server_cfg.get("iam_default_scopes"),
        )
    if auth_mode == "oidc":
        raise BindGuardError(
            "[server].auth = \"oidc\" is accepted as configuration but no "
            "OIDC resolver is implemented yet (B325 follow-up card) — use "
            "\"iam\", or \"none\" on a loopback bind_host."
        )
    raise BindGuardError(f"[server].auth={auth_mode!r} is not a recognized auth mode")


class BrainDaemon:

    def __init__(self, config: dict):
        self.config      = config
        self.db          = KuzuClient(str(DB_PATH))
        self.running     = False
        self._llm_client = None   # set in start()
        self._centroids  = {}     # set in start()
        self._loop_queue: asyncio.Queue = asyncio.Queue()
        self._stale_projects: set[str] = set()
        self._last_file_regen: str | None = None
        # B315: local Campy is single-tenant cloud with auth stubbed — this
        # resolver always returns a real Principal (tenant "local",
        # workspace "local", every known scope), never None. Cloud
        # resolvers (OIDC/IAM) implement the same PrincipalResolver
        # Protocol; see campy/brain/auth.py and B325's IAMPrincipalResolver.
        self._principal_resolver = LocalSingleUserResolver()
        # B325: set for real in start() from [server].auth, once the bind
        # guard has passed. None until then — _start_web_server always
        # runs after start()'s guard check, so this is never used unset.
        self._http_principal_resolver = None
        # B316: constructed in start(), once the seed path / embedding
        # model needed by schema_init are known. None until then — code
        # that might run before start() (tests constructing BrainDaemon
        # directly) falls back to self.db, matching pre-B316 behavior.
        self._router: WorkspaceRouter | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self):
        print("HippoCampy daemon starting...")

        # B325 Task 2 — bind guard, checked synchronously before anything
        # else starts. A misconfigured [server] block must be a hard
        # startup failure: raising here propagates out of main() and exits
        # the process, rather than surfacing as a background-task crash
        # that _restart_on_failure would just retry forever. Nothing is
        # bound — no IPC socket, no web/MCP server — if this raises.
        server_cfg = self.config.get("server", {})
        bind_host = server_cfg.get("bind_host", "127.0.0.1")
        auth_mode = server_cfg.get("auth", "none")
        _enforce_bind_guard(bind_host, auth_mode)
        self._http_principal_resolver = _build_http_principal_resolver(auth_mode, server_cfg)
        # Log the effective bind address and auth mode every time, so an
        # operator never has to guess whether the daemon is exposed.
        print(f"[server] bind_host={bind_host} auth={auth_mode}")

        # Configure embedding provider dispatch (sentence-transformers | ollama | openai)
        emb.configure(self.config)

        # Pre-warm embedder
        embedding_model = self.config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        print(f"Pre-warming embedder: {embedding_model}")
        emb.prewarm(embedding_model)

        # Initialize Kùzu schema (idempotent)
        seed_path = self._resolve_seed_path()
        init_schema(self.db, str(seed_path), embedding_model)

        # B316: WorkspaceRouter, rooted at the parent of the existing
        # DB_PATH — the same directory the pre-B316 single database has
        # always lived in. `local_db_path=DB_PATH` is what makes the
        # "local" workspace resolve to the pre-existing path with no
        # migration (see router.py's LOCAL_WORKSPACE_ID special case).
        # register("local", self.db) wires in the *already-open* client
        # from __init__ rather than letting get("local") open a second
        # kuzu.Database handle on the identical directory — Kùzu is
        # single-process-writer, so two live handles on one path is a
        # hazard, not just waste. schema_init is a thin async wrapper
        # around the same synchronous init_schema() just called above for
        # self.db, run in a thread so it doesn't block the event loop for
        # a newly-created workspace's first access.
        async def _schema_init_for_router(client: KuzuClient) -> None:
            await asyncio.to_thread(init_schema, client, str(seed_path), embedding_model)

        self._router = WorkspaceRouter(
            get_workspace_root(), schema_init=_schema_init_for_router, local_db_path=DB_PATH,
        )
        self._router.register("local", self.db)

        # Load gist centroids (needed by Step 2 System 1 classifier)
        self._centroids = step2_gist.load_centroids(self.db)
        print(f"Loaded {len(self._centroids)} gist centroids.")

        # Load schema.org routing table into module cache (needed by Step 3)
        step3_schema_org.load_routing_table(self.db)
        print("Loaded schema.org routing table.")

        # Initialize LLM client (degrades gracefully to System 1 if unavailable)
        self._llm_client = create_llm_client(self.config)
        if self._llm_client:
            print(f"LLM provider ready: {self.config.get('llm', {}).get('provider', 'ollama')}")
        else:
            print("LLM provider unavailable. Loop running in System 1 (embedding) only mode.")

        # Wire loop queue into tools module
        init_loop_queue(self._loop_queue)

        # D2 fix: attach done callbacks so task crashes are logged and the task
        # is restarted rather than silently dying.
        def _restart_on_failure(task: asyncio.Task, coro_factory, *args):
            exc = task.exception() if not task.cancelled() else None
            if exc:
                _logger.exception(
                    "Background task '%s' died unexpectedly — restarting",
                    task.get_name(), exc_info=exc,
                )
                new_task = asyncio.create_task(coro_factory(*args),
                                               name=task.get_name())
                new_task.add_done_callback(
                    lambda t: _restart_on_failure(t, coro_factory, *args)
                )

        # Start Loop worker (Gated Consolidation Loop, M3)
        loop_task = asyncio.create_task(self._loop_worker(), name="loop_worker")
        loop_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._loop_worker)
        )

        # Start background sweep
        sweep_interval = self.config.get("pruning", {}).get("sweep_interval_seconds", 300)
        sweep_task = asyncio.create_task(
            self._background_sweep(sweep_interval), name="background_sweep"
        )
        sweep_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._background_sweep, sweep_interval)
        )

        # B342/B365: Start periodic self-restart task (allocator fragmentation
        # mitigation). See _periodic_restart for why this exists. Ported from
        # the root brain_daemon.py, which never shipped -- see B365.
        restart_interval_hours = self.config.get("daemon", {}).get("restart_interval_hours", 24)
        if restart_interval_hours > 0:
            restart_task = asyncio.create_task(
                self._periodic_restart(restart_interval_hours), name="periodic_restart"
            )
            restart_task.add_done_callback(
                lambda t: _restart_on_failure(t, self._periodic_restart, restart_interval_hours)
            )

        # Start Memory Control Panel web server (M7)
        web_port = self.config.get("web", {}).get("port", 7799)
        web_task = asyncio.create_task(
            self._start_web_server(web_port), name="web_server"
        )
        web_task.add_done_callback(
            lambda t: _restart_on_failure(t, self._start_web_server, web_port)
        )

        # Start IPC server
        await self._run_ipc_server()

    def _resolve_seed_path(self) -> Path:
        """Find GistSeedExamples.md — check config path dir first, then default."""
        config_dir = Path(self.config.get("_config_path", "campy.toml")).parent
        candidates = [
            config_dir.parent / "InvertorsDocs" / "GistSeedExamples.md",
            SEED_PATH,
            # Installed mode: bundled in campy/data/
            Path(__file__).parent / "data" / "GistSeedExamples.md",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "GistSeedExamples.md not found. Expected alongside campy.toml."
        )

    # ------------------------------------------------------------------
    # IPC Server (JSON-RPC 2.0 over Unix domain socket)
    # ------------------------------------------------------------------

    async def _run_ipc_server(self):
        socket_path = _socket_path()
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Clean up stale socket from previous crash
        if socket_path.exists():
            socket_path.unlink()

        # 4 MB limit — notify_turn payloads can be large (full assistant responses)
        server = await asyncio.start_unix_server(
            self._handle_connection, path=str(socket_path),
            limit=4 * 1024 * 1024,
        )
        self.running = True
        print(f"Brain Daemon listening on {socket_path}")

        async with server:
            await server.serve_forever()

    def _peer_credential(self, writer: asyncio.StreamWriter) -> str | None:
        """Best-effort opaque peer identity for the Unix socket transport.

        A local Unix socket carries no cryptographic identity — filesystem
        permissions on the socket path are the access control, same as
        before this card. This exists so TransportContext always has
        *something* transport-derived to carry, and so the remote HTTP
        transport (B325) has an obvious analogous slot to fill with a
        verified SigV4/OIDC identity instead of a guess.
        """
        try:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                return f"unix:{sock.fileno()}"
        except Exception:
            pass
        return None

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle a single adapter connection. Reads newline-delimited JSON-RPC 2.0.

        B362: an abrupt client disconnect (the adapter's own call-level
        timeout expiring, then it gives up and closes its socket) is an
        ordinary occurrence, not a daemon fault -- ConnectionResetError/
        BrokenPipeError from writing into that closed socket must not
        propagate as an unhandled exception in client_connected_cb.
        """
        # B315: TransportContext is built from what this connection itself
        # knows — BEFORE any request line is read, let alone parsed — and
        # the Principal resolved from it is reused for every JSON-RPC
        # request that arrives on this connection. This ordering is
        # structural, not stylistic: if a TransportContext were ever built
        # from `request` or `request["params"]`, an agent could forge its
        # own tenant/workspace identity from the request body — exactly the
        # confused-deputy hole this card exists to close. Do not move this
        # below the read loop, and do not add a TransportContext field that
        # comes from anything but the transport connection itself.
        transport_ctx = TransportContext(
            transport="unix-socket",
            peer_credential=self._peer_credential(writer),
        )
        principal = await self._principal_resolver.resolve(transport_ctx)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line)
                    response = await self._dispatch(request, principal)
                except json.JSONDecodeError:
                    response = {
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}
                    }
                try:
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    _logger.debug("Client disconnected before response could be written")
                    break
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                pass

    async def _dispatch(self, request: dict, principal: Principal) -> dict:
        """Route JSON-RPC method calls to tool handlers in campy/brain/thalamus/tools.py.

        `principal` is resolved once per connection from the transport
        credential (see `_handle_connection`) and passed to every handler
        that opted in via Task 3's signature-inspection adoption
        (`_WANTS_PRINCIPAL`, computed at import time above). It is never
        derived from `request` or `params` here. The actual guard +
        handler invocation lives in the module-level `route_tool_call()`
        so the streamable-HTTP transport (B325,
        `web/server.py::_dispatch_mcp`) shares this exact behavior instead
        of reimplementing it — see that function's docstring.
        """
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        # MCP protocol introspection methods
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"protocolVersion": "2024-11-05",
                               "serverInfo": {"name": "campy-daemon", "version": "0.1.0"},
                               "capabilities": {"tools": {}}}}
        if method == "tools/list":
            tools = [{"name": name} for name in TOOL_HANDLERS]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        # B316: resolve this request's database from the router, keyed on
        # the transport-derived principal.workspace_id — never from
        # `params` (B315's rule, unchanged). Falls back to `self.db` when
        # no router exists yet (a BrainDaemon constructed directly, e.g.
        # in a test, without calling start()), matching pre-B316 behavior.
        try:
            db = await self._resolve_workspace_db(principal.workspace_id)
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid workspace: {e}"}}

        try:
            result = await route_tool_call(method, params, db, self.config, principal)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except ForbiddenParamError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": str(e)}}
        except UnknownMethodError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": str(e)}}
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }
        finally:
            self._release_workspace_db(principal.workspace_id)

    async def _resolve_workspace_db(self, workspace_id: str) -> KuzuClient:
        """B316: the router-backed replacement for always using `self.db`.
        Raises ValueError for a workspace_id `WorkspaceRouter._workspace_dir`
        rejects (invalid shape, traversal attempt) — translated to a
        JSON-RPC -32602 by the one caller, `_dispatch`."""
        if self._router is None:
            return self.db
        return await self._router.get(workspace_id)

    def _release_workspace_db(self, workspace_id: str) -> None:
        if self._router is not None:
            self._router.release(workspace_id)

    # ------------------------------------------------------------------
    # Gated Consolidation Loop worker (M3)
    # ------------------------------------------------------------------

    async def _loop_worker(self):
        """
        Reads (message_id, text, role, session_id) tuples from the queue and
        runs the Gated Consolidation Loop on each. Runs as a background task.
        """
        print("Loop worker started.")
        while True:
            # B14: Added session_id to queue tuple
            message_id, text, role, session_id = await self._loop_queue.get()
            try:
                print(f"[Loop] Processing ({role}): {text[:120]!r}")
                summary = await run_loop(
                    message_id=message_id,
                    text=text,
                    role=role,
                    db=self.db,
                    llm_client=self._llm_client,
                    config=self.config,
                    centroids=self._centroids,
                    session_id=session_id,
                )
                print(
                    f"[Loop] msg={message_id[:8]} "
                    f"entities={summary['entities_found']} "
                    f"concepts={summary['concepts_stored']} "
                    f"relations={summary['relations_found']} "
                    f"noise={summary['noise_count']} "
                    f"triggers={summary.get('triggers_bound', 0)}"
                )

                # B14: Persist loop summary to Session node
                if summary and session_id != "unknown":
                    try:
                        await self.db.execute_write(
                            "MATCH (s:Session {session_id: $sid}) "
                            "SET s.last_loop_summary = $summary",
                            {"sid": session_id, "summary": json.dumps(summary)}
                        )
                    except Exception:
                        pass  # Non-critical

            except Exception as e:
                print(f"[Loop] Error processing message {message_id}: {e}")
            finally:
                self._loop_queue.task_done()

    # ------------------------------------------------------------------
    # Memory Control Panel web server (M7)
    # ------------------------------------------------------------------

    async def _start_web_server(self, port: int):
        """
        Start the FastAPI Memory Control Panel + streamable-HTTP MCP
        surface (B325). Runs as a background asyncio task alongside the
        IPC server.

        B325: bind address is `[server].bind_host`, defaulting to
        127.0.0.1 — an existing local install sees no change. The bind
        guard already ran synchronously in `start()` before this task was
        ever created (see `_enforce_bind_guard`), so by the time this
        method runs, binding here is known to be safe for the configured
        auth mode.
        """
        server_cfg = self.config.get("server", {})
        bind_host = server_cfg.get("bind_host", "127.0.0.1")

        from web.server import create_app
        app = create_app(
            self.db, self.config,
            principal_resolver=self._http_principal_resolver,
            router=self._router,
        )
        config = uvicorn.Config(
            app,
            host=bind_host,
            port=port,
            log_level="error",
        )
        server = uvicorn.Server(config)
        print(f"Memory Control Panel + MCP: http://{bind_host}:{port}")
        await server.serve()

    # ------------------------------------------------------------------
    # Background sweep — Synaptic Pruning + Hebbian Trigger 2
    # ------------------------------------------------------------------

    async def _background_sweep(self, interval_seconds: int):
        """
        Periodic sweep: pathway decay, archive, resurrection, Hebbian Trigger 2.
        Runs per-table to keep write-lock windows short.
        First run is deferred by one full interval to let the daemon warm up.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                summary = await run_sweep(
                    db=self.db,
                    config=self.config,
                    llm_client=self._llm_client,
                )
                print(
                    f"[Sweep] decayed={summary['decayed']} "
                    f"archived={summary['archived']} "
                    f"resurrected={summary['resurrected']} "
                    f"promoted={summary['promoted']} "
                    f"centroids={summary.get('centroids_updated', 0)} "
                    f"patterns={summary.get('patterns_discovered', 0)} "
                    f"errors={summary['errors']}"
                )
            except Exception as e:
                print(f"[Sweep] Error during sweep: {e}")

            # File Bridge: regenerate stale project files
            await self._file_bridge_regen()

            # Associative Hooks: recompile trigger manifest
            await self._compile_trigger_manifest()

    async def _periodic_restart(self, interval_hours: float):
        """
        B342: periodic self-restart to bound allocator fragmentation.

        B342's investigation found the daemon's physical memory footprint
        (resident + swapped, not just RSS) grows slowly but with no observed
        plateau across a 2-hour, 1200-cycle stress run -- consistent with
        small-object allocator fragmentation (macOS libmalloc not returning
        partially-used regions to the OS) rather than a Python-level leak
        (gc object counts stay flat). Extrapolating the observed rate, the
        original incident (5.4GB RSS / 99GB physical footprint, 94.5GB
        swapped, on a near-empty graph) would need on the order of a week
        of continuous uptime to develop.

        Same pattern gunicorn/uWSGI use for exactly this failure mode
        (`max_requests` worker recycling) -- a time-based version here since
        this daemon's load isn't request-counted the same way. KuzuDB is the
        durable source of truth (see CLAUDE.md's "No Shadow Stores" rule),
        so a clean restart loses no real state; `self.shutdown()` closes the
        db (final checkpoint) and stops the socket before exiting, and
        launchd's KeepAlive brings up a fresh process immediately.

        24h default is roughly an order of magnitude inside the observed
        danger zone. Small random jitter (+/-10%) avoids the restart always
        landing at the same wall-clock offset relative to other periodic
        maintenance (background sweep, checkpoint). Set
        `[daemon] restart_interval_hours = 0` to disable.
        """
        jitter = random.uniform(0.9, 1.1)
        delay_seconds = interval_hours * 3600 * jitter
        await asyncio.sleep(delay_seconds)
        _logger.info(
            "[Restart] Scheduled self-restart after %.1fh uptime (B342 fragmentation "
            "mitigation) -- launchd KeepAlive will bring up a fresh process",
            interval_hours * jitter,
        )
        self.shutdown()

    async def _compile_trigger_manifest(self):
        """Recompile the trigger manifest from graph state."""
        try:
            from campy.brain.thalamus.trigger_manifest import compile_manifest
            summary = await compile_manifest(self.db, self.config)
            if summary["triggers_compiled"] > 0:
                _logger.info(
                    "[Triggers] compiled %d triggers (%d procedures, %d lessons)",
                    summary["triggers_compiled"],
                    summary["procedures"],
                    summary["lessons"],
                )
        except Exception as e:
            _logger.error("[Triggers] manifest compilation failed: %s", e)

    async def _file_bridge_regen(self):
        """Regenerate context files for projects marked stale."""
        if not self._stale_projects:
            return
        from campy.brain.thalamus.file_bridge import regen_all
        stale = list(self._stale_projects)
        self._stale_projects.clear()
        for project_path in stale:
            try:
                result = await regen_all(Path(project_path), self.db)
                _logger.info(
                    "[FileBridge] regen %s: context_md=%s adrs=%d pointers=%s",
                    project_path,
                    result["context_md"],
                    result["adrs_generated"],
                    result["pointers_modified"],
                )
            except Exception as e:
                _logger.error("[FileBridge] regen failed for %s: %s", project_path, e)

    def mark_project_stale(self, project_path: str):
        """Mark a project's context files as needing regeneration."""
        self._stale_projects.add(project_path)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self.running = False
        # B316: close every open workspace client, not just the local one.
        # shutdown() runs from a signal handler and cannot await, so this
        # uses the router's synchronous close_all_sync() rather than the
        # async close_all(). self.db was registered into the router as the
        # "local" workspace client in start() (WorkspaceRouter.register),
        # so closing via the router closes it exactly once — the `else`
        # branch below only fires when start() never ran (no router yet).
        if self._router is not None:
            self._router.close_all_sync()
        else:
            self.db.close()
        socket_path = _socket_path()
        if socket_path.exists():
            socket_path.unlink()
        print("Brain Daemon stopped.")
        # D1 fix: stop the event loop so the process exits cleanly.
        try:
            asyncio.get_running_loop().stop()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    config = load_config()
    daemon = BrainDaemon(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.shutdown)

    await daemon.start()


if __name__ == "__main__":
    asyncio.run(main())
