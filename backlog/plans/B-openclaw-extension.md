# B-OpenClaw-Extension — SideQuests Brain as OpenClaw Memory Plugin

## Overview

Build a TypeScript OpenClaw extension that makes SideQuests Brain the memory system for OpenClaw/NemoClaw agents. The extension is a thin bridge — no memory logic, no database code. It forwards all memory operations to the Brain Daemon via the SSE/MCP endpoint at `http://127.0.0.1:7799/sse`.

OpenClaw's memory plugin slot is exclusive — only one memory plugin active at a time. We register as `kind: "memory"` to replace their built-in memory (SQLite-vec or LanceDB) with the full Gated Consolidation Loop.

**The extension does 4 things:**
1. Registers SideQuests MCP tools as OpenClaw tools (LLM can call them)
2. Hooks `llm_input` → forwards user turns to `notify_turn` (passive ingestion)
3. Hooks `llm_output` → forwards assistant turns to `notify_turn` (passive ingestion)
4. Hooks `before_agent_start` → calls `current_truth` to inject relevant context

## Architecture

```
OpenClaw Agent (TypeScript)
  └── sidequests-brain extension
        ├── Registers tools (current_truth, notify_turn, etc.)
        ├── Hooks llm_input/llm_output → notify_turn (passive)
        ├── Hooks before_agent_start → current_truth (auto-recall)
        └── Connects to Brain Daemon via HTTP
              └── http://127.0.0.1:7799/mcp (JSON-RPC POST)
```

**Why HTTP POST, not SSE:** The SSE endpoint (`/sse`) is for long-lived streaming connections (ChatGPT Desktop). For an extension making discrete tool calls, direct HTTP POST to `/mcp` is simpler and more reliable. The Brain Daemon's `/mcp` endpoint accepts JSON-RPC 2.0 requests directly.

## Files to Read First

| File | Why |
|------|-----|
| `web/server.py` | Brain Daemon's `/mcp` endpoint — the target for all calls |
| `mcp_engine/tool_schemas.py` | Canonical tool definitions to mirror as OpenClaw tools |
| `plugin/.mcp.json` | SSE endpoint URL reference |

Also read (in the OpenClaw repo after install):
| File | Why |
|------|-----|
| `extensions/memory-lancedb/index.ts` | Reference implementation — closest example |
| `extensions/memory-lancedb/openclaw.plugin.json` | Plugin manifest format |
| `src/plugins/types.ts` | Plugin API types (registerTool, on, etc.) |

## Implementation

### File Structure

```
extensions/hippocampy/
├── openclaw.plugin.json     # Plugin manifest
├── package.json             # npm package metadata
├── tsconfig.json            # TypeScript config
└── src/
    └── index.ts             # Main extension (~200 lines)
```

### Phase 1: Plugin Manifest

**File: `extensions/hippocampy/openclaw.plugin.json`**

```json
{
  "id": "sidequests-brain",
  "kind": "memory",
  "name": "SideQuests Brain",
  "description": "Graph-native AI memory powered by the Gated Consolidation Loop. Automatically captures decisions, constraints, and plans — then recalls them with full context across sessions.",
  "version": "0.1.0",
  "uiHints": {
    "brainUrl": {
      "label": "Brain Daemon URL",
      "placeholder": "http://127.0.0.1:7799",
      "help": "URL of the SideQuests Brain Daemon (must be running locally)"
    }
  },
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "brainUrl": {
        "type": "string",
        "default": "http://127.0.0.1:7799"
      },
      "autoCapture": {
        "type": "boolean",
        "default": true
      },
      "autoRecall": {
        "type": "boolean",
        "default": true
      },
      "sessionId": {
        "type": "string",
        "description": "Override session ID (auto-generated if omitted)"
      }
    }
  }
}
```

### Phase 2: Package Configuration

**File: `extensions/hippocampy/package.json`**

```json
{
  "name": "@sidequests/openclaw-brain",
  "version": "0.1.0",
  "description": "SideQuests Brain memory plugin for OpenClaw",
  "type": "module",
  "main": "src/index.ts",
  "openclaw": {
    "extensions": ["./src/index.ts"],
    "install": {
      "localPath": "extensions/hippocampy",
      "defaultChoice": "local"
    }
  },
  "dependencies": {
    "@sinclair/typebox": "^0.32.0"
  },
  "peerDependencies": {
    "openclaw": "*"
  }
}
```

**File: `extensions/hippocampy/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src"]
}
```

### Phase 3: Main Extension

**File: `extensions/hippocampy/src/index.ts`**

```typescript
/**
 * SideQuests Brain — OpenClaw Memory Extension
 *
 * Thin bridge between OpenClaw's plugin API and the SideQuests Brain Daemon.
 * All memory logic lives in the Brain Daemon (Python). This extension only:
 * 1. Registers MCP tools as OpenClaw tools
 * 2. Forwards LLM turns to notify_turn (passive ingestion)
 * 3. Injects current_truth results before agent starts (auto-recall)
 */

import { Type } from "@sinclair/typebox";

// ---------------------------------------------------------------------------
// Brain Daemon MCP client
// ---------------------------------------------------------------------------

interface BrainConfig {
  brainUrl: string;
  autoCapture: boolean;
  autoRecall: boolean;
  sessionId?: string;
}

class BrainClient {
  private baseUrl: string;
  private requestId = 0;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  /**
   * Call an MCP tool on the Brain Daemon via JSON-RPC 2.0 POST to /mcp.
   * The SSE endpoint issues a connection_id on GET /sse, then accepts
   * JSON-RPC POSTs at /mcp?connection_id=<id>. For simplicity, we
   * first GET /sse to obtain a connection_id, then POST to /mcp.
   */
  async callTool(toolName: string, args: Record<string, unknown>): Promise<unknown> {
    // Step 1: Get a connection ID from the SSE endpoint
    const sseResp = await fetch(`${this.baseUrl}/sse`);
    const reader = sseResp.body?.getReader();
    if (!reader) throw new Error("No SSE stream");

    const decoder = new TextDecoder();
    let connectionId = "";

    // Read until we get the endpoint event with connection_id
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const match = text.match(/connection_id=([a-f0-9-]+)/);
      if (match) {
        connectionId = match[1];
        break;
      }
    }
    reader.cancel();

    if (!connectionId) throw new Error("Failed to get connection ID from SSE");

    // Step 2: POST JSON-RPC to /mcp with the connection_id
    const rpcRequest = {
      jsonrpc: "2.0",
      id: ++this.requestId,
      method: "tools/call",
      params: { name: toolName, arguments: args },
    };

    const resp = await fetch(
      `${this.baseUrl}/mcp?connection_id=${connectionId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(rpcRequest),
      }
    );

    if (!resp.ok) throw new Error(`Brain returned ${resp.status}`);

    const rpcResp = await resp.json();
    if (rpcResp.error) throw new Error(rpcResp.error.message);

    // Extract text content from MCP response
    const content = rpcResp.result?.content;
    if (content?.[0]?.type === "text") {
      try {
        return JSON.parse(content[0].text);
      } catch {
        return content[0].text;
      }
    }
    return rpcResp.result;
  }

  async ping(): Promise<boolean> {
    try {
      // Just check if the SSE endpoint responds
      const resp = await fetch(`${this.baseUrl}/sse`, {
        signal: AbortSignal.timeout(2000),
      });
      resp.body?.cancel();
      return resp.ok;
    } catch {
      return false;
    }
  }
}

// ---------------------------------------------------------------------------
// Session ID generation
// ---------------------------------------------------------------------------

function generateSessionId(): string {
  return `oc-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Plugin entry point
// ---------------------------------------------------------------------------

// Use dynamic import or require for OpenClaw plugin SDK
// The exact import path depends on OpenClaw's module resolution.
// Adapt this import to match the installed OpenClaw version.

export default {
  id: "sidequests-brain",
  name: "SideQuests Brain",
  description: "Graph-native AI memory with Gated Consolidation Loop",
  kind: "memory" as const,

  register(api: any) {
    // Parse config
    const cfg: BrainConfig = {
      brainUrl: api.pluginConfig?.brainUrl || "http://127.0.0.1:7799",
      autoCapture: api.pluginConfig?.autoCapture ?? true,
      autoRecall: api.pluginConfig?.autoRecall ?? true,
      sessionId: api.pluginConfig?.sessionId,
    };

    const brain = new BrainClient(cfg.brainUrl);
    let sessionId = cfg.sessionId || generateSessionId();

    // -------------------------------------------------------------------
    // 1. Register tools — core memory tools for explicit LLM use
    // -------------------------------------------------------------------

    api.registerTool(
      {
        name: "memory_recall",
        label: "Memory Recall (SideQuests)",
        description:
          "Search the Brain's knowledge graph for relevant decisions, constraints, and context. " +
          "Call before answering questions about past choices or architecture.",
        parameters: Type.Object({
          query: Type.String({ description: "Natural language search query" }),
          scope: Type.Optional(
            Type.String({
              description: "Search scope: branch (current quest), global, or both",
              default: "both",
            })
          ),
          limit: Type.Optional(
            Type.Number({ description: "Max results to return", default: 10 })
          ),
        }),
        async execute(_toolCallId: string, params: any) {
          const result = await brain.callTool("current_truth", {
            query: params.query,
            session_id: sessionId,
            scope: params.scope || "both",
            limit: params.limit || 10,
          });
          return {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          };
        },
      },
      { name: "memory_recall" }
    );

    api.registerTool(
      {
        name: "memory_store",
        label: "Notify Brain (SideQuests)",
        description:
          "Forward a message to the Brain for processing. The Brain decides what to remember " +
          "via its Gated Consolidation Loop — you don't need to decide what's important.",
        parameters: Type.Object({
          role: Type.String({ description: "Message role: user or assistant" }),
          content: Type.String({ description: "Message content to process" }),
        }),
        async execute(_toolCallId: string, params: any) {
          const result = await brain.callTool("notify_turn", {
            role: params.role,
            content: params.content,
            session_id: sessionId,
          });
          return {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          };
        },
      },
      { name: "memory_store" }
    );

    api.registerTool(
      {
        name: "memory_search_analogies",
        label: "Cross-Quest Search (SideQuests)",
        description:
          "Search across all quests for analogous patterns, decisions, or lessons learned.",
        parameters: Type.Object({
          query: Type.String({ description: "Search query for cross-quest patterns" }),
          limit: Type.Optional(
            Type.Number({ description: "Max results", default: 5 })
          ),
        }),
        async execute(_toolCallId: string, params: any) {
          const result = await brain.callTool("analogical_search", {
            query: params.query,
            session_id: sessionId,
            limit: params.limit || 5,
          });
          return {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          };
        },
      },
      { name: "memory_search_analogies" }
    );

    api.registerTool(
      {
        name: "memory_status",
        label: "Context Status (SideQuests)",
        description:
          "Check context window health — token usage, loaded knowledge, and session info.",
        parameters: Type.Object({}),
        async execute() {
          const result = await brain.callTool("context_status", {
            session_id: sessionId,
          });
          return {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          };
        },
      },
      { name: "memory_status" }
    );

    api.registerTool(
      {
        name: "memory_open_loops",
        label: "Open Loops (SideQuests)",
        description:
          "Retrieve unresolved tentative knowledge nodes for review.",
        parameters: Type.Object({
          scope: Type.Optional(Type.String({ default: "both" })),
          limit: Type.Optional(Type.Number({ default: 10 })),
        }),
        async execute(_toolCallId: string, params: any) {
          const result = await brain.callTool("get_open_loops", {
            scope: params.scope || "both",
            limit: params.limit || 10,
          });
          return {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          };
        },
      },
      { name: "memory_open_loops" }
    );

    // -------------------------------------------------------------------
    // 2. Passive ingestion — forward all LLM turns to the Brain
    // -------------------------------------------------------------------

    if (cfg.autoCapture) {
      // Capture user turns
      api.on("llm_input", async (event: any) => {
        try {
          // event.prompt contains the user's message
          if (event.prompt) {
            await brain.callTool("notify_turn", {
              role: "user",
              content:
                typeof event.prompt === "string"
                  ? event.prompt
                  : JSON.stringify(event.prompt),
              session_id: sessionId,
            });
          }
        } catch {
          // Non-critical — don't break the agent over ingestion failure
        }
      });

      // Capture assistant turns
      api.on("llm_output", async (event: any) => {
        try {
          // event.assistantTexts contains the LLM's response(s)
          const texts = event.assistantTexts;
          if (texts && texts.length > 0) {
            const content = texts.join("\n");
            await brain.callTool("notify_turn", {
              role: "assistant",
              content,
              session_id: sessionId,
            });
          }
        } catch {
          // Non-critical
        }
      });
    }

    // -------------------------------------------------------------------
    // 3. Auto-recall — inject relevant context before agent starts
    // -------------------------------------------------------------------

    if (cfg.autoRecall) {
      api.on("before_agent_start", async (event: any) => {
        try {
          const query =
            typeof event.prompt === "string"
              ? event.prompt
              : JSON.stringify(event.prompt);

          if (!query || query.length < 5) return {};

          const result: any = await brain.callTool("current_truth", {
            query,
            session_id: sessionId,
            scope: "both",
            limit: 5,
          });

          if (result?.results && result.results.length > 0) {
            const context = result.results
              .map(
                (r: any) =>
                  `[${r.node_type}] ${r.text_raw} (strength: ${r.pathway_strength?.toFixed(2) || "?"})`
              )
              .join("\n");

            return {
              prependContext: `<sidequests-memory>\n${context}\n</sidequests-memory>`,
            };
          }
        } catch {
          // Non-critical — agent proceeds without memory injection
        }
        return {};
      });
    }

    // -------------------------------------------------------------------
    // 4. Service registration — health check on startup
    // -------------------------------------------------------------------

    api.registerService?.({
      id: "sidequests-brain",
      async start() {
        const alive = await brain.ping();
        if (alive) {
          console.log(
            `[SideQuests Brain] Connected to Brain Daemon at ${cfg.brainUrl}`
          );
        } else {
          console.warn(
            `[SideQuests Brain] Brain Daemon not reachable at ${cfg.brainUrl}. ` +
              `Memory tools will fail until the daemon is started.`
          );
        }
      },
      async stop() {
        // Nothing to clean up — Brain Daemon manages its own lifecycle
      },
    });
  },
};
```

### Phase 4: OpenClaw Configuration

After installing the extension, users add this to their `openclaw.json`:

```json
{
  "plugins": {
    "slots": {
      "memory": "sidequests-brain"
    }
  },
  "extensions": {
    "sidequests-brain": {
      "brainUrl": "http://127.0.0.1:7799",
      "autoCapture": true,
      "autoRecall": true
    }
  }
}
```

## Tool Mapping

| OpenClaw Tool Name | Brain MCP Tool | Purpose |
|-------------------|----------------|---------|
| `memory_recall` | `current_truth` | Search knowledge graph for relevant context |
| `memory_store` | `notify_turn` | Forward message for processing by Consolidation Loop |
| `memory_search_analogies` | `analogical_search` | Cross-quest pattern search |
| `memory_status` | `context_status` | Context window health check |
| `memory_open_loops` | `get_open_loops` | Unresolved tentative knowledge |

**Why rename tools:** OpenClaw's memory plugin convention uses `memory_*` prefix. Using our MCP names directly would confuse the LLM and not match OpenClaw's existing patterns. The mapping is transparent — each OpenClaw tool calls exactly one Brain MCP tool.

**Tools NOT exposed:** `branch_quest`, `complete_quest`, `set_quest`, `diff_since`, `explore_graph`, `ingest_document` — these are quest management tools, not memory operations. They can be added later if needed, or used directly via mcporter.

## Hook Behavior

| Hook | Fires When | Action | Critical? |
|------|-----------|--------|-----------|
| `llm_input` | User sends message to LLM | `notify_turn(role="user")` | No — fire-and-forget |
| `llm_output` | LLM generates response | `notify_turn(role="assistant")` | No — fire-and-forget |
| `before_agent_start` | Before LLM processes user message | `current_truth(query)` → inject context | No — agent proceeds without if Brain is down |

All hooks are non-critical — if the Brain Daemon is unreachable, the agent continues normally without memory. This matches the Brain's design philosophy: memory is additive, never blocking.

## Files to Create

| File | Description |
|------|-------------|
| `extensions/hippocampy/openclaw.plugin.json` | Plugin manifest |
| `extensions/hippocampy/package.json` | npm package config |
| `extensions/hippocampy/tsconfig.json` | TypeScript config |
| `extensions/hippocampy/src/index.ts` | Main extension (~200 lines) |

## Files to Modify

None — this is a standalone extension. No changes to the Brain Daemon or existing MCP code.

## What NOT to Do

- Do NOT add memory logic to the extension — all intelligence lives in the Brain Daemon
- Do NOT register as a regular extension — use `kind: "memory"` to replace OpenClaw's built-in memory
- Do NOT use the SSE streaming endpoint for tool calls — use HTTP POST to `/mcp`
- Do NOT block the agent if the Brain is unreachable — all hooks are non-critical
- Do NOT expose quest management tools (branch_quest, etc.) — keep it focused on memory

## Verification

1. Extension loads without errors in OpenClaw: `openclaw --extensions=sidequests-brain`
2. `memory_recall` returns results from the Brain's knowledge graph
3. `memory_store` forwards to Brain and returns `{"status": "queued"}`
4. Passive ingestion: user and assistant turns appear in the Brain's graph after a conversation
5. Auto-recall: relevant context injected before agent starts (visible in `<sidequests-memory>` tags)
6. Graceful degradation: agent works normally if Brain Daemon is not running
7. Session ID persists across tool calls within a single agent session

## Notes

- **SSE connection pattern:** The `/mcp` endpoint requires a `connection_id` obtained from `GET /sse`. The `BrainClient` handles this automatically — gets a connection ID, makes the POST, then discards the SSE connection. This is slightly wasteful (one SSE connect per tool call). If performance matters, we can hold the SSE connection open and reuse the connection_id. Optimize later if needed.

- **OpenClaw version compatibility:** This extension targets OpenClaw's current plugin API (as of March 2026). The `api: any` typing is intentional — avoids hard dependency on a specific OpenClaw SDK version. Replace with proper types once the SDK stabilizes.

- **NemoClaw sandbox:** If running inside NemoClaw's OpenShell sandbox, the network policy must allow outbound connections to `127.0.0.1:7799`. The Brain Daemon runs on the host, not inside the sandbox. This may require a NemoClaw configuration change.
