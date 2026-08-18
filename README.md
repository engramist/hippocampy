# HippoCampy

**One memory for all your coding agents.**

Local-first, graph-native AI memory for Claude Code, Codex, Gemini CLI, and VS Code
Copilot. Hit a token limit in one agent, open another, and it already knows what
you were doing.

<!-- TODO: record demo GIF per docs/demo-script.md and embed here -->

> Hit a context limit mid-task in Claude Code. Opened Codex in the same repo.
> First line printed, before any prompt:
> `[Campy] Working on B291 (branch: feat/x · abc1234). Next: wire the new tool
> into TOOL_HANDLERS.` No summary pasted. No re-explaining. Work continued.

## Quickstart

> **Not yet on PyPI.** `hippocampy` has not been published to PyPI yet
> (tracked in [`backlog/B236.md`](backlog/B236.md);
> [go/no-go status](docs/one-click-install-release-gate.md)). The commands
> below are the *recommended* install path once a release exists, and are
> kept here validated and ready to go — but **today**, use
> [Install from source](#install) instead, which always works.

```bash
pipx install hippocampy
campy setup     # detect and register with Claude Code, Codex, Gemini CLI, etc.
```

Then just use your agent as normal — Campy captures every turn in the background.

## How it works

Every turn is captured, run through a Gated Consolidation Loop (biomimetic
heuristics that filter noise into durable facts), and stored in an embedded
Kùzu graph — no server, nothing leaves your machine. Recall tools plus a
`CONTEXT.md` file bridge and a per-turn resume line mean memory shows up in your
agent's context without it having to ask. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the full design.

## What makes it different

- **Cross-agent continuity.** Switch between Claude Code, Codex, Gemini CLI, and
  VS Code Copilot mid-task — the resume line travels with you, not with the agent.
- **Local-first and private.** Kùzu runs embedded in-process. No cloud service,
  no server, your conversations never leave your machine.
- **Memory arrives, you don't ask for it.** A layered injection system (file
  bridge, associative hooks, anticipatory triggers) surfaces relevant context
  automatically, on top of on-demand recall tools.

## Install

> **No single command is "canonical" yet.** `hippocampy` is not published to
> PyPI, so `pipx install hippocampy` does not work today. Source install
> (below) is the one path guaranteed to work right now. See the
> [one-click install release gate](docs/one-click-install-release-gate.md)
> for the full go/no-go record and why this framing is honest rather than
> just "not finished yet."

**From source (works today):**

```bash
git clone git@github.com:engramist/hippocampy.git
cd hippocampy
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
campy setup       # detect and register AI agents
campy doctor       # verify everything works
campy start        # start the memory daemon
```

**Once published (recommended path, validated and ready — not live yet):**

```bash
pipx install hippocampy    # or: pip install hippocampy
campy setup                # detect and register AI agents
campy doctor                # verify everything works
campy start                 # start the memory daemon
```

<details>
<summary>Alternative install methods</summary>

**One-line bootstrap** (no local checkout needed — checks for a supported
Python, installs via `pipx`/`uv tool`/a managed venv, registers detected
agents, and starts the daemon. Inspect before running, since this installs a
daemon that reads your AI conversations. The script itself is validated
end-to-end — see [B237](backlog/B237.md)/[B238](backlog/B238.md) — but its
default install step depends on the not-yet-published PyPI package above,
so it will fail at that step until publication happens):

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh | bash
```

Inspect first (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/bootstrap.sh -o /tmp/campy-bootstrap.sh
bash /tmp/campy-bootstrap.sh --dry-run
bash /tmp/campy-bootstrap.sh
```

**Install script** (inspect before running, since this installs a daemon that
reads your AI conversations):

```bash
curl -fsSL https://raw.githubusercontent.com/engramist/hippocampy/main/scripts/install.sh -o /tmp/campy-install.sh
sh /tmp/campy-install.sh
```

**Via Smithery** (for MCP clients like Claude Desktop):

```bash
npx @smithery/cli install hippocampy --client claude
```

**Via Homebrew** (macOS, optional — not yet public; see
[docs/homebrew-install.md](docs/homebrew-install.md)):

```bash
brew tap engramist/campy
brew install hippocampy
campy install    # Homebrew only installs the CLI; finish setup explicitly
```

Homebrew is optional and secondary regardless of PyPI status — macOS users
who trust `brew` more than piping a shell script can use it once the tap is
public. The formula never creates `~/.campy`, starts the daemon, or
registers AI clients during `brew install` — that's `campy install` /
`campy doctor`, run by you afterward, same as every other install path.

</details>

### Verify the install

```bash
campy doctor              # full health check — Python version, DB, daemon, client registration
campy doctor --repair     # attempt automatic repair of anything doctor flags
campy status               # is the memory daemon running?
campy activity --follow    # live feed of captures/recalls as they happen
```

`campy doctor`'s "MCP Clients" and "Plugin Status" checks report,
per-client, whether **Codex**, **Claude Desktop**/**Claude Code**, and
**VS Code Copilot** are registered — a client that isn't installed on your
machine is reported as "not found," not a failure. See
[docs/troubleshooting-install.md](docs/troubleshooting-install.md) for fixes
to specific check failures.

### Where your memory lives

All captured memory — the Kùzu graph database, activity log, and config —
lives under `~/.campy` (or `~/.sidequests` if you have a pre-existing
install; Campy won't silently move it). **Installing, repairing, or
uninstalling never deletes this data by default.** Deleting it is a
separate, explicit step:

```bash
campy uninstall               # remove client registrations + daemon; keeps ~/.campy by default
campy uninstall --delete-data # separate, explicit step: also deletes ~/.campy (your memory)
```

See [docs/troubleshooting-install.md](docs/troubleshooting-install.md) for
the full breakdown of what each install/repair/uninstall path does and does
not touch.

## Requirements

Python 3.12 or 3.13, Kùzu 0.11.3 (installed automatically as a dependency).

## Status & Contributing

Alpha. Every PR runs through an automated security gate (CodeQL, Semgrep,
pip-audit) plus GitHub Copilot ecosystem review before a maintainer looks at it.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the full pipeline and
[docs/ecosystem-rules.md](docs/ecosystem-rules.md) for the layer boundaries every
contributor follows. Contributor navigation: [docs/codebase-anatomy.md](docs/codebase-anatomy.md).

## Optional: Local Graph Viewer

For inspecting your Campy graph directly, see
[tools/graph_viewer/README.md](tools/graph_viewer/README.md) — a read-only
browser built on the archived Kuzu Explorer project, kept out of the normal
install/runtime path.

---

**License:** Apache-2.0 — see [LICENSE](LICENSE).
**Patent Pending:** Campy includes patent-pending memory architecture (U.S. Provisional
Application #64/017,066, filed March 25, 2026). No patent has been granted. See
[PATENTS.md](PATENTS.md).
