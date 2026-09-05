# VibeGuide Integration Guide: Campy Agent Memory Service

**Audience:** VibeGuide Platform Engineering & Agent Architecture Teams  
**Target Runtime:** AWS ECS/Fargate (0.25 vCPU, 0.5 GB RAM) backed by Amazon EFS  
**Service Ingress:** AWS Application Load Balancer / Bedrock Gateway (`POST /mcp` and `/api/v1/*`)  
**Security Model:** AWS IAM SigV4 Authentication + Physical Workspace Sharding

---

## 1. Overview

Campy serves as the neurosymbolic long-term memory engine for VibeGuide's coding agents and build-workers. It bridges immediate session contexts with cross-session learnings, constraints, and architecture decisions while eliminating context rot and token bloat.

In cloud deployment, Campy operates as a managed multi-tenant service running on AWS ECS/Fargate. Each VibeGuide project, agent, or evaluation run is mapped to a physically isolated graph and vector store on Amazon EFS via Campy's `WorkspaceRouter`.

---

## 2. Authentication & Tenancy Model

### SigV4 Authentication
All requests to Campy (except `GET /health`) require AWS Signature Version 4 (SigV4) headers:
- `Authorization`: `AWS4-HMAC-SHA256 Credential=...`
- `X-Amz-Date`: `YYYYMMDD'T'HHMMSS'Z'`
- `X-Amz-Security-Token`: (Session token if using temporary STS credentials)

Campy's `IAMPrincipalResolver` verifies inbound requests against AWS STS `GetCallerIdentity`. Verified caller ARNs are cached for 15 minutes to eliminate latency and avoid STS rate limits.

### Workspace Mapping & Isolation
1. **Operator Policy (Authoritative):**  
   The Campy deployment binds VibeGuide's IAM Role ARN to an authoritative tenant and default workspace via configuration:
   ```json
   {
     "arn:aws:iam::123456789012:role/vibeguide-agent-role": "vibeguide-prod"
   }
   ```
2. **Dynamic Workspace Selection (`X-Campy-Workspace-Id`):**  
   To shard memory by project or build-worker, VibeGuide agents can supply the `X-Campy-Workspace-Id` header:
   ```http
   X-Campy-Workspace-Id: project-alpha
   ```
   If the operator policy authorizes workspace switching, Campy routes all graph and vector queries directly to that workspace's physical database shard. Unmapped callers attempting to specify arbitrary workspaces are rejected with HTTP 403 / IAMConfigError.

---

## 3. Integration Protocols

VibeGuide can interact with Campy via either **Streamable-HTTP MCP** or **Direct REST Endpoints**. Both interfaces share the identical underlying tool execution pipeline, secret scrubber, and workspace router.

### Option A: Streamable-HTTP MCP (`POST /mcp`)
Standard Model Context Protocol (MCP 2025-03-26) over HTTP.

```http
POST /mcp HTTP/1.1
Host: campy.internal.vibeguide.io:7799
Authorization: AWS4-HMAC-SHA256 ...
X-Amz-Date: 20260904T120000Z
X-Campy-Workspace-Id: project-alpha
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "current_truth",
    "arguments": {
      "query": "authentication requirements",
      "scope": "both"
    }
  }
}
```

### Option B: Direct REST Endpoints (`/api/v1/*`)
Lightweight REST routes optimized for build-worker scripts and headless services without full MCP client overhead:

#### 1. Ingest Conversation Turn / Lesson
```http
POST /api/v1/notify HTTP/1.1
Host: campy.internal.vibeguide.io:7799
Authorization: AWS4-HMAC-SHA256 ...
X-Amz-Date: 20260904T120000Z
X-Campy-Workspace-Id: project-alpha
Content-Type: application/json

{
  "role": "user",
  "content": "All cloud deployments must use IAM SigV4 authentication on all HTTP endpoints.",
  "session_id": "build-worker-492"
}
```

#### 2. Retrieve Active Truth & Constraints
```http
GET /api/v1/recall?q=auth+requirements&scope=both HTTP/1.1
Host: campy.internal.vibeguide.io:7799
Authorization: AWS4-HMAC-SHA256 ...
X-Amz-Date: 20260904T120000Z
X-Campy-Workspace-Id: project-alpha
```

#### 3. Compile Token-Budgeted Context Bundle
```http
POST /api/v1/bundle HTTP/1.1
Host: campy.internal.vibeguide.io:7799
Authorization: AWS4-HMAC-SHA256 ...
X-Amz-Date: 20260904T120000Z
X-Campy-Workspace-Id: project-alpha
Content-Type: application/json

{
  "query": "refactor authentication middleware",
  "token_budget": 16000,
  "agent_type": "coding"
}
```

#### 4. Service Health Probe (Unauthenticated)
```http
GET /health HTTP/1.1
Host: campy.internal.vibeguide.io:7799
```
Response:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "rss_mb": 68.42,
  "workspaces_open": 3
}
```

---

## 4. Security, Scrubbing & Guardrails

1. **Content Secret Scrubbing**: All text ingested into Campy passes through `scrub_before_ingest()` prior to persisting into the graph. API keys, JWTs, AWS credentials, and SSH private keys are automatically redacted.
2. **Prompt Injection Boundary**: Recalled memory nodes are formatted using tagged boundaries:
   ```html
   <retrieved_memory source="hippocampus" trust="stored_data">
   ...
   </retrieved_memory>
   ```
   This prevents recalled data from executing arbitrary instructions against LLMs.
3. **Contradiction Auditing**: Contradictory beliefs or superseded constraints are demoted via `[DEPRECATED_BY]` relationships and excluded from active recall prompts.
4. **Physical Storage Partitioning**: No shared tables or database-level `tenant_id` WHERE clauses. Every workspace lives in an isolated filesystem directory on EFS (`/data/campy/<workspace>-<hash>/`).
