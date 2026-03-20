"""
sidequests/cli/smoke_test.py — Brain Daemon health check.

Runs 3 checks:
  1. Socket exists and daemon accepts connection
  2. tools/list returns the expected tool set
  3. current_truth responds (schema initialized)

Used by `sidequests status` and called at the end of `sidequests setup`.
"""

from __future__ import annotations
import asyncio
import json
import uuid
from pathlib import Path

SOCKET_PATH = Path.home() / ".sidequests" / "brain.sock"

EXPECTED_TOOLS = {
    "notify_turn", "current_truth", "branch_quest", "diff_since",
    "get_open_loops", "analogical_search", "ingest_document", "explore_graph",
    "complete_quest", "set_quest", "context_status",
}


async def _send(method: str, params: dict | None = None) -> dict:
    """Send one JSON-RPC request to the Brain Daemon socket. 5 s timeout."""
    request = json.dumps({
        "jsonrpc": "2.0",
        "id":      str(uuid.uuid4()),
        "method":  method,
        "params":  params or {},
    }) + "\n"
    reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    writer.write(request.encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    writer.close()
    await writer.wait_closed()
    return json.loads(line)


async def smoke_test() -> dict:
    """
    Run all 3 checks. Returns:
      {"checks": [{"name", "passed", "detail"}, ...], "passed": bool}
    """
    checks = []

    # ── Check 1: socket reachable ──────────────────────────────────────────
    try:
        await _send("initialize")
        checks.append({"name": "Daemon socket", "passed": True,
                        "detail": f"{SOCKET_PATH} — reachable"})
    except Exception as e:
        checks.append({"name": "Daemon socket", "passed": False,
                        "detail": f"Cannot connect: {e}"})
        # No point continuing if socket is down
        return {"checks": checks, "passed": False}

    # ── Check 2: tools/list ────────────────────────────────────────────────
    try:
        resp   = await _send("tools/list")
        tools  = {t["name"] for t in resp.get("result", {}).get("tools", [])}
        missing = EXPECTED_TOOLS - tools
        if missing:
            checks.append({"name": "Tools registered", "passed": False,
                            "detail": f"Missing tools: {sorted(missing)}"})
        else:
            checks.append({"name": "Tools registered", "passed": True,
                            "detail": f"{len(tools)} tools available"})
    except Exception as e:
        checks.append({"name": "Tools registered", "passed": False,
                        "detail": f"Error: {e}"})

    # ── Check 3: current_truth responds ────────────────────────────────────
    try:
        resp = await _send("current_truth",
                           {"query": "smoke test", "session_id": "smoke"})
        if "result" in resp and "results" in resp["result"]:
            checks.append({"name": "Schema initialized", "passed": True,
                            "detail": "current_truth responded OK"})
        else:
            checks.append({"name": "Schema initialized", "passed": False,
                            "detail": f"Unexpected response: {resp}"})
    except Exception as e:
        checks.append({"name": "Schema initialized", "passed": False,
                        "detail": f"Error: {e}"})

    passed = all(c["passed"] for c in checks)
    return {"checks": checks, "passed": passed}


def check_sse_endpoint(port: int = 7799) -> bool:
    """Verify the SSE endpoint is responding."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/sse",
            headers={"Accept": "text/event-stream"}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        # Read just the first line to confirm event-stream
        first_line = resp.readline().decode()
        resp.close()
        if "endpoint" in first_line or "event" in first_line:
            return True
        return False
    except Exception:
        return False


def check_status() -> bool:
    """Print human-readable status and return True if all checks passed."""
    result = asyncio.run(smoke_test())
    for check in result["checks"]:
        icon = "✓" if check["passed"] else "✗"
        print(f"  [{icon}] {check['name']}: {check['detail']}")

    # SSE health check
    sse_ok = check_sse_endpoint()
    icon = "✓" if sse_ok else "✗"
    detail = "Responding" if sse_ok else "Unreachable"
    print(f"  [{icon}] SSE Endpoint: {detail}")

    if result["passed"] and sse_ok:
        print("\nBrain Daemon is healthy.")
    else:
        print("\nSome checks failed. Run `sidequests start` to start the daemon.")
    return result["passed"] and sse_ok
