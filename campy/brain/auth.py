"""
campy/brain/auth.py — B315: Principal derivation and threading.

Campy today has no concept of *who* is asking. This module is the seam that
fixes that, for both the local single-user deployment and the eventual
multi-tenant cloud one, behind a single Protocol so the two never drift:

    Principal          — the answer to "who is this, and what can they do?"
    TransportContext    — what the TRANSPORT itself knows about the caller,
                           before any JSON-RPC request body is parsed
    PrincipalResolver    — Protocol: TransportContext -> Principal
    LocalSingleUserResolver — the only implementation this card builds

The rule this module exists to make structurally true, not merely
documented (see docs/ecosystem-rules.md's "Principal derivation" section):

    Tenant and workspace are derived from the transport credential,
    NEVER from request params.

Framing: local Campy is single-tenant cloud with auth stubbed.
`LocalSingleUserResolver` returns a real `Principal` (tenant "local",
workspace "local", every known scope) rather than `None` — handlers never
branch on "are we local?", so the multi-tenant dispatch path is exercised
by every local test run instead of only in production.

Cloud resolvers (OIDC, IAM) are out of scope for B315 — see B325 for
`IAMPrincipalResolver`, the first real implementation beyond local.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Scope vocabulary — start small, grow deliberately (module-level so it is
# the single source of truth for every resolver and every `.require()` call).
# ---------------------------------------------------------------------------

SCOPE_MEMORY_READ = "memory.read"
SCOPE_MEMORY_WRITE = "memory.write"
SCOPE_MEMORY_ADMIN = "memory.admin"
SCOPE_VISIBILITY_OVERRIDE = "visibility.override"

KNOWN_SCOPES: frozenset[str] = frozenset({
    SCOPE_MEMORY_READ,
    SCOPE_MEMORY_WRITE,
    SCOPE_MEMORY_ADMIN,
    SCOPE_VISIBILITY_OVERRIDE,
})

# Local mode is single-tenant cloud with auth stubbed — it holds every scope
# Campy currently knows about, by definition (there is no one else to deny).
_ALL_SCOPES: frozenset[str] = frozenset(KNOWN_SCOPES)
_DEFAULT_RUNTIME_SCOPES: frozenset[str] = frozenset({
    SCOPE_MEMORY_READ,
    SCOPE_MEMORY_WRITE,
})


@dataclass(frozen=True)
class Principal:
    """The answer to "who is asking, and what can they do?"

    Every field here is meant to be cheap to log and safe to put in an
    audit trail — none of it is a secret. `derived_from` in particular is
    not decoration: during an incident it is the difference between "we
    trusted a token" and "we trusted a request body."
    """

    subject_id: str        # stable user/service identity
    tenant_id: str          # isolation boundary — "local" in local mode
    workspace_id: str       # DB shard key (B316 consumes this) — "local" locally
    scopes: frozenset[str]  # subset of KNOWN_SCOPES this principal holds
    client: str             # "claude-code", "gemini-cli", "agentcore", … (observability only)
    session_id: str | None
    derived_from: str       # "local-single-user" | "oidc" | "iam" — how we know this

    def require(self, scope: str) -> None:
        """Raise PermissionError if `scope` is not held. Returns None otherwise."""
        if scope not in self.scopes:
            raise PermissionError(
                f"principal {self.subject_id!r} (tenant={self.tenant_id!r}, "
                f"workspace={self.workspace_id!r}) lacks required scope {scope!r}"
            )


@dataclass(frozen=True)
class TransportContext:
    """Everything the TRANSPORT itself knows about a caller.

    Constructed by the connection/request handler — `_handle_connection` for
    the Unix socket, the HTTP request handler for B325's remote surface —
    strictly BEFORE any JSON-RPC request body is read or parsed. That
    ordering is the whole point: this type must never carry a field that a
    client could populate via `params`, because "the workspace/tenant come
    from the transport credential, never from request params" is only a
    structural guarantee if the type used to derive them has no path back
    to the request body at all.

    Fields are deliberately generic across transports:
      - `transport`        — "unix-socket" | "http" | "stdio"
      - `peer_credential`  — an opaque, transport-verified identity string:
                              a Unix socket peer descriptor locally, a
                              verified SigV4 caller ARN or OIDC subject over
                              HTTP (B325). None when the transport has no
                              stronger credential than "you can reach the
                              socket" (today's local Unix socket).
      - `headers`          — raw HTTP headers, HTTP transport only. Read-only
                              transport metadata (e.g. for SigV4 signature
                              verification) — a resolver may inspect these,
                              but they carry connection/request metadata, not
                              the JSON-RPC method body.

    If the next field you want to add here would come from `params`, it
    does not belong on this type — thread it through the tool handler
    itself instead. Whoever is tempted to "just add workspace_id to
    TransportContext for convenience" should read this docstring first.
    """

    transport: str
    peer_credential: str | None = None
    headers: Mapping[str, str] | None = None


# Field names TransportContext is allowed to carry. Used by
# tests/test_auth_context.py to assert, structurally, that nothing
# request-body-shaped has been added here.
TRANSPORT_CONTEXT_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(TransportContext)
)


@runtime_checkable
class PrincipalResolver(Protocol):
    """TransportContext -> Principal. The only thing a resolver is allowed
    to look at is the transport context — never request params."""

    async def resolve(self, transport_ctx: TransportContext) -> Principal: ...


class LocalSingleUserResolver:
    """Local Campy mode: single user, single tenant, single workspace.

    Returns a real `Principal`, never `None` — see this module's docstring
    for why that framing ("local is single-tenant cloud with auth stubbed")
    matters: it is what keeps the multi-tenant dispatch path exercised by
    every local test run instead of only in a cloud deployment nobody has
    tested end to end.
    """

    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        return Principal(
            subject_id="local-user",
            tenant_id="local",
            workspace_id="local",
            scopes=_ALL_SCOPES,
            client="local",
            session_id=None,
            derived_from="local-single-user",
        )


# ---------------------------------------------------------------------------
# B315 Task 5 — the forbidden-key guard.
#
# A request whose `params` contain any of these keys is rejected before any
# handler runs (see campy/brain_daemon.py::_dispatch). This is
# belt-and-braces on top of TransportContext's structural separation above:
# even though params can never populate a TransportContext, a client could
# still try to pass e.g. `workspace_id` straight into a tool's `params` dict
# hoping a handler reads it directly. Nothing does (see the B315 PR notes on
# the two capture-path handlers this card converts), but the guard makes an
# attempt a logged, visible failure instead of a silent no-op that might
# stop being a no-op the next time someone touches a handler.
# ---------------------------------------------------------------------------

FORBIDDEN_PARAM_KEYS: frozenset[str] = frozenset({
    "tenant_id",
    "workspace_id",
    "subject_id",
    "principal",
    "scopes",
})


# ---------------------------------------------------------------------------
# B325 — IAMPrincipalResolver: the first non-local PrincipalResolver.
#
# boto3 is an OPTIONAL import here, exactly as campy/brain/llm/bedrock.py
# treats it: imported lazily, only when IAM auth mode is actually selected
# and a resolve() call is made, so a local user is never made to install
# AWS libraries just because this class exists in the import graph.
# ---------------------------------------------------------------------------


class IAMConfigError(RuntimeError):
    """Raised for an IAM auth configuration/verification problem."""


_BOTO3_INSTALL_HINT = (
    "IAM auth mode requires boto3, which is not installed. "
    "Install it with: pip install 'hippocampy[bedrock]'  (or: pip install boto3)"
)


def _import_boto3_for_iam():
    """Import boto3 lazily. Raises IAMConfigError with an install hint if
    boto3 is not present — mirrors bedrock.py's `_import_boto3()`."""
    try:
        import boto3
    except ImportError as e:
        raise IAMConfigError(_BOTO3_INSTALL_HINT) from e
    return boto3


async def _sts_get_caller_identity_verifier(headers: Mapping[str, str]) -> str:
    """Verify a SigV4-signed request by replaying its exact signed headers
    against AWS STS `GetCallerIdentity`.

    This is the same "IAM auth via STS" pattern HashiCorp Vault's `aws`
    auth method (and several API gateways) use: a SigV4 signature is only
    valid for the exact request it was computed over (method, URL,
    headers, body), so if the caller's own `Authorization` /
    `X-Amz-Date` / `X-Amz-Security-Token` headers succeed against STS,
    that proves the caller holds the credentials named in the
    Authorization header — Campy never sees a raw AWS secret key, only
    headers the caller already signed for this exact purpose.

    Returns the caller's ARN. Raises IAMConfigError on any failure
    (missing headers, non-SigV4 auth, STS rejects the signature, network
    error) — never lets a verification failure look like success.
    """
    boto3 = _import_boto3_for_iam()

    authorization = headers.get("authorization") or headers.get("Authorization")
    amz_date = headers.get("x-amz-date") or headers.get("X-Amz-Date")
    if not authorization or not amz_date:
        raise IAMConfigError("missing SigV4 Authorization/X-Amz-Date headers")
    if not authorization.startswith("AWS4-HMAC-SHA256"):
        raise IAMConfigError("Authorization header is not a SigV4 signature")

    security_token = headers.get("x-amz-security-token") or headers.get("X-Amz-Security-Token")

    def _call_sts() -> str:
        import botocore.session

        session = botocore.session.get_session()
        client = session.create_client("sts")
        request_headers = {"Authorization": authorization, "X-Amz-Date": amz_date}
        if security_token:
            request_headers["X-Amz-Security-Token"] = security_token
        endpoint = client.meta.endpoint_url

        import urllib.request

        req = urllib.request.Request(
            f"{endpoint}/?Action=GetCallerIdentity&Version=2011-06-15",
            headers=request_headers, method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — AWS endpoint only
            return resp.read().decode()

    try:
        body = await asyncio.to_thread(_call_sts)
    except IAMConfigError:
        raise
    except Exception as e:
        raise IAMConfigError(f"STS GetCallerIdentity verification failed: {e}") from e

    match = re.search(r"<Arn>([^<]+)</Arn>", body)
    if not match:
        raise IAMConfigError("STS response did not contain a caller ARN")
    return match.group(1)


class IAMPrincipalResolver:
    """PrincipalResolver for the B325 remote MCP surface's `auth = "iam"` mode.

    `resolve()` verifies the inbound request's SigV4 signature (via
    `verifier`, injectable for tests — defaults to
    `_sts_get_caller_identity_verifier`) and extracts the calling IAM
    identity. Unlike `LocalSingleUserResolver`, this can fail: an unsigned
    or badly-signed request must be rejected before any handler runs (see
    campy/brain_daemon.py::_dispatch — the caller catches `IAMConfigError`
    and returns a JSON-RPC error rather than dispatching).

    Field mapping (B325 Task 3):
      - `subject_id`     — the verified caller ARN, unmodified.
      - `tenant_id` / `workspace_id` — from `workspace_map` (keyed by ARN)
        when the caller ARN has an entry, else the resolver's configured
        default tenant/workspace. **Never read from `params`** — B315's
        rule holds on this transport exactly as it does locally. If the
        Gateway in front of Campy passes a workspace as a session
        attribute, that arrives as an HTTP header on `transport_ctx`,
        which is transport-level and therefore an acceptable source; it
        would not be acceptable arriving in the JSON-RPC body. See
        docs/deployment-agentcore.md for the caveat that the customer's
        current Gateway configuration does not yet forward one.
      - `derived_from`   — always "iam".
    """

    def __init__(
        self,
        *,
        tenant_id: str = "default",
        workspace_id: str = "default",
        workspace_map: dict[str, str] | None = None,
        tenant_map: dict[str, str] | None = None,
        principal_scope_map: dict[str, list[str] | tuple[str, ...] | set[str]] | None = None,
        default_scopes: list[str] | tuple[str, ...] | set[str] | None = None,
        client: str = "agentcore",
        verifier=_sts_get_caller_identity_verifier,
    ) -> None:
        self._default_tenant_id = tenant_id
        self._default_workspace_id = workspace_id
        self._workspace_map = workspace_map or {}
        self._tenant_map = tenant_map or {}
        self._principal_scope_map = principal_scope_map or {}
        if default_scopes is None:
            self._default_scopes = _DEFAULT_RUNTIME_SCOPES
        else:
            unknown = set(default_scopes) - KNOWN_SCOPES
            if unknown:
                raise IAMConfigError(f"unknown default scope(s): {sorted(unknown)}")
            self._default_scopes = frozenset(default_scopes)
        self._client = client
        self._verifier = verifier

    async def resolve(self, transport_ctx: TransportContext) -> Principal:
        headers = transport_ctx.headers or {}
        caller_arn = await self._verifier(headers)

        # Operator-configured workspace mapping is authoritative. A caller
        # can request a workspace via header, but that value never overrides
        # explicit operator policy.
        header_workspace = headers.get("x-campy-workspace-id") or headers.get("X-Campy-Workspace-Id")
        mapped_workspace = self._workspace_map.get(caller_arn)
        if mapped_workspace:
            if header_workspace and header_workspace != mapped_workspace:
                raise IAMConfigError(
                    "workspace header override rejected: caller is bound to operator-configured workspace"
                )
            workspace_id = mapped_workspace
        else:
            # No explicit grant for this caller: never allow an arbitrary
            # caller-supplied workspace id.
            if header_workspace and header_workspace != self._default_workspace_id:
                raise IAMConfigError(
                    "workspace header requires explicit iam_workspace_map grant for this caller"
                )
            workspace_id = self._default_workspace_id

        tenant_id = self._tenant_map.get(caller_arn) or self._default_tenant_id
        scoped = self._principal_scope_map.get(caller_arn)
        if scoped is None:
            scopes = self._default_scopes
        else:
            unknown = set(scoped) - KNOWN_SCOPES
            if unknown:
                raise IAMConfigError(
                    f"unknown scope(s) configured for {caller_arn}: {sorted(unknown)}"
                )
            scopes = frozenset(scoped)

        return Principal(
            subject_id=caller_arn,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            scopes=scopes,
            client=self._client,
            session_id=None,
            derived_from="iam",
        )


__all__ = [
    "SCOPE_MEMORY_READ",
    "SCOPE_MEMORY_WRITE",
    "SCOPE_MEMORY_ADMIN",
    "SCOPE_VISIBILITY_OVERRIDE",
    "KNOWN_SCOPES",
    "Principal",
    "TransportContext",
    "TRANSPORT_CONTEXT_FIELDS",
    "PrincipalResolver",
    "LocalSingleUserResolver",
    "FORBIDDEN_PARAM_KEYS",
    "IAMConfigError",
    "IAMPrincipalResolver",
]
