import os
import socket
import json
import urllib.request
import asyncio
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from campy.paths import get_daemon_socket_path

SOCKET_PATH = get_daemon_socket_path()

def _send(method: str, params: dict | None = None, timeout_seconds: float = 5.0) -> dict:
    """Send a JSON-RPC 2.0 request over the Unix domain socket."""
    if not SOCKET_PATH.exists():
        return {"error": {"code": -32000, "message": f"Daemon socket not found at {SOCKET_PATH}"}}

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1
    }

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout_seconds)
        client.connect(str(SOCKET_PATH))
        # Daemon reads newline-delimited JSON-RPC frames via reader.readline().
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))

        response = b""
        while b"\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk

        client.close()
        if not response:
            return {"error": {"code": -32000, "message": "Empty response from daemon"}}
        # Daemon writes newline-delimited JSON-RPC frames.
        line = response.split(b"\n", 1)[0]
        return json.loads(line.decode("utf-8"))
    except Exception as e:
        return {"error": {"code": -32000, "message": str(e)}}

def check_ollama(base_url: str = "http://localhost:11434/v1") -> bool:
    """Ping Ollama to see if it's responding."""
    try:
        # Try /api/tags (Ollama native) or just the v1 endpoint
        native_url = base_url.replace("/v1", "/api/tags")
        if native_url == base_url:
             native_url = "http://localhost:11434/api/tags"

        req = urllib.request.Request(native_url)
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.getcode() == 200
    except Exception:
        # Try the base_url as fallback
        try:
            req = urllib.request.Request(base_url)
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.getcode() == 200
        except Exception:
            return False

def check_bedrock(llm_cfg: dict) -> bool:
    """
    Verify AWS Bedrock is reachable for the configured provider (B324).

    Deliberately does NOT invoke a model (no `converse()` call, no tokens
    burned) — same reasoning as `check_ollama`'s cheap ping. Instead it
    confirms boto3 is installed and that credentials + region resolve enough
    to hit Bedrock's control-plane `list_foundation_models`, which is free
    and invokes no model.
    """
    try:
        import boto3
    except ImportError:
        return False

    try:
        region = (
            llm_cfg.get("region")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
        )
        session_kwargs = {}
        if llm_cfg.get("profile"):
            session_kwargs["profile_name"] = llm_cfg["profile"]
        session = boto3.Session(**session_kwargs)

        client_kwargs = {}
        if region:
            client_kwargs["region_name"] = region
        client = session.client("bedrock", **client_kwargs)
        client.list_foundation_models()
        return True
    except Exception:
        return False


def smoke_test() -> dict:
    """Run a health check via the MCP tools list."""
    response = _send("tools/list")
    if "error" in response:
        return {"ok": False, "detail": response["error"]["message"]}

    tools = response.get("result", {}).get("tools", [])
    if len(tools) >= 5:
        return {"ok": True, "detail": f"Connected to Brain ({len(tools)} tools available)"}
    elif len(tools) > 0:
        return {"ok": True, "detail": f"Connected to Brain ({len(tools)} tools found, expected 5+)"}
    return {"ok": False, "detail": "No tools found in tool/list response"}

def check_arc_tools() -> dict:
    """Check if ARC world-model tools are available in the tools list."""
    response = _send("tools/list")
    if "error" in response:
        return {"ok": False, "detail": response["error"]["message"]}

    tools = response.get("result", {}).get("tools", [])
    tool_names = {t["name"] for t in tools}

    missing = []
    if "publish_mechanic_summary" not in tool_names:
        missing.append("publish_mechanic_summary")
    if "recall_mechanic_priors" not in tool_names:
        missing.append("recall_mechanic_priors")

    if not missing:
        return {"ok": True, "detail": "ARC world-model tools available"}
    else:
        return {"ok": False, "detail": f"Missing ARC tools: {', '.join(missing)}"}


def check_sse_endpoint(port: int = 7799) -> bool:
    """Check if the MCP HTTP endpoint is responding at the given port."""
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def check_remote_mcp_surface(port: int = 7799, host: str = "127.0.0.1") -> dict:
    """B325: verify the streamable-HTTP MCP surface (`POST /mcp`) is up and
    advertises the same tools the Unix-socket transport does — the two
    dispatch paths sharing `campy.brain_daemon.route_tool_call()` is what
    makes that comparison meaningful rather than coincidental. This is a
    smoke check against an already-running daemon, not a bind-guard test
    (see tests/test_bind_guard.py for the startup-time hard-failure
    behavior this function can't observe from outside the process)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(
        f"http://{host}:{port}/mcp", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "detail": f"remote MCP surface unreachable: {e}"}

    if "error" in payload:
        return {"ok": False, "detail": payload["error"].get("message", "unknown error")}

    http_tools = {t["name"] for t in payload.get("result", {}).get("tools", [])}
    socket_response = _send("tools/list")
    socket_tools = {t["name"] for t in socket_response.get("result", {}).get("tools", [])}

    # HTTP's tool_schemas.TOOLS is a curated subset with published schemas
    # (see docs/ARCHITECTURE.md's Transports section) — every HTTP name
    # must still be one the socket transport actually knows how to
    # dispatch, but HTTP need not list every internal/unpublished tool.
    missing = http_tools - socket_tools
    if missing:
        return {"ok": False, "detail": f"HTTP-only tools not in socket dispatch: {sorted(missing)}"}
    if not http_tools:
        return {"ok": False, "detail": "remote MCP surface returned no tools"}

    return {"ok": True, "detail": f"Remote MCP surface OK ({len(http_tools)} tools, port {port})"}

def check_status() -> bool:
    """Print human-readable status and return True if healthy."""
    res = smoke_test()
    if res["ok"]:
        print(f"  [✓] {res['detail']}")
        # Also check LLM if possible
        return True
    else:
        print(f"  [✗] Daemon health check failed: {res['detail']}")
        return False

async def run_smoke_tests() -> dict:
    """
    Run full suite of smoke tests with retries for daemon startup.
    """
    results = {
        "Daemon Communication": False,
        "MCP Tool Visibility": False,
        "LLM Provider Connectivity": False,
        "Kùzu Health": False
    }

    # 1. Wait for Daemon (up to 10 seconds)
    max_retries = 5
    for i in range(max_retries):
        res = _send("tools/list")
        if "error" not in res:
            results["Daemon Communication"] = True
            tools = res.get("result", {}).get("tools", [])
            if len(tools) >= 5:
                results["MCP Tool Visibility"] = True
                results["Kùzu Health"] = True # tools/list confirms Kùzu is at least partially initialized
            break
        time.sleep(2)

    # 2. Check LLM (Ollama)
    # Try to find config to see what provider to check
    repo_root = Path(__file__).parent.parent.parent
    config_path = repo_root / "campy.toml"
    provider = "ollama"
    base_url = "http://localhost:11434/v1"
    llm_cfg: dict = {}

    if config_path.exists():
        try:
            import tomllib
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                llm_cfg = config.get("llm", {})
                provider = llm_cfg.get("provider", "ollama")
                base_url = llm_cfg.get("base_url", "http://localhost:11434/v1")
        except Exception:
            pass

    if provider == "ollama":
        results["LLM Provider Connectivity"] = check_ollama(base_url)
    elif provider == "bedrock":
        results["LLM Provider Connectivity"] = check_bedrock(llm_cfg)
    else:
        # For cloud providers, we just assume if we have an API key they are "connected"
        # because we don't want to burn tokens on a smoke test.
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY"
        }
        key_var = env_vars.get(provider)
        if key_var and os.environ.get(key_var):
            results["LLM Provider Connectivity"] = True
        else:
            # Check if it was in config
            results["LLM Provider Connectivity"] = False

    return results
