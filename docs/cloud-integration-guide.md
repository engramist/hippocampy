# Cloud Integration Guide (AWS ECS/Fargate)

How to run Campy as a shared memory service in your AWS account, and how
agents call it. The card is [B385](../backlog/B385.md). The local
single-user install is unaffected by anything here.

## 1. What runs

One container (`deploy/Dockerfile`) running `python -m campy.brain_daemon`:

| Path | What | Auth |
|---|---|---|
| `GET /health` | Liveness and storage probe (section 6) | none |
| `POST /mcp`, `GET /mcp`, `GET /sse` | MCP (Streamable HTTP, spec 2025-03-26) | SigV4 via STS |
| `/api/v1/*` | REST: `recall`, `bundle`, `timeline`, `diff`, `decide`, `status`, `notify`, `tools`, `heartbeat`, `activity/stream` | SigV4 via STS |

The web dashboard is off (`CAMPY_SERVER_DASHBOARD_ENABLED=false`). It is an
operator view of the local workspace only ([B457](../backlog/B457.md)).

Every memory request, whether MCP or REST, goes through the same dispatch
chokepoint (`route_tool_call`). It resolves the caller's workspace, checks the
caller's scopes, and rejects `tenant_id` / `workspace_id` / `principal` /
`scopes` supplied in the request body.

## 2. Build and push the image

```bash
docker build -f deploy/Dockerfile -t campy:<tag> .
# optional mirror for the base image:
#   --build-arg PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
aws ecr get-login-password | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker tag campy:<tag> <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/campy:<tag>
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/campy:<tag>
```

**Build:** needs the base-image registry, pypi.org, github.com (the spaCy
`en_core_web_md` model) and huggingface.co (the embedding model).

**Runtime:** needs no internet egress except AWS STS and Bedrock (use VPC
endpoints). Both models are baked into the image, and it runs with
`HF_HUB_OFFLINE=1`.

The image runs as non-root UID 1000.

## 3. Deploy on ECS/Fargate

Start from `deploy/ecs-task-definition.json` and fill in the `<...>`
placeholders.

**Storage: Amazon EFS mounted at `/data/campy` (`CAMPY_HOME`).** Everything
persistent lives there:
- the graph store and the vector/FTS index;
- per-workspace shards under `workspaces/`;
- logs;
- `config.toml`, which the entrypoint seeds from the image default on first
  start and never overwrites afterwards.

> **Run exactly one task per EFS file system.** The graph store is an embedded
> RocksDB (pyoxigraph) and the vector index is SQLite. Both allow a single
> writer. Two tasks on the same volume will contend for locks or corrupt the
> store. Set the service's `desiredCount` to 1, with
> `deploymentConfiguration` `minimumHealthyPercent: 0` and
> `maximumPercent: 100`, so a deployment stops the old task before starting
> the new one. For more tenants or throughput, run separate services with
> separate file systems.

EFS latency is higher than local disk. The daemon's hot path is in-process,
so this mainly affects cold start and writes.

**IAM roles:**
- **Task role:** `bedrock:InvokeModel` for your model or inference profile.
  STS `GetCallerIdentity` needs no permission.
- **Execution role:** the usual ECR pull and CloudWatch Logs permissions, plus
  `ssm:GetParameters` for the parameters in `secrets` (and `kms:Decrypt` if
  they are SecureStrings).

**Networking:** put an ALB (HTTPS listener only) in front of the task on port
7799, with the target group health check at `GET /health`. The IPC socket
stays on container-local disk (`CAMPY_SOCKET_PATH=/tmp/campy/brain.sock`),
because Unix sockets on NFS are unreliable.

## 4. Configuration

The environment overrides `config.toml`. Malformed values stop startup with
an error that names the variable. The full table is
`campy/brain/brainstem/config.py::ENV_OVERRIDES`.

| Variable | Config key | Container default |
|---|---|---|
| `CAMPY_SERVER_AUTH` | `[server].auth` | `iam` (the bind guard refuses `0.0.0.0` with `none`) |
| `CAMPY_SERVER_BIND_HOST` | `[server].bind_host` | `0.0.0.0` |
| `CAMPY_SERVER_DASHBOARD_ENABLED` | `[server].dashboard_enabled` | `false` |
| `CAMPY_WEB_PORT` | `[web].port` | `7799` |
| `CAMPY_LLM_PROVIDER` / `_MODEL` / `_REGION` / `_BASE_URL` | `[llm].*` | `bedrock`, no model: **required** (the container refuses to start without it) |
| `CAMPY_IAM_TENANT_ID` / `CAMPY_IAM_WORKSPACE_ID` | defaults for unmapped callers | set per deployment |
| `CAMPY_IAM_WORKSPACE_MAP_JSON` | `{"<caller ARN>": "<workspace>"}` | from SSM |
| `CAMPY_IAM_TENANT_MAP_JSON` | `{"<caller ARN>": "<tenant>"}` | from SSM |
| `CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON` | `{"<caller ARN>": ["memory.read", ...]}` | from SSM |
| `CAMPY_IAM_DEFAULT_SCOPES_JSON` | scopes for callers without a scope-map entry | `["memory.read","memory.write"]` if unset |

`CAMPY_HOME` sets where all state lives.

## 5. Calling the service

### Authentication

Campy authenticates the caller with the "IAM via STS" pattern, as HashiCorp
Vault's `aws` auth method does:

1. The client signs a request for **STS `GetCallerIdentity`**, not a request
   for Campy.
2. The client sends the resulting headers to Campy with each request.
3. Campy replays them to STS and uses the ARN STS returns.

Campy never sees an AWS secret key.

**Sign for the same STS host the service uses:**
`sts.<AWS_REGION>.amazonaws.com`, where `AWS_REGION` is the task's region
(Fargate sets it).

```python
import botocore.session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def campy_auth_headers(region: str) -> dict:
    creds = botocore.session.get_session().get_credentials().get_frozen_credentials()
    url = f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15"
    req = AWSRequest(method="GET", url=url)
    SigV4Auth(creds, "sts", region).add_auth(req)
    headers = {"Authorization": req.headers["Authorization"],
               "X-Amz-Date": req.headers["X-Amz-Date"]}
    if creds.token:
        headers["X-Amz-Security-Token"] = req.headers["X-Amz-Security-Token"]
    return headers
```

Send these headers on every request, and re-sign at least every few minutes.
Verified identities are cached for 15 minutes, keyed on the exact
`Authorization` + `X-Amz-Date`.

> **Replay window.** These headers prove identity to STS. They are not bound
> to a particular Campy request, so anyone who captures them can reuse them
> until STS stops accepting them. Serve only over TLS (HTTPS on the ALB), use
> short-lived role credentials, and keep the workspace and scope policy below
> tight. It is defence in depth, not optional.

### Workspace and tenant

- A caller's workspace comes from `CAMPY_IAM_WORKSPACE_MAP_JSON`, keyed by
  the verified ARN. Callers without an entry get `CAMPY_IAM_WORKSPACE_ID`.
- A caller may send `x-campy-workspace-id`. It must equal the operator-mapped
  workspace (or, for unmapped callers, the default), otherwise the request is
  rejected. It can never select another workspace.
- Workspaces are separate stores under `$CAMPY_HOME/workspaces/`, not
  row-level filters.

### Scopes

- Read-only tools (for example `current_truth`, `compile_context`) need
  `memory.read`. Everything else, including `notify_turn`, needs
  `memory.write`.
- Missing scope: REST returns 403 and MCP returns a JSON-RPC error.
- Per-caller scopes come from `CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON`.

### REST contract

All responses are `{"ok": true, "data": {...}}` or
`{"ok": false, "error": "..."}`.

| Endpoint | Input | Maps to |
|---|---|---|
| `GET /api/v1/recall?q=...&scope=both&session_id=...` | query string | `current_truth` |
| `POST /api/v1/bundle` | `{"query", "token_budget"?, "agent_type"?}` | `compile_context` |
| `GET /api/v1/timeline?since=<ISO>&limit=20&quest_id=...` | query string | `reconstruct_timeline` |
| `GET /api/v1/diff?since=<ISO>` | query string | `diff_since` |
| `POST /api/v1/decide` | `{"query", "session_id"?}` | `memory_decision` |
| `GET /api/v1/status?session_id=...` | query string | `context_status` |
| `POST /api/v1/notify` | `{"role", "content", "session_id"?}` | `notify_turn` |
| `GET /api/v1/tools` | none | list of tools |
| `GET /api/v1/heartbeat`, `/api/v1/activity/stream` | none | daemon phase (no memory content) |

Status codes:

| Status | Meaning |
|---|---|
| 400 | Bad input, forbidden parameter, or invalid workspace |
| 401 | Unauthenticated |
| 403 | Missing scope |
| 404 | Unknown tool |
| 500 | Tool failure |

### MCP

`POST /mcp` takes JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`)
with the same headers. Any MCP client that can add custom headers works.

## 6. Health

`GET /health` is unauthenticated and returns low-sensitivity fields only:

```json
{"status": "ok", "version": "0.1.0", "uptime_s": 12.3, "rss_mb": 412.0, "storage": "ok"}
```

It returns **503** with `"status": "unhealthy"` when the graph store can't be
queried within 1 s, so the ALB and ECS replace the task. The probe is a
lock-free read, so a long write doesn't make a healthy task look dead.
Startup (model load, store open) can take a minute or more, hence the 120 s
`startPeriod`.

## 7. Local cloud-parity run

```bash
CAMPY_LLM_MODEL=<model-or-profile-id> AWS_PROFILE=<profile> \
  docker compose -f deploy/docker-compose.yml up --build
```

This runs the same image, auth mode and surface. A named volume stands in for
EFS, your `~/.aws` is mounted read-only for STS and Bedrock, and the service
listens on `127.0.0.1:7799`. Set `CAMPY_IAM_WORKSPACE_MAP_JSON` to map two of
your roles to different workspaces, to see isolation end to end.

## 8. Status and known gaps

**Covered by tests:** `tests/test_cloud_deployment_readiness.py` and
`tests/test_http_workspace_isolation.py`. They cover the env overrides, the
bind guard, the minimal route surface, `/health`, per-workspace REST and
dashboard isolation, the container config, and the entrypoint. They also
check that every `CAMPY_*` variable the deployment files set is one the
daemon actually reads.

**Not yet verified:**
- **The image build.** The development sandbox these files were written in
  could not reach any container registry or huggingface.co. Build it once
  where those are reachable before relying on it.
- **Auto-scaling.** It needs a store that isn't single-writer (section 3).
- **OIDC auth.** It is accepted as configuration but not implemented;
  startup refuses it.
