"""
mcp_engine/tool_schemas.py — Canonical MCP tool schema definitions.

Single source of truth for tool names, descriptions, and input schemas.
All adapters (stdio + SSE) import from here to prevent drift.
"""

TOOLS: list[dict] = [
    {
        "name": "notify_turn",
        "description": (
            "Forward this turn to the Brain for background memory processing. "
            "Call after EVERY response. Response is instant — never blocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "role":       {"type": "string", "enum": ["user", "assistant"]},
                "content":    {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["role", "content", "session_id"],
        },
    },
    {
        "name": "current_truth",
        "description": (
            "Retrieve relevant memory before answering about past decisions, "
            "constraints, or architecture from the current project branch. "
            "Call before answering complex questions or making architectural choices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":      {"type": "string"},
                "session_id": {"type": "string"},
                "scope":      {"type": "string", "enum": ["branch", "global", "both"],
                               "default": "branch"},
                "limit":      {"type": "integer", "default": 10},
            },
            "required": ["query", "session_id"],
        },
    },
    {
        "name": "branch_quest",
        "description": (
            "Declare a SideQuest when exploring a tangent distinct from the "
            "main project goal. Returns side_quest_id for tracking."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string"},
                "purpose":         {"type": "string"},
                "parent_quest_id": {"type": "string"},
            },
            "required": ["name", "purpose"],
        },
    },
    {
        "name": "diff_since",
        "description": (
            "Return decisions, constraints, and requirements created since a "
            "given ISO timestamp. Use to sync context after a session gap."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_iso": {"type": "string"},
                "limit":     {"type": "integer", "default": 20},
            },
            "required": ["since_iso"],
        },
    },
    {
        "name": "get_open_loops",
        "description": (
            "Return concepts awaiting confirmation (soft-lock items). "
            "Use to surface uncertain memory items for user review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "analogical_search",
        "description": (
            "Search across ALL historical MainQuests for similar decisions, "
            "constraints, and requirements. Use when starting a new project or "
            "feature that might benefit from past architectural patterns."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":            {"type": "string"},
                "current_quest_id": {"type": "string",
                                     "description": "Exclude results from this quest."},
                "limit":            {"type": "integer", "default": 5},
                "min_similarity":   {"type": "number", "default": 0.70},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ingest_document",
        "description": (
            "Ingest a local file into the Brain's knowledge graph. "
            "Chunks, embeds, and queues each segment for the Consolidation Loop. "
            "Idempotent: re-ingestion is skipped if the file hasn't changed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string",
                              "description": "Absolute path to the file to ingest."},
                "quest_id":  {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "explore_graph",
        "description": (
            "Traverse knowledge graph from a seed node, following relationships up to N hops. "
            "Enables following causal chains and multi-hop relationships."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_node_id": {
                    "type": "string",
                    "description": "Node ID to start traversal (from current_truth results)."
                },
                "session_id": {
                    "type": "string"
                },
                "depth": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 5
                },
                "strategy": {
                    "type": "string",
                    "enum": ["dfs", "bfs"],
                    "default": "dfs"
                },
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming", "both"],
                    "default": "both"
                }
            },
            "required": ["start_node_id", "session_id"]
        },
    },
    {
        "name": "complete_quest",
        "description": (
            "Mark the current Quest as completed. Triggers lesson synthesis "
            "from confirmed artifacts. Completed quests feed cross-project analogical reasoning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quest_id": {"type": "string",
                             "description": "The quest_id to mark completed."},
            },
            "required": ["quest_id"],
        },
    },
    {
        "name": "set_quest",
        "description": (
            "Explicitly bind this session to a named project/quest. "
            "Use when the user says 'this is about X' or starts a new project. "
            "Creates a new quest if the name doesn't match an existing one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id":  {"type": "string"},
                "quest_name":  {"type": "string",
                                "description": "Name of the quest to bind to."},
                "quest_id":    {"type": "string",
                                "description": "Optional: bind to a specific quest_id."},
            },
            "required": ["session_id", "quest_name"],
        },
    },
    {
        "name": "context_status",
        "description": (
            "Check the health of the current context window — token usage, "
            "loaded knowledge, and handoff suggestions. Use when context feels "
            "bloated or when starting a new session on an existing project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "upsert_lesson",
        "description": (
            "Explicitly add or update a domain-specific lesson learned. "
            "Lessons enable transfer learning across project boundaries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text":        {"type": "string", "description": "The lesson content."},
                "domain":      {"type": "string", "description": "e.g., 'rust', 'react', 'ux'."},
                "lesson_type": {"type": "string", "enum": ["mistake", "edge-case", "optimization", "architecture-principle"]},
                "session_id":  {"type": "string"},
                "lesson_id":   {"type": "string", "description": "Optional: update existing lesson."},
            },
            "required": ["text", "domain", "lesson_type"],
        },
    },
    {
        "name": "recall_relevant_lessons",
        "description": (
            "Retrieve domain-specific lessons or best practices from the knowledge graph. "
            "Use to avoid repeating past mistakes or to apply proven optimizations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":  {"type": "string", "description": "Semantic search query."},
                "domain": {"type": "string", "description": "Filter by domain (e.g., 'rust')."},
                "limit":  {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "get_anomalies",
        "description": (
            "Retrieve flagged anomalies (potential prompt injections or constraint violations). "
            "Use to review and audit suspicious content detected by the Brain."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["branch", "global", "both"],
                         "default": "branch",
                         "description": "Scope of anomaly search."},
                "limit": {"type": "integer", "default": 20,
                         "description": "Maximum number of anomalies to return."},
                "quest_id": {"type": "string", "description": "Optional: filter by quest."},
            },
        },
    },
]
