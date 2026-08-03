"""REST API endpoints for Campy — thin wrappers around MCP tool handlers."""
import asyncio
import json
import logging
import time
from typing import Optional

from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.requests import Request

logger = logging.getLogger(__name__)

__all__ = ["create_router", "_ok", "_err"]


def _ok(data: dict) -> JSONResponse:
    """Standard success response."""
    return JSONResponse({"ok": True, "data": data})


def _err(message: str, status: int = 400) -> JSONResponse:
    """Standard error response."""
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def create_router(db=None, config: dict = None):
    """Create the REST API route list. db and config are injected at mount time."""

    async def _call_tool(tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool handler directly."""
        from campy.brain.thalamus.tools import TOOL_HANDLERS
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            result = await handler(params=arguments, db=db, config=config or {})
            return result
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return {"error": str(e)}

    async def recall_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/recall?q=<query>&scope=both"""
        query = request.query_params.get("q", "")
        if not query:
            return _err("Missing required parameter: q")
        scope = request.query_params.get("scope", "both")
        session_id = request.query_params.get("session_id", "rest-api")
        result = await _call_tool("current_truth", {
            "query": query, "scope": scope, "session_id": session_id,
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def bundle_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/bundle — body: {query, token_budget?, agent_type?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        query = body.get("query", "")
        if not query:
            return _err("Missing required field: query")
        result = await _call_tool("compile_context", {
            "query": query,
            "token_budget": body.get("token_budget", 32000),
            "agent_type": body.get("agent_type", "generic"),
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def timeline_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/timeline?since=<ISO>&limit=20"""
        args = {"limit": int(request.query_params.get("limit", "20"))}
        since = request.query_params.get("since")
        if since:
            args["since_iso"] = since
        quest_id = request.query_params.get("quest_id")
        if quest_id:
            args["quest_id"] = quest_id
        result = await _call_tool("reconstruct_timeline", args)
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def diff_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/diff?since=<ISO>"""
        since = request.query_params.get("since")
        if not since:
            return _err("Missing required parameter: since")
        result = await _call_tool("diff_since", {"since_iso": since})
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def decide_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/decide — body: {query, session_id?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        query = body.get("query", "")
        if not query:
            return _err("Missing required field: query")
        args = {"query": query}
        if body.get("session_id"):
            args["session_id"] = body["session_id"]
        result = await _call_tool("memory_decision", args)
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def status_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/status?session_id=<id>"""
        session_id = request.query_params.get("session_id", "rest-api")
        result = await _call_tool("context_status", {"session_id": session_id})
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def notify_endpoint(request: Request) -> JSONResponse:
        """POST /api/v1/notify — body: {role, content, session_id?}"""
        try:
            body = await request.json()
        except Exception:
            return _err("Invalid JSON body")
        role = body.get("role", "")
        content = body.get("content", "")
        if not role or not content:
            return _err("Missing required fields: role, content")
        result = await _call_tool("notify_turn", {
            "role": role,
            "content": content,
            "session_id": body.get("session_id", "rest-api"),
        })
        if "error" in result:
            return _err(result["error"], 500)
        return _ok(result)

    async def tools_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/tools — list available tools"""
        from campy.brain.thalamus.tools import TOOL_HANDLERS
        tools = [{"name": name} for name in sorted(TOOL_HANDLERS.keys())]
        return _ok({"tools": tools, "count": len(tools)})

    async def heartbeat_endpoint(request: Request) -> JSONResponse:
        """GET /api/v1/heartbeat — one-shot current phase."""
        from campy.brain.brainstem.phase import get_phase
        return _ok(get_phase())

    async def activity_stream_endpoint(request: Request) -> StreamingResponse:
        """GET /api/v1/activity/stream — SSE stream of phase transitions."""
        from campy.brain.brainstem.phase import subscribe, unsubscribe

        q = subscribe()

        async def event_generator():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=30.0)
                        yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                unsubscribe(q)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    routes = [
        Route("/api/v1/recall", recall_endpoint, methods=["GET"]),
        Route("/api/v1/bundle", bundle_endpoint, methods=["POST"]),
        Route("/api/v1/timeline", timeline_endpoint, methods=["GET"]),
        Route("/api/v1/diff", diff_endpoint, methods=["GET"]),
        Route("/api/v1/decide", decide_endpoint, methods=["POST"]),
        Route("/api/v1/status", status_endpoint, methods=["GET"]),
        Route("/api/v1/notify", notify_endpoint, methods=["POST"]),
        Route("/api/v1/tools", tools_endpoint, methods=["GET"]),
        Route("/api/v1/heartbeat", heartbeat_endpoint, methods=["GET"]),
        Route("/api/v1/activity/stream", activity_stream_endpoint, methods=["GET"]),
    ]
    return routes
