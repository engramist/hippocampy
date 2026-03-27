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
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

// ---------------------------------------------------------------------------
// Brain Daemon MCP client
// ---------------------------------------------------------------------------

interface BrainConfig {
  brainUrl: string;
  autoCapture: boolean;
  autoRecall: boolean;
  sessionId?: string;
  autoLaunch?: boolean;  // opt-in: attempt to start daemon if not running (default: false)
}

// ---------------------------------------------------------------------------
// Service status helpers
// ---------------------------------------------------------------------------

/** Return true if the launchd plist for the Brain Daemon exists on disk. */
function isLaunchdServiceInstalled(): boolean {
  const plistPath = path.join(
    os.homedir(),
    "Library",
    "LaunchAgents",
    "ai.sidequests.brain.plist"
  );
  return fs.existsSync(plistPath);
}

/** Return true if a systemd user service unit file exists for the Brain Daemon. */
function isSystemdServiceInstalled(): boolean {
  const unitPath = path.join(
    os.homedir(),
    ".config",
    "systemd",
    "user",
    "sidequests-brain.service"
  );
  return fs.existsSync(unitPath);
}

/** Return true if the Brain Daemon is registered as a persistent user service. */
function isDaemonServiceInstalled(): boolean {
  if (process.platform === "darwin") return isLaunchdServiceInstalled();
  if (process.platform === "linux") return isSystemdServiceInstalled();
  return false;
}

class BrainClient {
  private baseUrl: string;
  private requestId = 0;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  /**
   * Call an MCP tool on the Brain Daemon via Streamable HTTP.
   * Simple POST to /mcp, result comes back directly in response body.
   */
  async callTool(toolName: string, args: Record<string, unknown>): Promise<unknown> {
    const rpcRequest = {
      jsonrpc: "2.0",
      id: ++this.requestId,
      method: "tools/call",
      params: { name: toolName, arguments: args },
    };

    const resp = await fetch(`${this.baseUrl}/mcp`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
      },
      body: JSON.stringify(rpcRequest),
    });

    if (!resp.ok) {
      throw new Error(`Brain returned HTTP ${resp.status}`);
    }

    const rpcResp = await resp.json();

    if (rpcResp.error) {
      throw new Error(`MCP error ${rpcResp.error.code}: ${rpcResp.error.message}`);
    }

    // Extract text content from MCP tool result
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
      const resp = await fetch(`${this.baseUrl}/mcp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 0,
          method: "initialize",
          params: {},
        }),
        signal: AbortSignal.timeout(3000),
      });
      if (!resp.ok) return false;
      const data = await resp.json();
      return !!data.result?.serverInfo;
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
      // autoLaunch is opt-in and disabled by default.
      // Enable only if you want the plugin to attempt launching the daemon
      // when it is unreachable. Warning: may produce duplicate daemon instances
      // if the daemon is slow to start. Prefer the launchd/systemd service path.
      autoLaunch: api.pluginConfig?.autoLaunch ?? false,
    };

    const brain = new BrainClient(cfg.brainUrl);
    let sessionId = cfg.sessionId || generateSessionId();

    // -------------------------------------------------------------------
    // 1. Register tools — core memory tools for explicit LLM use
    // -------------------------------------------------------------------

    console.log("[SideQuests Brain] Registering 7 memory tools...");

    const recallToolParams = Type.Object({
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
    });

    const registerRecallTool = (
      name: string,
      label: string,
      description: string,
    ) => {
      api.registerTool(
        {
          name,
          label,
          description,
          parameters: recallToolParams,
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
        { name }
      );
    };

    registerRecallTool(
      "memory_recall",
      "Memory Recall (SideQuests)",
      "Search the Brain's knowledge graph for relevant decisions, constraints, and context. " +
        "Call before answering questions about past choices or architecture.",
    );

    registerRecallTool(
      "memory_search",
      "Memory Search (SideQuests)",
      "Alias for memory_recall. Search the Brain's knowledge graph for relevant decisions, constraints, and context.",
    );

    registerRecallTool(
      "memory_get",
      "Memory Get (SideQuests)",
      "Alias for memory_recall. Fetch relevant memory context from the Brain using a natural-language query.",
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

    console.log("[SideQuests Brain] All 7 tools registered: memory_recall, memory_search, memory_get, memory_store, memory_search_analogies, memory_status, memory_open_loops");

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
            `[SideQuests Brain] Connected to Brain Daemon at ${cfg.brainUrl} (Streamable HTTP)`
          );
          return;
        }

        // Daemon not reachable — give a diagnostic-quality warning.
        const serviceInstalled = isDaemonServiceInstalled();

        if (!serviceInstalled) {
          // Most actionable case: daemon was never configured as a service.
          console.warn(
            `[SideQuests Brain] Brain Daemon not running and no persistent service found. ` +
              `Run \`sidequests install\` or \`sidequests setup\` to register the daemon as a ` +
              `login-time background service (launchd on macOS, systemd on Linux). ` +
              `Memory tools will be unavailable until the daemon is started.`
          );
        } else {
          // Service is installed — this is a transient failure (crash, slow start, etc.)
          console.warn(
            `[SideQuests Brain] Brain Daemon service is registered but not currently reachable ` +
              `at ${cfg.brainUrl}. The service should restart automatically. ` +
              `If it stays offline, run \`sidequests status\` to diagnose.`
          );
        }

        // Opt-in auto-launch fallback — disabled by default to avoid duplicate daemon risk.
        if (cfg.autoLaunch && !serviceInstalled) {
          console.log(
            `[SideQuests Brain] autoLaunch is enabled — attempting to start daemon...`
          );
          try {
            const { spawn } = await import("child_process");
            // Find sidequests-daemon in PATH or fall back to python -m sidequests
            const { execSync } = await import("child_process");
            let daemonCmd: string;
            try {
              daemonCmd = execSync("which sidequests-daemon", { encoding: "utf8" }).trim();
            } catch {
              daemonCmd = "";
            }
            if (daemonCmd) {
              spawn(daemonCmd, [], {
                detached: true,
                stdio: "ignore",
              }).unref();
            } else {
              spawn("python3", ["-m", "sidequests.daemon"], {
                detached: true,
                stdio: "ignore",
              }).unref();
            }
            // Wait briefly then re-check
            await new Promise((resolve) => setTimeout(resolve, 3000));
            const retryAlive = await brain.ping();
            if (retryAlive) {
              console.log(
                `[SideQuests Brain] Auto-launch succeeded — daemon is now reachable.`
              );
            } else {
              console.warn(
                `[SideQuests Brain] Auto-launch attempted but daemon still not reachable. ` +
                  `Check ~/.sidequests/daemon.log for errors.`
              );
            }
          } catch (err: any) {
            console.warn(
              `[SideQuests Brain] Auto-launch failed: ${err?.message ?? err}`
            );
          }
        }
      },
      async stop() {
        // Nothing to clean up — Brain Daemon manages its own lifecycle via launchd/systemd.
      },
    });
  },
};
