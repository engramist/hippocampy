"""
sidequests CLI — setup, start, stop, status commands.

Entry point: `sidequests` (defined in pyproject.toml [project.scripts])
"""

import click


@click.group()
@click.version_option(package_name="sidequests-brain")
def cli() -> None:
    """SideQuests Brain Daemon — persistent AI memory."""
    pass


@cli.command()
@click.option(
    "--target",
    type=click.Choice(
        ["claude-code", "claude-desktop", "codex", "codex-desktop",
         "chatgpt-desktop", "gemini-cli", "all"],
        case_sensitive=False,
    ),
    default="all",
    show_default=True,
    help="Which AI client to register. 'all' auto-detects installed clients.",
)
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    default=None,
    help="Project root for .mcp.json (Claude Code). Defaults to current directory.",
)
def setup(target: str, project_root: str | None) -> None:
    """[Deprecated — use `sidequests install`] Detect AI clients, register adapters, and start the Brain Daemon."""
    from sidequests.cli.setup import run_setup
    run_setup(target=target, project_root=project_root)


@cli.command()
def install() -> None:
    """One-command installer: LLM setup, dependencies, schema, adapters, daemon."""
    from sidequests.cli.install import run_install
    run_install()


@cli.command()
def start() -> None:
    """Start the Brain Daemon in the foreground (for debugging)."""
    from sidequests.cli.daemon_ctl import start_daemon
    start_daemon()


@cli.command()
def stop() -> None:
    """Stop the Brain Daemon background service."""
    from sidequests.cli.daemon_ctl import stop_daemon
    stop_daemon()


@cli.command()
def status() -> None:
    """Check if the Brain Daemon is running and healthy."""
    from sidequests.cli.smoke_test import check_status
    import sys
    ok = check_status()
    sys.exit(0 if ok else 1)


@cli.command("review")
@click.option("--limit", default=20, show_default=True,
              help="Maximum number of open loops to show.")
def review(limit: int) -> None:
    """Review unresolved tentative knowledge nodes (open loops)."""
    import asyncio
    import json
    from pathlib import Path
    from sidequests.cli.smoke_test import _send

    async def _run():
        try:
            resp = await _send("get_open_loops", {"limit": limit})
            loops = resp.get("result", {}).get("open_loops", [])
            if not loops:
                print("No open loops — all nodes confirmed or archived.")
                return
            print(f"\nOpen loops ({len(loops)}):\n")
            for item in loops:
                conf = item.get("confidence", 0)
                print(f"  [{item.get('gist_class', '?')}] {item['text_raw'][:80]}")
                print(f"    confidence={conf:.2f}  id={item.get('concept_id', '?')}")
                print()
        except Exception as e:
            print(f"Error: {e}\nIs the Brain Daemon running? Try `sidequests status`.")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
