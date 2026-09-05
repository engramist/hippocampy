# B-385-cloud-vibeguide-service — Cloud Deployment Foundation & VibeGuide Multi-Tenant Agent Memory Service (AWS ECS/Fargate)

**Card:** B385 | **Priority:** P0 | **Depends on:** B315, B316, B325, B328, B384  
**Branch:** `feat/b385-cloud-vibeguide-service` | **PR Target:** `main`  
**Target Consumer:** VibeGuide (First External Customer & Evaluation Partner)

---

## 1. Summary

Transition Campy from a local-only daemon into an enterprise-ready, containerized, multi-tenant agent memory service running on AWS ECS/Fargate. The primary customer is **VibeGuide**, which requires multi-session memory persistence across build-workers and coding agents without cross-tenant memory leakage or runaway cloud costs.

Leveraging B384's <80 MB engine foundation, Campy runs continuously on AWS Fargate's smallest, most cost-effective tier (0.25 vCPU, 0.5 GB RAM) backed by an Amazon EFS persistent volume for physical workspace isolation via `WorkspaceRouter`.

---

## 2. Architecture & Multi-Tenant Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│ VibeGuide Cloud Environment                                            │
│                                                                        │
│   ┌───────────────────────────┐      ┌─────────────────────────────┐   │
│   │ VibeGuide AgentCore       │      │ VibeGuide Platform          │   │
│   │ Lambda Proxy              │      │ Build-Worker Fleet          │   │
│   └─────────────┬─────────────┘      └──────────────┬──────────────┘   │
│                 │                                   │                  │
│                 │ SigV4 (POST /mcp)                 │ SigV4 (REST)     │
└─────────────────┼───────────────────────────────────┼──────────────────┘
                  │                                   │
                  ▼                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ AWS Application Load Balancer / Bedrock Gateway                        │
│ (HTTPS Ingress :443 -> Target Group :7799)                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ AWS ECS / Fargate Service (0.25 vCPU, 0.5 GB RAM)                      │
│                                                                        │
│   Campy Cloud Container (python:3.12-slim, non-root uid 1000)          │
│   ├── FastEmbed ONNX Cache (/app/.cache/fastembed) [Pre-baked]         │
│   ├── Global SigV4 IAM Middleware (STS GetCallerIdentity Cached)       │
│   ├── Ingress Routes:                                                  │
│   │   ├── GET  /health           (Unauthenticated Target Group probe)  │
│   │   ├── POST /mcp              (SigV4 Streamable-HTTP MCP)           │
│   │   ├── GET  /sse              (SigV4 SSE Stream)                    │
│   │   └── ANY  /api/v1/*         (SigV4 REST Endpoints)                │
│   └── Multi-Tenant Workspace Dispatch:                                 │
│       └── WorkspaceRouter.get(principal.workspace_id)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ POSIX I/O
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Amazon EFS Multi-AZ Persistent Storage (/data/campy)                   │
│                                                                        │
│ ├── workspaces/                                                        │
│ │   ├── vibeguide-prod-<hash>/                                         │
│ │   │   ├── graph/ (Oxigraph RocksDB store)                            │
│ │   │   └── vectors.db (sqlite-vec 384-dim cosine index)               │
│ │   ├── vibeguide-buildworker-1-<hash>/                                │
│ │   └── tenant-sandbox-b-<hash>/                                       │
│ └── config/                                                            │
│     └── campy.toml                                                     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Approach

### Task 1: 12-Factor Path & Configuration Abstraction
- In `campy/paths.py`:
  - Check `os.environ.get("CAMPY_HOME")` or `os.environ.get("CAMPY_DATA_DIR")`. If set, use that absolute directory as the root for `runtime_dir()`, `get_database_path()`, and `get_workspace_root()`.
  - Maintains 100% backward compatibility for local desktop users (`~/.campy` or legacy `~/.sidequests`).
- In `campy/brain/brainstem/config.py`:
  - Allow environment variables to override `campy.toml` values:
    - `CAMPY_SERVER_BIND_HOST` -> `config["server"]["bind_host"]`
    - `CAMPY_SERVER_AUTH` -> `config["server"]["auth"]`
    - `CAMPY_SERVER_DASHBOARD_ENABLED` -> `config["server"]["dashboard_enabled"]`
    - `CAMPY_IAM_WORKSPACE_MAP_JSON` -> parsed JSON dict merged into `config["server"]["iam_workspace_map"]`
    - `CAMPY_IAM_TENANT_MAP_JSON` -> parsed JSON dict merged into `config["server"]["iam_tenant_map"]`

### Task 2: REST & Ingress Surface Hardening
- In `web/server.py`:
  - When `_dashboard_enabled = False`, update `allowed_paths` to preserve `/api/v1/*` routes in addition to `/health`, `/mcp`, and `/sse`.
  - Pass `router=_router` into `create_router(db=db, config=_config, router=_router)`.
  - Update `GET /health` to report memory RSS, storage mount health, uptime, and loaded workspace count without requiring authentication.
- In `campy/brain/brainstem/rest_api.py`:
  - Update `_call_tool()`: If `router` is provided and `request.state.principal` exists, dynamically borrow the database for that principal's workspace via `await router.get(principal.workspace_id)`.
  - Guarantees that VibeGuide's build-workers calling REST endpoints are isolated to their designated workspace with zero chance of reading or polluting other workspaces.

### Task 3: Production Containerization (`deploy/Dockerfile`)
- Multi-stage build based on `python:3.12-slim`.
- Installs necessary system libraries (e.g. `curl` for container health check).
- Pre-bakes the default FastEmbed model (`BAAI/bge-small-en-v1.5`) directly into the image at `/app/.cache/fastembed`.
- Sets environment variables:
  ```dockerfile
  ENV HF_HUB_OFFLINE=1 \
      TRANSFORMERS_OFFLINE=1 \
      FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
      CAMPY_HOME=/data/campy \
      CAMPY_SERVER_BIND_HOST=0.0.0.0 \
      CAMPY_SERVER_DASHBOARD_ENABLED=false
  ```
- Creates non-root user `campy` (UID 1000, GID 1000) and switches to it.
- Declares volume `/data/campy` for EFS mounting.
- Uses `HEALTHCHECK` probe against `http://localhost:7799/health`.
- Runs entrypoint starting the daemon / web server on port 7799.

### Task 4: AWS ECS/Fargate & Docker-Compose Assets
- `deploy/ecs-task-definition.json`:
  - 256 CPU units (0.25 vCPU), 512 MiB memory.
  - EFS volume configuration with `transitEncryption = ENABLED` and POSIX root directory `/campy`.
  - LogConfiguration pointing to AWS CloudWatch `/ecs/campy-memory-service`.
- `deploy/docker-compose.yml`:
  - Local multi-container verification harness with local volume mount emulating EFS.
  - Pre-configured with test IAM SigV4 environment.

### Task 5: VibeGuide Integration Guide (`docs/vibeguide-integration-guide.md`)
- Complete integration documentation for VibeGuide:
  - SigV4 signing specification and credentials setup.
  - Header contracts: `X-Campy-Workspace-Id`, `Authorization`, `X-Amz-Date`.
  - Sample Python / TypeScript code snippets for VibeGuide build-workers to ingest and recall memories over REST and MCP.
  - Privacy, secret scrubbing, and prompt injection defense disclosures.

---

## 4. Concrete File Changes

### Core Changes:
- `campy/paths.py`: Add `CAMPY_HOME` / `CAMPY_DATA_DIR` env var overrides.
- `campy/brain/brainstem/config.py`: Add 12-factor cloud env var loader.
- `web/server.py`: Allow `/api/v1/` in minimal mode; inject router to REST routes; enrich `/health`.
- `campy/brain/brainstem/rest_api.py`: Route DB calls via `router.get(principal.workspace_id)`.

### New Deployment Assets:
- `deploy/Dockerfile`
- `deploy/docker-compose.yml`
- `deploy/ecs-task-definition.json`
- `docs/vibeguide-integration-guide.md`

### Testing:
- `tests/test_cloud_deployment_readiness.py`: Comprehensive automated tests for env vars, path overrides, route filtering, and REST workspace routing.

---

## 5. Verification Plan

1. **Unit & Integration Tests:**
   ```bash
   pytest tests/test_cloud_deployment_readiness.py -v
   pytest tests/test_route_auth.py tests/test_auth_context.py tests/adapters/test_hermes_adapter.py -v
   pytest tests/test_workspace_router.py -v
   ```
2. **Security & Bind Guard Assertions:**
   Assert that setting `CAMPY_SERVER_BIND_HOST=0.0.0.0` with `CAMPY_SERVER_AUTH=none` immediately aborts process startup via `_enforce_bind_guard`.
3. **Container Build Verification:**
   Verify `deploy/Dockerfile` builds cleanly and executes in offline mode with pre-baked models.
