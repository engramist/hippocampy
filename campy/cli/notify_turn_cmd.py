"""
campy/cli/notify_turn_cmd.py — `campy notify-turn` CLI subcommand.

Thin wrapper over call_brain_soft("notify_turn", ...) used by the
.githooks/post-commit hook to force a WorkSummary checkpoint on commit.

Usage:
    campy notify-turn --role system --content "committed: abc1234 fix auth bug"
"""
import asyncio
import typer
from typing import Optional

app = typer.Typer(help="Send a turn to the Campy brain daemon.", hidden=True)


@app.callback(invoke_without_command=True)
def notify_turn_cmd(
    role: str = typer.Option("system", "--role", "-r", help="Role: user | assistant | system"),
    content: str = typer.Option(..., "--content", "-c", help="Turn content to capture"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s"),
):
    """Send a single turn to the daemon (used by git hooks and scripts)."""
    import os
    import subprocess

    repo_root = ""
    git_branch = "main"
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        git_branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
    except Exception:
        pass

    sid = session_id or f"git-hook-{os.getpid()}"
    params = {
        "role": role,
        "content": content,
        "session_id": sid,
        "agent_source": "git_hook",
        "repo_root": repo_root,
        "git_branch": git_branch,
    }

    # B318: fail-open — this is a git hook (implicit, no human waiting on a
    # direct answer), so a slow/unreachable daemon must never fail or hold
    # up the commit. call_brain_soft() degrades to `default` on any failure
    # and never raises; CAPTURE_TIMEOUT is the write-path budget.
    from campy.brain_transport import CAPTURE_TIMEOUT, call_brain_soft
    asyncio.run(call_brain_soft("notify_turn", params, timeout=CAPTURE_TIMEOUT))
