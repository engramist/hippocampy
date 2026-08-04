"""Context assembly and ingestion routing handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._shared import get_loop_queue
from .capture import notify_turn

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)



async def ingest_document(params: dict, db, config: dict) -> dict:
    """
    Ingest a local file into the graph as Document + DocumentExtract nodes.
    Runs chunking, embedding, and DERIVED_FROM wiring.
    Queues each extract for the Gated Consolidation Loop.

    params: {file_path, quest_id?}
    """
    file_path = params.get("file_path", "").strip()
    quest_id  = params.get("quest_id", "")

    if not file_path:
        return {"error": "file_path is required"}

    from campy.brain.sensory_cortex.ingest import ingest_document as _ingest
    return await _ingest(
        db=db,
        file_path=file_path,
        config=config,
        loop_queue=get_loop_queue(),
        quest_id=quest_id,
    )


async def ingest_data(params: dict, db, config: dict) -> dict:
    """
    Unified ingestion entry point. Classifies file/content input and routes it
    to the graph/document/tabular ingestion path without creating a shadow store.

    params: {file_path?, content?, mime_type?, session_id, quest_id?}
    """
    from campy.brain.temporal_lobe.memory_router import classify_input

    file_path = (params.get("file_path") or "").strip()
    content = params.get("content")
    mime_type = params.get("mime_type")
    session_id = (params.get("session_id") or "unknown").strip() or "unknown"
    quest_id = (params.get("quest_id") or "").strip()

    if not file_path and not content:
        return {"error": "file_path or content is required"}

    route = classify_input(content=content, file_path=file_path, mime_type=mime_type)
    _logger.info(
        "ingest_data classified input as storage_type=%s confidence=%.2f suggested_tool=%s (%s)",
        route.storage_type, route.confidence, route.suggested_tool, route.reason,
    )

    async def _record_turn() -> dict:
        return await notify_turn(
            {
                "role": params.get("role", "user"),
                "content": content or "",
                "session_id": session_id,
            },
            db,
            config,
        )

    if file_path:
        result = await ingest_document({"file_path": file_path, "quest_id": quest_id}, db, config)
    elif route.storage_type in ("tabular", "graph+tabular"):
        # B251: classify_input() can recommend the tabular path for pasted
        # content (no file_path) - route it there instead of silently
        # falling through to notify_turn regardless of the classification.
        # "graph+tabular" is a dual-write: the conversational turn is
        # still recorded alongside the tabular data.
        from campy.brain.sensory_cortex.tabular_ingest import ingest_tabular_from_content

        tabular_result = await ingest_tabular_from_content(
            db, content or "", config, get_loop_queue(), quest_id
        )
        if route.storage_type == "graph+tabular":
            result = {"tabular": tabular_result, "graph": await _record_turn()}
        else:
            result = {"tabular": tabular_result}
    else:
        result = await _record_turn()

    return {
        "route": {
            "storage_type": route.storage_type,
            "reason": route.reason,
            "confidence": route.confidence,
            "suggested_tool": route.suggested_tool,
        },
        "result": result,
    }


async def compile_context(params: dict, db, config: dict) -> dict:
    """
    Compile a bounded ContextBundle for multi-entity or broad memory queries.

    params: {query, token_budget?, agent_type?, output_format?, session_id?, quest_id?,
             include_tabular?, include_summaries?}
    """
    from campy.brain.thalamus.bundle_compiler import compile_bundle
    from campy.brain.thalamus.formatters import format_bundle

    query = (params.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    token_budget = int(params.get("token_budget") or 32000)
    agent_type = params.get("output_format") or params.get("agent_type") or "generic"

    bundle = await compile_bundle(
        query=query,
        db=db,
        config=config,
        token_budget=token_budget,
        agent_type=agent_type,
        quest_id=params.get("quest_id"),
        session_id=params.get("session_id"),
        include_tabular=params.get("include_tabular", True),
        include_summaries=params.get("include_summaries", True),
    )

    return {
        "bundle": bundle.to_dict(),
        "formatted": format_bundle(bundle, agent_type),
        "agent_type": agent_type,
    }


async def ask(params: dict, db: "KuzuClient", config: dict) -> dict:
    """MCP tool handler for `ask`. Thin wrapper over run_ask()."""
    from campy.brain.thalamus.ask import run_ask
    query = params.get("query", "")
    session_id = params.get("session_id", "")
    token_budget = params.get("token_budget", 32000)
    capture = params.get("capture", True)
    if not query:
        return {"error": "query is required"}
    answer = await run_ask(
        query=query,
        session_id=session_id,
        db=db,
        config=config,
        token_budget=token_budget,
        capture=capture,
    )
    return {"answer": answer}


async def memory_decision(params: dict, db: KuzuClient, config: dict) -> dict:
    """
    Recommend whether and how to recall SideQuests memory.

    Uses transparent lexical/phase-based routing to recommend the appropriate
    recall tool or suggest no recall for the current user prompt.

    params: {
        user_prompt (required): str,
        task_phase (optional): str (e.g., 'planning', 'debugging'),
        available_context_summary (optional): str,
        session_id (optional): str,
        client_name (optional): str (e.g., 'codex', 'claude-desktop')
    }

    Returns:
    {
        should_recall: bool,
        recommended_tool: str,
        query: str,
        reason: str,
        confidence: float (0.0-1.0),
        context_budget: str ("compact", "moderate", "exhaustive"),
        anti_bloat_guidance: str,
    }
    """
    from campy.brain.thalamus.memory_decision import decide_memory_action

    user_prompt = params.get("user_prompt", "").strip()
    if not user_prompt:
        return {
            "should_recall": False,
            "recommended_tool": "none",
            "query": "",
            "reason": "Empty user prompt; no recall needed.",
            "confidence": 1.0,
            "context_budget": "compact",
            "anti_bloat_guidance": "No action needed.",
        }

    task_phase = params.get("task_phase", "unknown")
    available_context_summary = params.get("available_context_summary")
    session_id = params.get("session_id")
    client_name = params.get("client_name")

    recommendation = decide_memory_action(
        user_prompt=user_prompt,
        task_phase=task_phase,
        available_context_summary=available_context_summary,
        session_id=session_id,
        client_name=client_name,
    )

    return recommendation
