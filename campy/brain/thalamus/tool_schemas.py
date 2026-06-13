"""
campy/brain/thalamus/tool_schemas.py — Canonical MCP tool schema definitions.

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
            "Call before answering complex questions or making architectural choices. "
            "Optional include_rationale returns originating message context for each result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":      {"type": "string"},
                "session_id": {"type": "string"},
                "scope":      {"type": "string", "enum": ["branch", "global", "both"],
                               "default": "branch"},
                "limit":      {"type": "integer", "default": 10},
                "include_rationale": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include 1-hop ESTABLISHED_IN message rationale for each result."
                },
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
        "name": "reconstruct_timeline",
        "description": (
            "Reconstruct the temporal sequence of messages and decisions for a topic. "
            "Returns a time-ordered list of messages and any Decisions established at each step."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "session_id": {"type": "string", "description": "Optional: restrict to one session"},
                "max_hops": {"type": "integer", "default": 20},
                "include_decisions": {"type": "boolean", "default": True}
            },
            "required": ["topic"]
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
        "name": "ingest_data",
        "description": (
            "Unified data ingestion. Automatically classifies input and routes to optimal storage "
            "(graph, tabular, or document). Use this instead of calling ingest_document or notify_turn directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file to ingest (if not providing content)"},
                "content": {"type": "string", "description": "Raw content to ingest (if not providing file)"},
                "mime_type": {"type": "string", "description": "Optional MIME type hint"},
                "session_id": {"type": "string"},
                "quest_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "compile_context",
        "description": (
            "Compile a context bundle from all memory types (graph, exact facts, tabular data, summaries). "
            "Returns shaped context optimized for the requesting agent's token budget. "
            "Use this for complex queries that need assembled context; use current_truth for simple fact lookups."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What context is needed"},
                "token_budget": {"type": "integer", "description": "Max tokens for the bundle (default: 32000)", "default": 32000},
                "agent_type": {"type": "string", "description": "Requesting agent type for output formatting"},
                "include_tabular": {"type": "boolean", "default": True},
                "include_summaries": {"type": "boolean", "default": True},
                "session_id": {"type": "string"},
                "quest_id": {"type": "string"},
            },
            "required": ["query", "session_id"],
        },
    },
    {
        "name": "ingest_arc_artifacts",
        "description": (
            "Import ARC_AGI run artifacts into SideQuests graph memory for retrieval and wiki projection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact_root": {"type": "string"},
                "include_live_jsonl": {"type": "boolean", "default": True},
                "dry_run": {"type": "boolean", "default": False},
                "max_events": {"type": "integer", "default": 5000},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "explore_graph",
        "description": (
            "Traverse knowledge graph from a seed node, following relationships up to N hops. "
            "Enables following causal chains and multi-hop relationships. "
            "Optional context_window adds temporal/causal neighbors around visited nodes."
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
                },
                "context_window": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 3,
                    "description": "Number of contextual neighbors to include around each node."
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
    {
        "name": "register_plan",
        "description": (
            "Declare a multi-step strategy. Stores Plan + PlanStep nodes, links steps by order, "
            "and returns warnings/suggestions from similar past plans."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal":       {"type": "string", "description": "What this plan aims to achieve."},
                "steps":      {"type": "array", "items": {"type": "string"}, "description": "Ordered list of steps."},
                "session_id": {"type": "string"},
                "strategy":   {"type": "string", "description": "Optional high-level approach description."},
            },
            "required": ["goal", "steps", "session_id"],
        },
    },
    {
        "name": "report_outcome",
        "description": (
            "Report a step-level or plan-level outcome with valence (-1.0 to +1.0). "
            "Updates Plan/PlanStep status and can create lesson/outcome signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id":     {"type": "string"},
                "step_number": {"type": "integer", "description": "Optional step number for step-level update."},
                "outcome":     {"type": "string"},
                "valence":     {"type": "number", "minimum": -1.0, "maximum": 1.0},
                "session_id":  {"type": "string"},
                "valence_source": {"type": "string", "description": "user_feedback | exit_code | test_result | system"},
            },
            "required": ["plan_id", "outcome", "valence", "session_id"],
        },
    },
    {
        "name": "get_openclaw_prompt",
        "description": (
            "Retrieve the OpenClaw plugin prompt for tool registration. "
            "Returns the system prompt fragments injected before an agent run."
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
        "name": "recall_plans",
        "description": (
            "Retrieve similar historical plans and their step outcomes. "
            "Ranked by similarity × |valence| × pathway_strength."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_query":  {"type": "string"},
                "session_id":  {"type": "string"},
                "min_valence": {"type": "number", "default": 0.0},
                "limit":       {"type": "integer", "default": 5},
            },
            "required": ["goal_query", "session_id"],
        },
    },
    {
        "name": "get_knowledge_gaps",
        "description": (
            "Return active KnowledgeGap nodes identified by background sweep. "
            "Useful for agents to proactively check missing or low-quality coverage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
                "unresolved_only": {"type": "boolean", "default": True},
                "min_severity": {"type": "number", "default": 0.0},
            },
        },
    },
    {
        "name": "recall_procedures",
        "description": (
            "Retrieve reusable Procedure templates by archetype or semantic query. "
            "Returns procedures ranked by success_rate and success_count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "archetype": {"type": "string", "description": "Optional archetype filter"},
                "query": {"type": "string", "description": "Optional semantic query"},
                "limit": {"type": "integer", "default": 3},
            },
        },
    },
    {
        "name": "recall_scene_graph_priors",
        "description": (
            "Return evidence-weighted progress priors for a scene graph signature. "
            "Uses stored lesson metadata keyed by scene_wl_hash and optional archetype."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "wl_hash": {"type": "string", "description": "Weisfeiler-Lehman hash for current scene graph."},
                "archetype": {"type": "string", "description": "Optional archetype filter such as 'race' or 'space'."},
                "min_valence": {"type": "number", "default": 0.0},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["wl_hash"],
        },
    },
    {
        "name": "register_task_graph",
        "description": (
            "Declare a first-class execution DAG (TaskGraph + TaskNodes). "
            "Enables durable dependency-aware execution tracking. "
            "Returns cycle_errors if any edges would form a cycle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "label":      {"type": "string", "description": "Human-readable name for the graph."},
                "session_id": {"type": "string"},
                "owner":      {"type": "string", "description": "Agent or module owning this graph."},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_id":     {"type": "string"},
                            "label":       {"type": "string"},
                            "description": {"type": "string"},
                            "depends_on":  {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["task_id", "label"]
                    }
                }
            },
            "required": ["label", "session_id", "owner", "tasks"]
        },
    },
    {
        "name": "get_ready_tasks",
        "description": (
            "Return the topological frontier: all pending tasks whose upstream dependencies "
            "are all complete or skipped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"}
            },
            "required": ["graph_id"]
        },
    },
    {
        "name": "advance_task",
        "description": (
            "Transition a task to active or complete. On complete, returns newly unblocked tasks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "task_id":  {"type": "string"},
                "status":   {"type": "string", "enum": ["active", "complete", "skipped"]},
                "result":   {"type": "string", "description": "Optional outcome summary."}
            },
            "required": ["graph_id", "task_id", "status"]
        },
    },
    {
        "name": "fail_task",
        "description": (
            "Mark a task as failed. Returns blocked dependents that can no longer become ready."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "task_id":  {"type": "string"},
                "reason":   {"type": "string"}
            },
            "required": ["graph_id", "task_id", "reason"]
        },
    },
    {
        "name": "get_task_graph",
        "description": (
            "Return full graph state (nodes + edges) for audit and coordination."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"}
            },
            "required": ["graph_id"]
        },
    },
    {
        "name": "get_disambiguation_queue",
        "description": (
            "Get pending entity disambiguation pairs for human review. Returns gray-zone concept pairs that the system couldn't automatically resolve."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10}
            }
        },
    },
    {
        "name": "resolve_disambiguation",
        "description": (
            "Resolve a disambiguation pair: merge (same entity), separate (distinct entities), or skip (review later)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "DisambiguationEvent ID from get_disambiguation_queue"},
                "resolution": {"type": "string", "enum": ["merge", "separate", "skip"], "description": "How to resolve: merge=same entity, separate=distinct, skip=review later"}
            },
            "required": ["event_id", "resolution"]
        },
    },
    {
        "name": "reload_domain_dictionary",
        "description": (
            "Reload the domain dictionary from .sidequests/domain_dictionary.yaml. "
            "Adds new entities and altLabels without duplicating existing ones."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string", "description": "Workspace root path", "default": "."}
            }
        },
    },
    {
        "name": "publish_mechanic_summary",
        "description": "Publish a learned ARC world-model mechanic summary to persistent graph memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "object",
                    "description": "ARC mechanic summary payload including signature, confidence, action/effect patterns, and failure modes."
                },
                "async_dispatch": {
                    "type": "boolean",
                    "default": True,
                    "description": "Accept and return immediately; processing happens in background."
                }
            },
            "required": ["summary"]
        }
    },
    {
        "name": "recall_mechanic_priors",
        "description": "Retrieve reusable ARC mechanic priors from graph memory based on action/effect signature similarity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "signature": {
                    "type": "object",
                    "description": "Query signature fields (action_set, archetype, effect_class, terminal_trend, coordinate_relevance, failure_signal)."
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Max number of ranked results to return."
                },
                "min_confidence": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Minimum confidence threshold for results."
                }
            }
        }
    },
    {
        "name": "arc_perceive_state",
        "description": "Ingest an ARC grid observation and upsert GridSnapshot, GridEntity, and ActionEffect records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "step": {"type": ["integer", "string"]},
                "grid_hash": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "object"}},
                "action_taken": {"type": "string"},
                "effect": {"type": "object"},
            },
            "required": ["task_id", "step"],
        },
    },
    {
        "name": "arc_get_game_context",
        "description": "Return a compact episodic summary of the current ARC game state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "arc_get_action_evidence",
        "description": "Fetch the evidence track record for one ARC action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_id": {"type": "string"},
            },
            "required": ["task_id", "action_id"],
        },
    },
    {
        "name": "arc_get_untested_actions",
        "description": "Return actions that have not yet been tried for the current ARC task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "available_actions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "arc_get_causal_path",
        "description": "Bounded causal-path lookup from an action to a victory condition.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_id": {"type": "string"},
                "goal_id": {"type": "string"},
            },
            "required": ["task_id", "action_id"],
        },
    },
    {
        "name": "arc_record_action_effect",
        "description": "Write the observed effect of an ARC action back into graph memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_id": {"type": "string"},
                "step": {"type": ["integer", "string"]},
                "effect": {"type": "object"},
                "entities_affected": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["task_id", "action_id", "step"],
        },
    },
    {
        "name": "arc_get_entity_movement",
        "description": "Track entity movement relative to an ARC action step.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "step": {"type": ["integer", "string"]},
            },
            "required": ["task_id", "step"],
        },
    },
    {
        "name": "arc_get_goal_evidence",
        "description": "Query VictoryCondition evidence for the current ARC task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "arc_classify_game_archetype",
        "description": "Classify the current ARC puzzle into a known archetype.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "grid_features": {"type": "object"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "arc_confirm_hypothesis",
        "description": "Increase confidence in an ARC hypothesis with supporting evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "evidence": {"type": "object"},
            },
            "required": ["task_id", "hypothesis_id"],
        },
    },
    {
        "name": "arc_contradict_hypothesis",
        "description": "Decrease confidence in an ARC hypothesis with contradicting evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "evidence": {"type": "object"},
            },
            "required": ["task_id", "hypothesis_id"],
        },
    },
    {
        "name": "arc_update_goal_confidence",
        "description": "Update VictoryCondition confidence with a progress gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "goal_id": {"type": "string"},
                "new_confidence": {"type": "number"},
                "has_meaningful_progress": {"type": "boolean", "default": False},
            },
            "required": ["task_id", "goal_id", "new_confidence"],
        },
    },
    {
        "name": "arc_get_mechanic_priors",
        "description": "Retrieve prior ARC mechanics linked to action patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_patterns": {"type": "array", "items": {"type": "object"}},
                "game_features": {"type": "object"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "arc_check_action_gate",
        "description": "Return the go/no-go decision for an ARC action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_id": {"type": "string"},
                "available_actions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id", "action_id"],
        },
    },
    {
        "name": "arc_record_reward_prediction_error",
        "description": "Store the reward prediction error for one ARC action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action_id": {"type": "string"},
                "step": {"type": ["integer", "string"]},
                "predicted_reward": {"type": "number"},
                "actual_reward": {"type": "number"},
            },
            "required": ["task_id", "action_id"],
        },
    },
    {
        "name": "memory_decision",
        "description": (
            "Recommend whether and how to recall SideQuests memory for the current user prompt. "
            "Returns deterministic routing decision: should_recall (bool), recommended_tool (str), "
            "query (str), reason, confidence, context_budget, and anti_bloat_guidance. "
            "Does not retrieve memory in v1; only recommends the next action."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_prompt": {
                    "type": "string",
                    "description": "The user's current message or question."
                },
                "task_phase": {
                    "type": "string",
                    "description": "Optional phase hint (e.g., 'planning', 'debugging', 'refactoring')."
                },
                "available_context_summary": {
                    "type": "string",
                    "description": "Optional summary of what's already in context."
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session ID for potential future stateful hints."
                },
                "client_name": {
                    "type": "string",
                    "description": "Optional client identifier (e.g., 'codex', 'claude-desktop')."
                },
            },
            "required": ["user_prompt"],
        },
    },
]
