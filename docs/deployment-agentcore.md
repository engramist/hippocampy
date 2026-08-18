# Deploying Campy Behind AWS Bedrock AgentCore Gateway

**Status: identity propagation resolved 2026-08-16 (open item 1, below); target-type mechanics
(open item 2) still pending the platform team.** This document records what B325 established,
an evaluating platform's answer to the identity-propagation question, and what remains open.
Specifics that identify the platform have been generalized below; the technical reasoning is
unchanged.

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

## The actual deployment topology

The customer's architecture review (2026-08-15) established that Campy is **not** registered as
a direct MCP-server Gateway target. Their governing architecture decision: targets are Lambdas
wrapping ecosystem adapters — the same adapter code is reused server-side as the Lambda
implementation, and adapters are never reimplemented per-gateway. Their single registered
Gateway target is a Lambda target. No MCP-server target is registered anywhere.

This is a **policy** decision, not a technical limitation — AWS Bedrock AgentCore Gateway
supports an `mcp.mcp_server` target type, and the provider's own escape hatch is to cite an
approved architecture decision (their own automated review gate treats a `remote_mcp` tool
wired without one as a HIGH finding). Both paths are legitimate; the platform picked
Lambda-fronted.

```
AgentCore agent → Gateway (AWS_IAM) → Lambda (thin adapter) → Campy HTTP MCP surface
```

The Lambda is a **thin proxy**: it receives the tool name in
`context.client_context.custom["bedrockAgentCoreToolName"]` plus tool arguments, and forwards
both to Campy's `/mcp` endpoint. **The Lambda must not reimplement tool logic** — their
architecture decision forbids exactly that; Campy's existing `TOOL_HANDLERS` is the adapter code
being reused, per that decision's own framing.

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

## Open item 1 — RESOLVED 2026-08-16: identity propagation is now required by their own policy

Original finding: the customer's Gateway invoked every target with its own service role, with
no per-caller metadata configured; their governing architecture decision accepted this as a
known risk. We asked whether `caller_iam_credentials` or `metadata_configuration` could be
enabled for a Campy target. Their answer, summarized because it is a policy decision other
cards depend on:

- Decided and codified 2026-08-16: every new gateway target gets `metadata_configuration` by
  default — session/workspace attributes travel as trusted transport metadata, never only in
  the request body — and any target holding per-tenant data additionally requires
  `caller_iam_credentials`, so the upstream call is signed as the real caller. A Campy target
  would be per-tenant by definition, so it gets both. The choice is recorded per target through
  a required tenancy-declaration variable in their infrastructure-as-code module for gateway
  targets — a target without an explicit tenancy statement won't register.
- The accepted-risk clause in their earlier decision is amended too: it now explicitly ends at
  the second target. The original acceptance was scoped to a single pre-existing, grandfathered
  read-only target. Any second target must declare its tenancy posture; the old acceptance does
  not carry over.

**Consequence for this repo:** if/when a Campy Gateway target is ever registered, it will
receive both `caller_iam_credentials` and `metadata_configuration` by the platform's own
mechanically-enforced policy — not as a request we'd need to keep making. `IAMPrincipalResolver`
(`campy/brain/auth.py`) is exactly the receiving side this feeds: `caller_iam_credentials` means
the SigV4 identity `IAMPrincipalResolver` verifies is the *real* calling agent's, not the
Gateway's own role.

**The signed-token fallback described in the previous version of this section is explicitly
rejected — do not build it.** Their reasoning, summarized: the real fix is pre-decided policy
plus provider-supported infrastructure config, not new engineering — a bespoke minted-token
plane would be a second auth mechanism of exactly the "per-agent side-channel" shape their
standards reject.

This is worth internalizing beyond this one document: a **workaround for someone else's
platform gap is itself a new side-channel**, and the fix belongs in the platform's own
governed config surface, not in Campy. No follow-up card for the token resolver exists or
should be filed.

**Important — this is not evaluation approval.** Their own caution, summarized so it isn't lost
in the good news above: these are policy answers about how any second target must be wired, not
a green light for a Campy target specifically. Their evaluation posture on Campy stands as of
this writing — pending resolution of the conditions they raised, independently auditable source
access being the first. The gateway plumbing is the easy part; the conditions are the gate.

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
