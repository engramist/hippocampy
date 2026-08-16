# Deploying Campy Behind AWS Bedrock AgentCore Gateway

**Status: partially pending** — the Gateway target-type decision and the identity-propagation
question below are marked explicitly and are not guessed at. This document records what B325
established plus the two open items its author (the customer's platform team) still needs to
answer.

## What B325 built

Campy's streamable-HTTP MCP transport (`POST /mcp`, MCP spec 2025-03-26) already existed —
see `web/server.py`, wired into `campy/brain_daemon.py::_start_web_server`. B325 added:

- **The bind guard** (`campy.brain_daemon._enforce_bind_guard`): binding to any non-loopback
  address while `[server].auth = "none"` is a hard startup failure. This is the property that
  makes it safe to describe a deployment topology below at all — a misconfigured bind can't
  silently expose Campy's memory unauthenticated.
- **`IAMPrincipalResolver`** (`campy/brain/auth.py`): verifies a SigV4-signed request by
  replaying its exact signed headers against AWS STS `GetCallerIdentity`, and maps the caller
  ARN to a `Principal`.
- **`route_tool_call()`** (`campy/brain_daemon.py`): the single chokepoint both the Unix-socket
  transport and the streamable-HTTP transport now call through, so B315's forbidden-key guard
  and (once B316 lands) workspace routing apply identically on every transport — no separate
  code path to drift.

## The actual deployment topology (ADR-0031)

The customer's architecture review (2026-08-15) established that Campy is **not** registered as
a direct MCP-server Gateway target. Per **ADR-0031 decision #3**: *"Targets are Lambdas
wrapping ecosystem adapters — Layer 6/5 adapter code is reused server-side as the Lambda
implementation. Adapters are never reimplemented per-gateway."* Their single registered Gateway
target is `target_configuration.mcp.lambda` (`targetType: LAMBDA`). No MCP-server target is
registered anywhere.

This is a **policy** decision, not a technical limitation — AWS Bedrock AgentCore Gateway
supports an `mcp.mcp_server` target type, and the provider's own escape hatch is to cite an ADR
(Gate check #8, `agent_harness_schema.py:35`, `_ADR_REQUIRED_TYPES`: a `harness.json` wiring a
`remote_mcp` tool without a cited ADR is a HIGH finding). Both paths are legitimate; the
platform picked Lambda-fronted.

```
AgentCore agent → Gateway (AWS_IAM) → Lambda (thin adapter) → Campy HTTP MCP surface
```

The Lambda is a **thin proxy**: it receives the tool name in
`context.client_context.custom["bedrockAgentCoreToolName"]` plus tool arguments, and forwards
both to Campy's `/mcp` endpoint. **The Lambda must not reimplement tool logic** — ADR-0031
forbids exactly that; Campy's existing `TOOL_HANDLERS` is the adapter code being reused, per the
ADR's own framing.

Why Campy's HTTP surface is the prerequisite (not an alternative) for this topology, not just
one option among several: **Kùzu is single-process-writer.** A Lambda cannot open the database
file directly — concurrent Lambda invocations would contend for exclusive access on the same
embedded database. The Lambda must proxy to a long-running Campy process (the daemon this repo
already runs), which is exactly what the streamable-HTTP transport is for.

## What Tasks 1–3 are still needed for

Building the streamable-HTTP transport, the bind guard, and `IAMPrincipalResolver` is **not**
wasted work under the Lambda topology above:

- The Lambda itself needs an HTTP surface to proxy to — Campy's `/mcp` endpoint, with the bind
  guard protecting it if Campy is ever reachable from outside the Lambda's network path.
- `IAMPrincipalResolver` is needed for every non-AgentCore IAM-authenticated consumer, and for
  a future direct Gateway `mcp.mcp_server` target if the platform ever picks that escape hatch
  instead.

## Open item 1 — identity does not propagate through the Gateway today

The customer's Gateway invokes with its own service role (`gateway_iam_role {}`); the provider's
`metadata_configuration` is never set. Concretely: **neither the calling agent's IAM identity
nor any session attribute reaches the Lambda or Campy today.** ADR-0031 accepts this as a known
risk.

The provider *does* support two mechanisms that would fix this, both currently unused:

- `caller_iam_credentials` — would let the Gateway forward the calling identity instead of its
  own service role.
- `metadata_configuration` — would let the Gateway attach session attributes (e.g. a workspace
  tag) that reach the target.

**Until one of these is enabled, B315's rule — workspace derives from the transport credential,
never from request params — cannot hold behind this Gateway.** The only channel available today
is the request body, which is precisely what B315 forbids trusting.

**Documented fallback (not implemented in B325):** a short-lived signed token, minted by the
platform's own backend and scoped to exactly one workspace, passed through in a way the Lambda
can treat as a transport-level credential (e.g. a header it attaches before calling Campy,
verified by a resolver the same way `IAMPrincipalResolver` verifies SigV4). This is categorically
different from a plaintext `workspace_id` in the JSON-RPC body: it's signed, short-lived, and
scoped — the security properties `TransportContext` needs to hold, carried on the transport
rather than in `params`. Building this resolver is a follow-up card, gated on the platform
enabling `caller_iam_credentials` or `metadata_configuration` (or committing to the signed-token
approach independently of either).

## Open item 2 — the Gateway target-type question is unresolved by definition

Per the architecture review, the target type is settled: Lambda, not MCP-server. What remains
genuinely open is everything downstream of that decision that only the platform team can answer:
the Lambda's IAM policy (least-privilege scoped to invoking Campy's endpoint and, transitively,
whatever Campy itself needs), the network path from the Lambda to wherever Campy runs (VPC
peering, PrivateLink, or public endpoint behind the bind guard + IAM auth), and the end-to-end
verification procedure once both exist. This document stays marked pending until the platform
team provides those specifics — Tasks 1–3 do not block on them, per the card's own scoping.

## Verifying the transport in isolation (no Gateway/Lambda required)

Everything below is testable today, independent of the open items above:

```bash
# Loopback, no auth (today's local default — unchanged by B325):
curl -s -X POST http://127.0.0.1:7799/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For IAM mode, set `[server]` in `campy.toml`:

```toml
[server]
bind_host = "0.0.0.0"   # or a concrete bind address — see the bind guard below
auth      = "iam"
```

then sign a request the same way the eventual Lambda proxy will (SigV4 over the exact request,
verified server-side by replaying it against STS `GetCallerIdentity` — see
`campy.brain.auth._sts_get_caller_identity_verifier`). An unsigned request is rejected before
any tool handler runs.

Also see `campy.cli.smoke_test.check_remote_mcp_surface()` for a scripted check that the HTTP
surface advertises the same tools the Unix-socket transport does — both now share
`route_tool_call()`, so that comparison means something.
