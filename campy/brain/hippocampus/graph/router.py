"""
campy/brain/hippocampus/graph/router.py — B316: WorkspaceRouter, one Kùzu
database per workspace.

Isolation model chosen (see docs/ARCHITECTURE.md's B316 section for the full
rationale): a shared graph with a `tenant_id` predicate needs every one of
~500 Cypher call sites to carry the filter, which is not auditable; a
database per workspace makes isolation physical instead, and turns Kùzu's
single-writer-per-database constraint into per-workspace parallelism instead
of a global bottleneck.

Sharding boundary rule: shard where traversal does not need to cross. Agents
working in one workspace never traverse into another; cross-workspace
knowledge is a separate, deliberately-promoted store, not an accidental
traversal.

`workspace_id` is treated as untrusted input for filesystem purposes —
principals will eventually be minted from external identity systems, so this
module never trusts a workspace_id string enough to interpolate it into a
path without validating it first. See `_workspace_dir()`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Awaitable, Callable

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# B316 Task 2 — allowlist regex, not a blocklist. A blocklist of "bad"
# characters loses (there is always one more way to spell `..`); an
# allowlist of what's PERMITTED makes traversal structurally impossible
# rather than merely filtered. 1-64 chars, first char alphanumeric.
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# The local single-workspace deployment must resolve to the pre-existing
# DB_PATH unchanged, with no migration — an existing install keeps its
# memory. Special-cased explicitly (never relying on the digest happening
# to match brain.db) — see _workspace_dir(). WorkspaceRouter's one caller
# (campy/brain_daemon.py) passes the real DB_PATH in explicitly as
# `local_db_path`, so this module never has to know or guess the filename
# campy.paths.get_database_path() uses — the two cannot drift apart.
LOCAL_WORKSPACE_ID = "local"


def _workspace_dir(root: Path, workspace_id: str, *, local_db_path: Path) -> Path:
    """Resolve `workspace_id` to a directory under `root`, safely.

    Raises ValueError for anything that doesn't match the allowlist regex
    (this also structurally rejects traversal sequences, empty strings,
    over-length ids, and null bytes — none of those characters are in the
    allowed set, so there is nothing to special-case).

    The digest suffix (non-local workspaces only) exists for a reason
    distinct from the regex: the regex prevents traversal, the digest
    prevents case-insensitive-filesystem collisions (`Foo` and `foo` are
    different workspace ids but could collide as directory names on a
    case-insensitive filesystem without it).
    """
    if workspace_id == LOCAL_WORKSPACE_ID:
        resolved = local_db_path.resolve()
    else:
        if not _WORKSPACE_ID_RE.fullmatch(workspace_id):
            raise ValueError(
                f"invalid workspace_id {workspace_id!r}: must match "
                f"{_WORKSPACE_ID_RE.pattern}"
            )
        digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:16]
        resolved = (root / f"{workspace_id}-{digest}").resolve()

    # Belt and braces: this is the one place in this module where a bug is
    # a security bug (path traversal) rather than an availability bug, so
    # the resolved path is asserted inside root even though the regex
    # above should already make escaping impossible.
    root_resolved = root.resolve()
    if not (resolved == root_resolved or root_resolved in resolved.parents):
        raise ValueError(
            f"resolved workspace path {resolved} escapes root {root_resolved}"
        )
    return resolved


class WorkspaceRouter:
    """One `KuzuClient` per workspace, LRU-bounded, safe under concurrency.

    - **LRU cache**, bounded by `max_open`. A `KuzuClient` holds an open
      `kuzu.Database` handle — leaking these exhausts file descriptors
      under load, which is the failure mode `max_open` exists to prevent.
    - **First access to an unknown workspace** creates its directory and
      runs `schema_init()`. Concurrent first-access for the same new
      workspace is guarded by a per-workspace `asyncio.Lock` (never a
      global one — that would serialize unrelated workspaces' first access
      against each other too).
    - **Eviction never closes a busy client.** `get()`/`release()` are a
      matched pair: a caller that holds a client across an operation
      should call `release()` when done, so eviction can consider it
      again. If every open client is busy when the bound is exceeded, the
      router logs at WARNING and exceeds `max_open` rather than blocking
      or closing something in use.
    """

    def __init__(self, root: Path, *, max_open: int = 32,
                 schema_init: Callable[[KuzuClient], Awaitable[None]],
                 local_db_path: Path | None = None):
        self._root = root
        self._max_open = max_open
        self._schema_init = schema_init
        # Defaults to root / "brain.db" for convenience (e.g. tests that
        # don't care about the local-alias special case), but
        # campy/brain_daemon.py always passes the real DB_PATH explicitly.
        self._local_db_path = local_db_path if local_db_path is not None else (root / "brain.db")
        # OrderedDict as an LRU: move_to_end() on every access keeps the
        # least-recently-used entry at the front (iteration order).
        self._clients: "OrderedDict[str, KuzuClient]" = OrderedDict()
        self._init_locks: dict[str, asyncio.Lock] = {}
        self._borrow_counts: dict[str, int] = {}

    @property
    def open_count(self) -> int:
        return len(self._clients)

    def _init_lock(self, workspace_id: str) -> asyncio.Lock:
        # No `await` between the dict lookup and the possible insert, so
        # this is race-free under asyncio's single-threaded cooperative
        # scheduling — same reasoning as kuzu_client.py's _get_write_lock().
        lock = self._init_locks.get(workspace_id)
        if lock is None:
            lock = asyncio.Lock()
            self._init_locks[workspace_id] = lock
        return lock

    def register(self, workspace_id: str, client: KuzuClient) -> None:
        """Pre-seed the cache with an already-open client for `workspace_id`,
        without going through `get()`'s creation path.

        Exists for exactly one caller: `BrainDaemon` opens `self.db` (the
        "local" workspace client) at `__init__`, before a router exists at
        all. Wiring that same instance in via `register("local", self.db)`
        means `get("local")` returns that *same* `KuzuClient` rather than
        opening a second `kuzu.Database` handle on the identical directory
        — Kùzu is single-process-writer, so two live handles on one path
        is not just wasteful, it is the exact hazard this method exists to
        avoid.
        """
        self._clients[workspace_id] = client
        self._clients.move_to_end(workspace_id)

    async def get(self, workspace_id: str) -> KuzuClient:
        """Return a client for this workspace, opening (and initializing
        schema on) the database if it does not exist yet. Pairs with
        `release()` — see the class docstring."""
        existing = self._clients.get(workspace_id)
        if existing is not None:
            self._clients.move_to_end(workspace_id)
            self._borrow_counts[workspace_id] = self._borrow_counts.get(workspace_id, 0) + 1
            return existing

        async with self._init_lock(workspace_id):
            # Re-check after acquiring the lock: a concurrent get() for
            # this same new workspace may have already created it while
            # this coroutine was waiting on the lock.
            existing = self._clients.get(workspace_id)
            if existing is not None:
                self._clients.move_to_end(workspace_id)
                self._borrow_counts[workspace_id] = self._borrow_counts.get(workspace_id, 0) + 1
                return existing

            workspace_dir = _workspace_dir(
                self._root, workspace_id, local_db_path=self._local_db_path
            )
            workspace_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            client = KuzuClient(str(workspace_dir))
            await self._schema_init(client)

            self._clients[workspace_id] = client
            self._clients.move_to_end(workspace_id)
            self._borrow_counts[workspace_id] = self._borrow_counts.get(workspace_id, 0) + 1

            await self._evict_if_needed()
            return client

    def release(self, workspace_id: str) -> None:
        """Signal that a client borrowed via `get()` is no longer in use.

        Not calling this is safe (the workspace simply never becomes
        eligible for eviction — `open_count` may exceed `max_open`, logged
        at WARNING) but is a resource-accounting bug at the call site worth
        fixing, not a correctness one: the client itself is never closed
        out from under an in-flight caller either way.
        """
        count = self._borrow_counts.get(workspace_id, 0)
        if count > 0:
            self._borrow_counts[workspace_id] = count - 1

    async def _evict_if_needed(self) -> None:
        while len(self._clients) > self._max_open:
            victim = None
            for candidate in self._clients:  # OrderedDict: LRU-first
                if self._borrow_counts.get(candidate, 0) > 0:
                    continue
                victim = candidate
                break
            if victim is None:
                _logger.warning(
                    "WorkspaceRouter: open_count=%d exceeds max_open=%d but "
                    "every open workspace client is busy — exceeding the "
                    "bound rather than evicting something in use.",
                    len(self._clients), self._max_open,
                )
                return
            client = self._clients.pop(victim)
            client.close()
            self._borrow_counts.pop(victim, None)

    async def close(self, workspace_id: str) -> None:
        client = self._clients.pop(workspace_id, None)
        if client is not None:
            client.close()
        self._borrow_counts.pop(workspace_id, None)
        self._init_locks.pop(workspace_id, None)

    async def close_all(self) -> None:
        for workspace_id in list(self._clients):
            await self.close(workspace_id)

    def close_all_sync(self) -> None:
        """Synchronous variant of `close_all()`, for callers that cannot
        await — namely `BrainDaemon.shutdown()`, which runs from a signal
        handler. `KuzuClient.close()` is itself synchronous, so this needs
        no lock: nothing else runs concurrently with a signal-handler
        callback in asyncio's single-threaded model. Prefer `close_all()`
        from async code."""
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                _logger.exception("WorkspaceRouter: error closing a client during shutdown")
        self._clients.clear()
        self._borrow_counts.clear()
