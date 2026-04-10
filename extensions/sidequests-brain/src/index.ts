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
  healthCheckIntervalMs?: number;  // B82: periodic daemon health ping interval (default: 30000)
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
// OpenClaw Passive Ingestion Contract
// ---------------------------------------------------------------------------

/**
 * OPENCLAW_EVENT_CONTRACT
 * Validated against OpenClaw core event system.
 *
 * userTurnEvent: Fired when user input is received. Expected payload: { prompt: string }
 * assistantTurnEvent: Fired when LLM output is generated. Expected payload: { assistantTexts: string[] }
 * preAgentEvent: Fired before an agent session starts. Expected payload: { prompt: string }
 *
 * Fallback: If payload fields are missing or empty, the hook skips processing
 * and logs a diagnostic warning.
 */
const OPENCLAW_EVENT_CONTRACT = {
  userTurnEvent: "llm_input",
  assistantTurnEvent: "llm_output",
  preAgentEvent: "before_agent_start",
  userPromptFields: ["prompt"],
  assistantTextFields: ["assistantTexts"],
} as const;

/**
 * Diagnostic helper: Summarize top-level keys and types of an event payload.
 */
function summarizeEventShape(event: any): string {
  if (!event || typeof event !== "object") return String(event);
  const keys = Object.keys(event);
  const summary = keys
    .map((k) => {
      const val = event[k];
      const type = Array.isArray(val) ? "array" : typeof val;
      return `${k}:${type}`;
    })
    .join(", ");
  return `{ ${summary} }`;
}

/**
 * Normalize user prompt payload from llm_input or before_agent_start.
 */
function normalizePromptPayload(event: any): string | null {
  const prompt = event?.prompt;
  if (prompt === undefined || prompt === null) return null;

  let normalized: string;
  if (typeof prompt === "string") {
    normalized = prompt;
  } else {
    try {
      normalized = JSON.stringify(prompt);
    } catch {
      normalized = String(prompt);
    }
  }

  return normalized.trim().length > 0 ? normalized : null;
}

/**
 * Normalize assistant output payload from llm_output.
 */
function normalizeAssistantPayload(event: any): string | null {
  const texts = event?.assistantTexts;
  if (texts === undefined || texts === null) return null;

  let normalized: string;
  if (Array.isArray(texts)) {
    normalized = texts
      .map((t) => (typeof t === "string" ? t : JSON.stringify(t)))
      .filter((t) => t.trim().length > 0)
      .join("\n");
  } else if (typeof texts === "string") {
    normalized = texts;
  } else {
    try {
      normalized = JSON.stringify(texts);
    } catch {
      normalized = String(texts);
    }
  }

  return normalized.trim().length > 0 ? normalized : null;
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
      healthCheckIntervalMs: Math.max(5000, Number(api.pluginConfig?.healthCheckIntervalMs ?? 30000)),
    };

    const brain = new BrainClient(cfg.brainUrl);
    let sessionId = cfg.sessionId || generateSessionId();
    let isOnline = false;
    let healthCheckInterval: any = null;

    // -------------------------------------------------------------------
    // 1. Register tools — core memory tools for explicit LLM use
    // -------------------------------------------------------------------

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

    const currentTruthParams = Type.Object({
      query: Type.String({ description: "Natural language search query" }),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
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

    const notifyTurnParams = Type.Object({
      role: Type.Union([
        Type.Literal("user"),
        Type.Literal("assistant"),
      ]),
      content: Type.String({ description: "Message content to process" }),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
    });

    const branchQuestParams = Type.Object({
      name: Type.String({ description: "Name of the SideQuest to create" }),
      purpose: Type.String({
        description: "Describe what differentiates this SideQuest from the main goal",
      }),
      parent_quest_id: Type.Optional(
        Type.String({ description: "Optional parent quest ID" })
      ),
    });

    const diffSinceParams = Type.Object({
      since_iso: Type.String({ description: "ISO timestamp to query changes since" }),
      limit: Type.Optional(
        Type.Number({ description: "Max results to return", default: 20 })
      ),
    });

    const openLoopsParams = Type.Object({
      quest_id: Type.Optional(Type.String({ description: "Optional quest filter" })),
      limit: Type.Optional(
        Type.Number({ description: "Max loops to return", default: 20 })
      ),
    });

    const analogicalSearchParams = Type.Object({
      query: Type.String({ description: "Search query for cross-quest patterns" }),
      current_quest_id: Type.Optional(
        Type.String({ description: "Exclude results from this quest" })
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max results", default: 5 })
      ),
      min_similarity: Type.Optional(
        Type.Number({ description: "Minimum similarity threshold", default: 0.7 })
      ),
    });

    const ingestDocumentParams = Type.Object({
      file_path: Type.String({ description: "Absolute path to the file to ingest" }),
      quest_id: Type.Optional(
        Type.String({ description: "Optional quest_id to tag the artifact" })
      ),
    });

    const exploreGraphParams = Type.Object({
      start_node_id: Type.String({
        description: "Node ID to start traversal (from current_truth results)",
      }),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
      depth: Type.Optional(
        Type.Number({
          description: "Number of hops to traverse",
          default: 3,
          minimum: 1,
          maximum: 5,
        })
      ),
      strategy: Type.Optional(
        Type.Union([
          Type.Literal("dfs"),
          Type.Literal("bfs"),
        ])
      ),
      edge_types: Type.Optional(Type.Array(Type.String())),
      direction: Type.Optional(
        Type.Union([
          Type.Literal("outgoing"),
          Type.Literal("incoming"),
          Type.Literal("both"),
        ])
      ),
    });

    const completeQuestParams = Type.Object({
      quest_id: Type.String({ description: "The quest_id to mark completed" }),
    });

    const setQuestParams = Type.Object({
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
      quest_name: Type.String({ description: "Quest name to bind this session" }),
      quest_id: Type.Optional(Type.String({ description: "Optional quest_id to target" })),
    });

    const contextStatusParams = Type.Object({
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
    });

    const openClawPromptParams = Type.Object({
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
    });

    const upsertLessonParams = Type.Object({
      text: Type.String({ description: "The lesson content" }),
      domain: Type.String({ description: "e.g., 'rust', 'react', 'ux'" }),
      lesson_type: Type.Union([
        Type.Literal("mistake"),
        Type.Literal("edge-case"),
        Type.Literal("optimization"),
        Type.Literal("architecture-principle"),
      ]),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
      lesson_id: Type.Optional(Type.String({ description: "Optional existing lesson" })),
    });

    const recallRelevantLessonsParams = Type.Object({
      query: Type.String({ description: "Semantic search query" }),
      domain: Type.Optional(Type.String({ description: "Optional domain filter" })),
      limit: Type.Optional(
        Type.Number({ description: "Max results", default: 5 })
      ),
    });

    const anomaliesParams = Type.Object({
      scope: Type.Optional(
        Type.String({
          description: "Scope of anomaly search",
          default: "branch",
        })
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max anomalies", default: 20 })
      ),
      quest_id: Type.Optional(Type.String({ description: "Optional quest filter" })),
    });

    const registerPlanParams = Type.Object({
      goal: Type.String({ description: "What this plan aims to achieve" }),
      steps: Type.Array(Type.String({ description: "Ordered step description" })),
      strategy: Type.Optional(
        Type.String({ description: "Optional high-level strategy" })
      ),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
    });

    const reportOutcomeParams = Type.Object({
      plan_id: Type.String({ description: "Plan ID returned by register_plan" }),
      step_number: Type.Optional(
        Type.Number({ description: "Optional step number for step-level update" })
      ),
      outcome: Type.String({ description: "What happened" }),
      valence: Type.Number({ description: "-1.0 failure to +1.0 success" }),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
      valence_source: Type.Optional(
        Type.String({ description: "user_feedback | exit_code | test_result | system" })
      ),
    });

    const recallPlansParams = Type.Object({
      goal_query: Type.String({ description: "Goal to search for similar plans" }),
      min_valence: Type.Optional(
        Type.Number({ description: "Minimum plan valence filter", default: 0 })
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max plans", default: 5 })
      ),
      session_id: Type.Optional(
        Type.String({ description: "OpenClaw session ID (auto-filled)" })
      ),
    });

    const reconstructTimelineParams = Type.Object({
      topic: Type.String({ description: "Topic to reconstruct a message/decision timeline for" }),
      session_id: Type.Optional(
        Type.String({ description: "Optional session filter (auto-filled)" })
      ),
      max_hops: Type.Optional(
        Type.Number({ description: "Maximum timeline hops to return", default: 20 })
      ),
      include_decisions: Type.Optional(
        Type.Boolean({ description: "Include decision nodes in the reconstructed timeline", default: true })
      ),
    });

    const knowledgeGapsParams = Type.Object({
      limit: Type.Optional(
        Type.Number({ description: "Maximum number of active gaps to return", default: 10 })
      ),
      unresolved_only: Type.Optional(
        Type.Boolean({ description: "Return only unresolved gaps", default: true })
      ),
      min_severity: Type.Optional(
        Type.Number({ description: "Minimum severity threshold", default: 0 })
      ),
    });

    const recallProceduresParams = Type.Object({
      archetype: Type.Optional(Type.String({ description: "Optional archetype filter" })),
      query: Type.Optional(Type.String({ description: "Optional semantic search query" })),
      limit: Type.Optional(
        Type.Number({ description: "Maximum reusable procedures to return", default: 3 })
      ),
    });

    type BrainToolDefinition = {
      name: string;
      label: string;
      description: string;
      parameters: any;
      callName?: string;
      transformParams?: (params: any) => Record<string, unknown>;
    };

    const recallTransform = (params: any = {}) => ({
      query: params.query,
      session_id: params.session_id || sessionId,
      scope: params.scope || "both",
      limit: params.limit ?? 10,
    });

    const analogicalTransform = (params: any = {}) => ({
      query: params.query,
      current_quest_id: params.current_quest_id,
      limit: params.limit ?? 5,
      min_similarity: params.min_similarity ?? 0.7,
    });

    const notifyTurnTransform = (params: any = {}) => ({
      role: params.role,
      content: params.content,
      session_id: params.session_id || sessionId,
    });

    const contextStatusTransform = (params: any = {}) => ({
      session_id: params.session_id || sessionId,
    });

    const openClawPromptTransform = (params: any = {}) => ({
      session_id: params.session_id || sessionId,
    });

    const memoryOpenLoopsTransform = (params: any = {}) => ({
      limit: params.limit ?? 10,
    });

    const canonicalOpenLoopsTransform = (params: any = {}) => ({
      quest_id: params.quest_id,
      limit: params.limit ?? 20,
    });

    const exploreGraphTransform = (params: any = {}) => ({
      start_node_id: params.start_node_id,
      session_id: params.session_id || sessionId,
      depth: params.depth ?? 3,
      strategy: params.strategy || "dfs",
      edge_types: params.edge_types,
      direction: params.direction || "both",
    });

    const setQuestTransform = (params: any = {}) => ({
      session_id: params.session_id || sessionId,
      quest_name: params.quest_name,
      quest_id: params.quest_id,
    });

    const branchQuestTransform = (params: any = {}) => ({
      name: params.name,
      purpose: params.purpose,
      parent_quest_id: params.parent_quest_id,
    });

    const diffSinceTransform = (params: any = {}) => ({
      since_iso: params.since_iso,
      limit: params.limit ?? 20,
    });

    const lessonTransform = (params: any = {}) => ({
      text: params.text,
      domain: params.domain,
      lesson_type: params.lesson_type,
      session_id: params.session_id || sessionId,
      lesson_id: params.lesson_id,
    });

    const recallLessonsTransform = (params: any = {}) => ({
      query: params.query,
      domain: params.domain,
      limit: params.limit ?? 5,
    });

    const anomaliesTransform = (params: any = {}) => ({
      scope: params.scope || "branch",
      limit: params.limit ?? 20,
      quest_id: params.quest_id,
    });

    const registerPlanTransform = (params: any = {}) => ({
      goal: params.goal,
      steps: params.steps || [],
      strategy: params.strategy,
      session_id: params.session_id || sessionId,
    });

    const reportOutcomeTransform = (params: any = {}) => ({
      plan_id: params.plan_id,
      step_number: params.step_number,
      outcome: params.outcome,
      valence: params.valence,
      valence_source: params.valence_source,
      session_id: params.session_id || sessionId,
    });

    const recallPlansTransform = (params: any = {}) => ({
      goal_query: params.goal_query,
      min_valence: params.min_valence ?? 0,
      limit: params.limit ?? 5,
      session_id: params.session_id || sessionId,
    });

    const reconstructTimelineTransform = (params: any = {}) => ({
      topic: params.topic,
      session_id: params.session_id || sessionId,
      max_hops: params.max_hops ?? 20,
      include_decisions: params.include_decisions ?? true,
    });

    const knowledgeGapsTransform = (params: any = {}) => ({
      limit: params.limit ?? 10,
      unresolved_only: params.unresolved_only ?? true,
      min_severity: params.min_severity ?? 0,
    });

    const recallProceduresTransform = (params: any = {}) => ({
      archetype: params.archetype,
      query: params.query,
      limit: params.limit ?? 3,
    });

    const registerTaskGraphParams = Type.Object({
      label: Type.String({ description: "Human-readable name for the graph" }),
      session_id: Type.Optional(Type.String({ description: "OpenClaw session ID (auto-filled)" })),
      owner: Type.Optional(Type.String({ description: "Agent or module owning this graph" })),
      tasks: Type.Array(
        Type.Object({
          task_id: Type.String(),
          label: Type.String(),
          description: Type.Optional(Type.String()),
          depends_on: Type.Optional(Type.Array(Type.String())),
        }),
        { description: "Array of task nodes to register" }
      ),
    });

    const registerTaskGraphTransform = (params: any = {}) => ({
      label: params.label,
      session_id: params.session_id || sessionId,
      owner: params.owner || "",
      tasks: params.tasks || [],
    });

    const getReadyTasksParams = Type.Object({
      graph_id: Type.String({ description: "Task graph ID" }),
    });

    const advanceTaskParams = Type.Object({
      graph_id: Type.String({ description: "Task graph ID" }),
      task_id: Type.String({ description: "Task node ID" }),
      status: Type.Union([
        Type.Literal("active"),
        Type.Literal("complete"),
        Type.Literal("skipped"),
      ]),
      result: Type.Optional(Type.String({ description: "Optional outcome summary" })),
    });

    const failTaskParams = Type.Object({
      graph_id: Type.String({ description: "Task graph ID" }),
      task_id: Type.String({ description: "Task node ID" }),
      reason: Type.String({ description: "Why the task failed" }),
    });

    const getTaskGraphParams = Type.Object({
      graph_id: Type.String({ description: "Task graph ID" }),
    });

    const getDisambiguationQueueParams = Type.Object({
      limit: Type.Optional(
        Type.Number({ description: "Maximum pending disambiguation events", default: 10 })
      ),
    });

    const resolveDisambiguationParams = Type.Object({
      event_id: Type.String({ description: "DisambiguationEvent ID to resolve" }),
      resolution: Type.Union([
        Type.Literal("merge"),
        Type.Literal("separate"),
        Type.Literal("skip"),
      ]),
    });

    const reloadDomainDictionaryParams = Type.Object({
      workspace_root: Type.Optional(
        Type.String({ description: "Workspace root containing .sidequests/domain_dictionary.yaml" })
      ),
    });

    const formatResult = (value: unknown) => ({
      content: [{ type: "text", text: JSON.stringify(value, null, 2) }],
    });

    const registerBrainTool = (definition: BrainToolDefinition) => {
      api.registerTool(
        {
          name: definition.name,
          label: definition.label,
          description: definition.description,
          parameters: definition.parameters,
          async execute(_toolCallId: string, params: any = {}) {
            const payload = definition.transformParams
              ? definition.transformParams(params)
              : { ...params };
            const result = await brain.callTool(
              definition.callName || definition.name,
              payload
            );
            return formatResult(result);
          },
        },
        { name: definition.name }
      );
    };

    const toolDefinitions: BrainToolDefinition[] = [
      {
        name: "memory_recall",
        label: "Memory Recall (SideQuests)",
        description:
          "Search the Brain's knowledge graph for relevant decisions, constraints, and context. " +
          "Call before answering questions about past choices or architecture.",
        parameters: recallToolParams,
        callName: "current_truth", // Alias: maps to current_truth
        transformParams: recallTransform,
      },
      {
        name: "memory_search",
        label: "Memory Search (SideQuests)",
        description:
          "Alias for memory_recall. Search the Brain's knowledge graph for relevant decisions, constraints, and context.",
        parameters: recallToolParams,
        callName: "current_truth", // Alias: maps to current_truth
        transformParams: recallTransform,
      },
      {
        name: "memory_get",
        label: "Memory Get (SideQuests)",
        description:
          "Alias for memory_recall. Fetch relevant memory context from the Brain using a natural-language query.",
        parameters: recallToolParams,
        callName: "current_truth", // Alias: maps to current_truth
        transformParams: recallTransform,
      },
      {
        name: "memory_store",
        label: "Notify Brain (SideQuests)",
        description:
          "Forward a message to the Brain for processing. The Brain decides what to remember " +
          "via its Gated Consolidation Loop — you don't need to decide what's important.",
        parameters: notifyTurnParams,
        callName: "notify_turn", // Alias: maps to notify_turn
        transformParams: notifyTurnTransform,
      },
      {
        name: "memory_search_analogies",
        label: "Cross-Quest Search (SideQuests)",
        description:
          "Search across all quests for analogous patterns, decisions, or lessons learned.",
        parameters: analogicalSearchParams,
        callName: "analogical_search", // Alias: maps to analogical_search
        transformParams: analogicalTransform,
      },
      {
        name: "memory_status",
        label: "Context Status (SideQuests)",
        description:
          "Check context window health — token usage, loaded knowledge, and session info.",
        parameters: Type.Object({}),
        callName: "context_status", // Alias: maps to context_status
        transformParams: contextStatusTransform,
      },
      {
        name: "memory_open_loops",
        label: "Open Loops (SideQuests)",
        description:
          "Retrieve unresolved tentative knowledge nodes for review.",
        parameters: Type.Object({
          scope: Type.Optional(Type.String({ default: "both" })),
          limit: Type.Optional(Type.Number({ default: 10 })),
        }),
        callName: "get_open_loops", // Alias: maps to get_open_loops
        transformParams: memoryOpenLoopsTransform,
      },
      {
        name: "memory_ingest",
        label: "Memory Ingest (SideQuests)",
        description:
          "Alias for notify_turn. Forward a message to the Brain for processing.",
        parameters: notifyTurnParams,
        callName: "notify_turn", // Alias: maps to notify_turn
        transformParams: notifyTurnTransform,
      },
      {
        name: "record_turn",
        label: "Record Turn (SideQuests)",
        description:
          "Alias for notify_turn. Record a conversation turn in the Brain's memory.",
        parameters: notifyTurnParams,
        callName: "notify_turn", // Alias: maps to notify_turn
        transformParams: notifyTurnTransform,
      },
      {
        name: "traverse_graph",
        label: "Traverse Graph (SideQuests)",
        description:
          "Alias for explore_graph. Traverse the knowledge graph from a seed node.",
        parameters: exploreGraphParams,
        callName: "explore_graph", // Alias: maps to explore_graph
        transformParams: exploreGraphTransform,
      },
      {
        name: "explore_memory",
        label: "Explore Memory (SideQuests)",
        description:
          "Alias for explore_graph. Explore the knowledge graph following multi-hop relationships.",
        parameters: exploreGraphParams,
        callName: "explore_graph", // Alias: maps to explore_graph
        transformParams: exploreGraphTransform,
      },
      {
        name: "finish_quest",
        label: "Finish Quest (SideQuests)",
        description:
          "Alias for complete_quest. Mark the current quest as completed.",
        parameters: completeQuestParams,
        callName: "complete_quest", // Alias: maps to complete_quest
        transformParams: (params: any = {}) => ({ quest_id: params.quest_id }),
      },
      {
        name: "create_subquest",
        label: "Create Subquest (SideQuests)",
        description:
          "Alias for branch_quest. Declare a SideQuest branching from the current goal.",
        parameters: branchQuestParams,
        callName: "branch_quest", // Alias: maps to branch_quest
        transformParams: branchQuestTransform,
      },
      {
        name: "notify_turn",
        label: "Notify Turn (SideQuests Brain)",
        description:
          "Forward this turn to the Brain for background memory processing. Call after EVERY response. Response is instant — never blocks.",
        parameters: notifyTurnParams,
        transformParams: notifyTurnTransform,
      },
      {
        name: "current_truth",
        label: "Current Truth (SideQuests Brain)",
        description:
          "Retrieve relevant memory before answering about past decisions, constraints, or architecture from the current project branch. Call before answering complex questions or making architectural choices.",
        parameters: currentTruthParams,
        transformParams: recallTransform,
      },
      {
        name: "branch_quest",
        label: "Branch Quest (SideQuests Brain)",
        description:
          "Declare a SideQuest when exploring a tangent distinct from the main project goal. Returns side_quest_id for tracking.",
        parameters: branchQuestParams,
        transformParams: branchQuestTransform,
      },
      {
        name: "register_plan",
        label: "Register Plan (SideQuests Brain)",
        description:
          "Declare a multi-step plan so SideQuests can track strategy quality and warn about similar failed plans.",
        parameters: registerPlanParams,
        transformParams: registerPlanTransform,
      },
      {
        name: "report_outcome",
        label: "Report Outcome (SideQuests Brain)",
        description:
          "Report step or plan outcomes with valence from -1.0 (failure) to +1.0 (success).",
        parameters: reportOutcomeParams,
        transformParams: reportOutcomeTransform,
      },
      {
        name: "recall_plans",
        label: "Recall Plans (SideQuests Brain)",
        description:
          "Recall similar historical plans ranked by similarity, valence, and pathway strength.",
        parameters: recallPlansParams,
        transformParams: recallPlansTransform,
      },
      {
        name: "reconstruct_timeline",
        label: "Reconstruct Timeline (SideQuests Brain)",
        description:
          "Reconstruct the time-ordered sequence of messages and decisions for a topic.",
        parameters: reconstructTimelineParams,
        transformParams: reconstructTimelineTransform,
      },
      {
        name: "get_knowledge_gaps",
        label: "Get Knowledge Gaps (SideQuests Brain)",
        description:
          "Return active unresolved knowledge gaps identified by the Brain's background sweep.",
        parameters: knowledgeGapsParams,
        transformParams: knowledgeGapsTransform,
      },
      {
        name: "recall_procedures",
        label: "Recall Procedures (SideQuests Brain)",
        description:
          "Retrieve reusable procedure templates by archetype or semantic query.",
        parameters: recallProceduresParams,
        transformParams: recallProceduresTransform,
      },
      {
        name: "diff_since",
        label: "Diff Since (SideQuests Brain)",
        description:
          "Return decisions, constraints, and requirements created since a given ISO timestamp. Use to sync context after a session gap.",
        parameters: diffSinceParams,
        transformParams: diffSinceTransform,
      },
      {
        name: "get_open_loops",
        label: "Get Open Loops (SideQuests Brain)",
        description:
          "Return concepts awaiting confirmation (soft-lock items). Use to surface uncertain memory items for user review.",
        parameters: openLoopsParams,
        transformParams: canonicalOpenLoopsTransform,
      },
      {
        name: "analogical_search",
        label: "Analogical Search (SideQuests Brain)",
        description:
          "Search across ALL historical MainQuests for similar decisions, constraints, and requirements. Use when starting a new project or feature that might benefit from past architectural patterns.",
        parameters: analogicalSearchParams,
        transformParams: analogicalTransform,
      },
      {
        name: "ingest_document",
        label: "Ingest Document (SideQuests Brain)",
        description:
          "Ingest a local file into the Brain's knowledge graph. Chunks, embeds, and queues each segment for the Consolidation Loop. Idempotent: re-ingestion is skipped if the file hasn't changed.",
        parameters: ingestDocumentParams,
        transformParams: (params: any = {}) => ({
          file_path: params.file_path,
          quest_id: params.quest_id,
        }),
      },
      {
        name: "explore_graph",
        label: "Explore Graph (SideQuests Brain)",
        description:
          "Traverse knowledge graph from a seed node, following relationships up to N hops. Enables following causal chains and multi-hop relationships.",
        parameters: exploreGraphParams,
        transformParams: exploreGraphTransform,
      },
      {
        name: "complete_quest",
        label: "Complete Quest (SideQuests Brain)",
        description:
          "Mark the current Quest as completed. Triggers lesson synthesis from confirmed artifacts. Completed quests feed cross-project analogical reasoning.",
        parameters: completeQuestParams,
        transformParams: (params: any = {}) => ({ quest_id: params.quest_id }),
      },
      {
        name: "set_quest",
        label: "Set Quest (SideQuests Brain)",
        description:
          "Explicitly bind this session to a named project/quest. Use when the user says 'this is about X' or starts a new project. Creates a new quest if the name doesn't match an existing one.",
        parameters: setQuestParams,
        transformParams: setQuestTransform,
      },
      {
        name: "context_status",
        label: "Context Status (SideQuests Brain)",
        description:
          "Check the health of the current context window — token usage, loaded knowledge, and handoff suggestions. Use when context feels bloated or when starting a new session on an existing project.",
        parameters: contextStatusParams,
        transformParams: contextStatusTransform,
      },
      {
        name: "get_openclaw_prompt",
        label: "Get OpenClaw Prompt (SideQuests Brain)",
        description:
          "Fetch the system prompt fragments that OpenClaw injects before an agent run.",
        parameters: openClawPromptParams,
        transformParams: openClawPromptTransform,
      },
      {
        name: "upsert_lesson",
        label: "Upsert Lesson (SideQuests Brain)",
        description:
          "Explicitly add or update a domain-specific lesson learned. Lessons enable transfer learning across project boundaries.",
        parameters: upsertLessonParams,
        transformParams: lessonTransform,
      },
      {
        name: "recall_relevant_lessons",
        label: "Recall Relevant Lessons (SideQuests Brain)",
        description:
          "Retrieve domain-specific lessons or best practices from the knowledge graph. Use to avoid repeating past mistakes or to apply proven optimizations.",
        parameters: recallRelevantLessonsParams,
        transformParams: recallLessonsTransform,
      },
      {
        name: "get_anomalies",
        label: "Get Anomalies (SideQuests Brain)",
        description:
          "Retrieve flagged anomalies (potential prompt injections or constraint violations). Use to review and audit suspicious content detected by the Brain.",
        parameters: anomaliesParams,
        transformParams: anomaliesTransform,
      },
      {
        name: "register_task_graph",
        label: "Register Task Graph (SideQuests Brain)",
        description:
          "Declare a durable execution DAG of tasks with dependency tracking. Returns cycle errors if any edges form a cycle.",
        parameters: registerTaskGraphParams,
        transformParams: registerTaskGraphTransform,
      },
      {
        name: "get_ready_tasks",
        label: "Get Ready Tasks (SideQuests Brain)",
        description:
          "Return the topological frontier: all pending tasks whose upstream dependencies are complete or skipped.",
        parameters: getReadyTasksParams,
      },
      {
        name: "advance_task",
        label: "Advance Task (SideQuests Brain)",
        description:
          "Transition a task to active, complete, or skipped. On complete, returns newly unblocked tasks.",
        parameters: advanceTaskParams,
      },
      {
        name: "fail_task",
        label: "Fail Task (SideQuests Brain)",
        description:
          "Mark a task as failed. Returns blocked dependent tasks that can no longer become ready.",
        parameters: failTaskParams,
      },
      {
        name: "get_task_graph",
        label: "Get Task Graph (SideQuests Brain)",
        description:
          "Return full graph state (nodes + edges) for a task graph. Use for audit and coordination.",
        parameters: getTaskGraphParams,
      },
      {
        name: "get_disambiguation_queue",
        label: "Get Disambiguation Queue (SideQuests Brain)",
        description:
          "Get pending gray-zone concept pairs for human review and curation.",
        parameters: getDisambiguationQueueParams,
        transformParams: (params: any = {}) => ({
          limit: params.limit ?? 10,
        }),
      },
      {
        name: "resolve_disambiguation",
        label: "Resolve Disambiguation (SideQuests Brain)",
        description:
          "Resolve a pending disambiguation event as merge, separate, or skip.",
        parameters: resolveDisambiguationParams,
        transformParams: (params: any = {}) => ({
          event_id: params.event_id,
          resolution: params.resolution,
        }),
      },
      {
        name: "reload_domain_dictionary",
        label: "Reload Domain Dictionary (SideQuests Brain)",
        description:
          "Reload the workspace domain dictionary and refresh entity aliases without duplication.",
        parameters: reloadDomainDictionaryParams,
        transformParams: (params: any = {}) => ({
          workspace_root: params.workspace_root || process.cwd(),
        }),
      },
    ];

    console.log(
      `[SideQuests Brain] Registering ${toolDefinitions.length} memory tools...`
    );
    toolDefinitions.forEach(registerBrainTool);
    console.log(
      `[SideQuests Brain] All ${toolDefinitions.length} tools registered: ${toolDefinitions
        .map((tool) => tool.name)
        .join(", ")}`
    );

    // -------------------------------------------------------------------
    // 2. Passive ingestion — forward all LLM turns to the Brain
    // -------------------------------------------------------------------

    if (cfg.autoCapture) {
      console.log(
        `[SideQuests Brain] Registering passive capture: ${OPENCLAW_EVENT_CONTRACT.userTurnEvent} (user), ${OPENCLAW_EVENT_CONTRACT.assistantTurnEvent} (assistant)`
      );

      // Capture user turns
      api.on(OPENCLAW_EVENT_CONTRACT.userTurnEvent, async (event: any) => {
        try {
          const content = normalizePromptPayload(event);
          if (content) {
            console.log(
              `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.userTurnEvent} fired (${summarizeEventShape(event)})`
            );
            await brain.callTool("notify_turn", {
              role: "user",
              content,
              session_id: sessionId,
            });
          } else {
            console.warn(
              `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.userTurnEvent} produced no usable content (${summarizeEventShape(event)})`
            );
          }
        } catch (err: any) {
          console.warn(
            `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.userTurnEvent} failed: ${err?.message ?? err}`
          );
        }
      });

      // Capture assistant turns
      api.on(OPENCLAW_EVENT_CONTRACT.assistantTurnEvent, async (event: any) => {
        try {
          const content = normalizeAssistantPayload(event);
          if (content) {
            console.log(
              `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.assistantTurnEvent} fired (${summarizeEventShape(event)})`
            );
            await brain.callTool("notify_turn", {
              role: "assistant",
              content,
              session_id: sessionId,
            });
          } else {
            console.warn(
              `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.assistantTurnEvent} produced no usable content (${summarizeEventShape(event)})`
            );
          }
        } catch (err: any) {
          console.warn(
            `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.assistantTurnEvent} failed: ${err?.message ?? err}`
          );
        }
      });
    }

    // -------------------------------------------------------------------
    // 3. System Prompt & Auto-Recall — inject context before agent starts
    // -------------------------------------------------------------------

    console.log(
      `[SideQuests Brain] Registering prompt injector: ${OPENCLAW_EVENT_CONTRACT.preAgentEvent}`
    );

    api.on(OPENCLAW_EVENT_CONTRACT.preAgentEvent, async (event: any) => {
      try {
        const query = normalizePromptPayload(event);
        // Contract: current_truth must use scope: "both" for cross-session recall.
        // Contract string pin: call "current_truth" before agent start.
        const recallScope = "both";

        console.log(
          `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.preAgentEvent} fired (${summarizeEventShape(event)})`
        );

        // 1. Fetch system prompt fragments (Layer 1 + Layer 2)
        // This is always-on regardless of autoRecall setting
        let systemPrompt = "";
        try {
          const promptResult: any = await brain.callTool("get_openclaw_prompt", {
            session_id: sessionId,
          });
          if (promptResult?.prompt) {
            systemPrompt = promptResult.prompt;
          }
        } catch (err: any) {
          console.warn(`[SideQuests Brain] Failed to fetch system prompt: ${err?.message}`);
        }

        // 2. Fetch memory context if autoRecall is enabled and query is sufficient
        let memoryContext = "";
        if (cfg.autoRecall && query && query.length >= 5) {
          try {
            const result: any = await brain.callTool("current_truth", {
              query,
              session_id: sessionId,
              scope: recallScope,
              limit: 5,
            });

            if (result?.results && result.results.length > 0) {
              const context = result.results
                .map(
                  (r: any) =>
                    `[${r.node_type}] ${r.text_raw} (strength: ${r.pathway_strength?.toFixed(2) || "?"})`
                )
                .join("\n");
              memoryContext = `<sidequests-memory>\n${context}\n</sidequests-memory>`;
            }
          } catch (err: any) {
            console.warn(`[SideQuests Brain] Failed to fetch memory context: ${err?.message}`);
          }
        }

        // 3. Combine and return
        const finalContext = [systemPrompt, memoryContext].filter(Boolean).join("\n\n");
        
        if (finalContext) {
          return {
            prependContext: finalContext,
          };
        }
      } catch (err: any) {
        console.warn(
          `[SideQuests Brain] Event ${OPENCLAW_EVENT_CONTRACT.preAgentEvent} failed: ${err?.message ?? err}`
        );
      }
      return {};
    });

    // -------------------------------------------------------------------
    // 4. Service registration — health check on startup
    // -------------------------------------------------------------------

    api.registerService?.({
      id: "sidequests-brain",
      async start() {
        isOnline = await brain.ping();
        const serviceInstalled = isDaemonServiceInstalled();

        if (isOnline) {
          console.log(
            `[SideQuests Brain] Connected to Brain Daemon at ${cfg.brainUrl} (Streamable HTTP)`
          );
        } else {
          // Daemon not reachable — give a diagnostic-quality warning.
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
        }

        // B82: Start periodic health check
        healthCheckInterval = setInterval(async () => {
          const currentlyAlive = await brain.ping();
          if (currentlyAlive && !isOnline) {
            console.log(
              `[SideQuests Brain] Brain Daemon recovered — transitioning to online`
            );
            isOnline = true;
          } else if (!currentlyAlive && isOnline) {
            console.warn(
              `[SideQuests Brain] Brain Daemon unreachable — transitioning to offline`
            );
            isOnline = false;
          }
        }, cfg.healthCheckIntervalMs);

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
              isOnline = true;
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
        if (healthCheckInterval) {
          clearInterval(healthCheckInterval);
          healthCheckInterval = null;
        }
      },
    });
  },
};
