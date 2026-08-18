"""
campy/brain/auth.py — B315 AuthContext: principal derivation and threading.

Campy today has no concept of *who* is asking — every JSON-RPC call has
routed through one global `self.db` with no caller identity and no
scoping. That is correct for local single-user Campy and completely
insufficient the moment more than one principal shares a deployment.

The design rule this module exists to enforce:

    The workspace and tenant are derived from the transport credential,
    never from the request params.

If an agent can pass a `workspace_id` argument, an agent can read another
tenant's memory — textbook confused-deputy, and with LLM agents it is one
prompt injection away from being exercised. This must be structurally
impossible, not merely discouraged. See `TransportContext` below for how
that is enforced, and `docs/ecosystem-rules.md` for the non-negotiable
rule statement.

Framing that keeps one code path: **local Campy is single-tenant cloud
with auth stubbed.** `LocalSingleUserResolver` returns a real `Principal`
(tenant `local`, workspace `local`, all scopes) — never `None`. Handlers
never branch on "are we local?"; if local became a special-cased path, the
two deployments would drift and the cloud path would stop being exercised
by local tests. See docs/ARCHITECTURE.md's B315 section for the full
contract, and B316 (workspace router — depends on this card) for how
`Principal.workspace_id` gets consumed to pick a database shard.

Contents:
    SCOPES                  — module-level scope vocabulary (start small).
    Principal                — who is asking, and what they're allowed to do.
    TransportContext          — what the *transport* knows, before any request
                                body is parsed. Never carries JSON-RPC params.
    PrincipalResolver         — Protocol: TransportContext -> Principal.
    LocalSingleUserResolver    — the only concrete resolver this card builds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Scope vocabulary
# ---------------------------------------------------------------------------

# Deliberately small — grow this list as real scoped operations need it,
# not speculatively. `memory.read`/`memory.write` cover the bulk of the
# existing MCP tool surface; `memory.admin` is reserved for admin-only
# operations like B313's drop_projections(); `visibility.override` is
# reserved for the not-yet-built visibility (private/team/org) filtering
# card (see B315's "What This Card Does NOT Do").
SCOPES = frozenset({
    "memory.read",
    "memory.write",
    "memory.admin",
    "visibility.override",
})

# The tenant/workspace/subject identifiers local (single-user) Campy uses.
# Not placeholders — this *is* the real tenant/workspace boundary in local
# mode, it just happens to have exactly one member. See the module
# docstring's "local is single-tenant cloud with auth stubbed" framing.
LOCAL_TENANT_ID = "local"
LOCAL_WORKSPACE_ID = "local"
LOCAL_SUBJECT_ID = "local-user"
LOCAL_CLIENT = "local"


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """Who is asking, and what they're allowed to do.

    Every field here is meant to be cheap to log and safe to put in an
    audit trail — none of it is a secret. `tenant_id`/`workspace_id` are
    the isolation boundary (B316 consumes `workspace_id` as the DB shard
    key); `client`/`session_id` are observability-only labels, never
    trust boundaries — `subject_id`/`tenant_id`/`workspace_id`/`scopes`
    are the ones that matter for access control.
    """

    subject_id: str        # stable user/service identity
    tenant_id: str         # isolation boundary — "local" in local mode
    workspace_id: str      # DB shard key (B316 consumes this) — "local" locally
    scopes: frozenset[str]  # e.g. {"memory.read", "memory.write"}
    client: str             # "claude-code", "gemini-cli", …  (observability only)
    session_id: str | None
    # "local-single-user" | "oidc" | "iam" — how we know this. Not
    # decoration: during an incident it is the difference between "we
    # trusted a token" and "we trusted a request body."
    derived_from: str

    def require(self, scope: str) -> None:
        """Raise PermissionError if `scope` is not held. Returns None (a
        plain no-op) when it is."""
        if scope not in self.scopes:
            raise PermissionError(
                f"principal {self.subject_id!r} (tenant={self.tenant_id!r}) "
                f"lacks required scope {scope!r}; held: {sorted(self.scopes)}"
            )


# ---------------------------------------------------------------------------
# TransportContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportContext:
    """Everything the *transport* knows about the caller — peer credentials
    from the unix socket, HTTP headers, TLS identity, whatever the wire
    itself can attest to.

    It must NOT carry the JSON-RPC `params` of the request being served.
    This is enforced structurally, not by convention: `brain_daemon.py`'s
    `_handle_connection` constructs one of these BEFORE the request body
    is parsed (see the comment at that construction site for why), and
    nothing in this dataclass gives a downstream caller any way to stuff
    request-body data into it after the fact — there is no field shaped
    like "extra params" or "raw request" to abuse. `PrincipalResolver`
    implementations get only what's declared here.

    Every field below is something the *connection* attests to, not
    something the *request* claims. `client_hint`, in particular, is an
    observability label the transport itself may be able to supply (e.g.
    a future TLS SNI / mTLS CN) — it is never populated from a JSON-RPC
    `params` dict, which is the entire point of this type existing.
    """

    transport: str = "unix_socket"        # "unix_socket" | "http" | ...
    peer_credentials: dict | None = None  # e.g. SO_PEERCRED {pid,uid,gid} — best effort
    client_hint: str | None = None        # transport-level client label, if any
    extra: dict = field(default_factory=dict)  # reserved for future transport metadata


# ---------------------------------------------------------------------------
# PrincipalResolver
# ---------------------------------------------------------------------------


@runtime_checkable
class PrincipalResolver(Protocol):
    """Resolves a `TransportContext` into a `Principal`.

    Cloud resolvers (OIDC/IAM) are out of scope for this card — this
    Protocol is the seam they'll implement against. `LocalSingleUserResolver`
    below is the only concrete implementation this card builds; a fake
    non-local resolver lives in `tests/test_auth_context.py` to prove the
    seam works for a non-local principal without building a real cloud
    resolver.
    """

    async def resolve(self, transport_ctx: TransportContext) -> Principal: ...


class LocalSingleUserResolver:
    """Local mode. Returns a fixed `Principal` with all scopes.

    This is the "auth stubbed" half of "local Campy is single-tenant cloud
    with auth stubbed" — every connection resolves to the same principal:
    tenant `local`, workspace `local`, every scope in `SCOPES`. It ignores
    `transport_ctx` almost entirely (there is exactly one principal to
    resolve to in local mode) except for `client_hint`, which — when the
    transport happens to supply one — becomes `Principal.client` instead
    of the generic `LOCAL_CLIENT` default; that field is observability-only
    so there's no harm in the transport enriching it when it can.
    """

    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        return Principal(
            subject_id=LOCAL_SUBJECT_ID,
            tenant_id=LOCAL_TENANT_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            scopes=frozenset(SCOPES),
            client=transport_ctx.client_hint or LOCAL_CLIENT,
            session_id=None,
            derived_from="local-single-user",
        )
