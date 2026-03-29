# OpenClaw Standalone Install Guide

> B26 — standalone OpenClaw install guide for SideQuests Brain integration.
>
> Verified against repo state on 2026-03-26/27. OpenClaw CLI help checked locally on
> `2026.3.13`; SideQuests plugin/tool details taken from
> `extensions/sidequests-brain/openclaw.plugin.json` and `src/index.ts`.

---

## Goal

This guide sets up **OpenClaw standalone** with **SideQuests Brain** on a local machine,
without depending on NemoClaw. The target outcome is:

- OpenClaw gateway running locally
- Docker sandbox available
- SideQuests Brain daemon reachable at `http://127.0.0.1:7799`
- OpenClaw SideQuests plugin installed
- Memory tools available inside agent sessions
- Passive capture + auto-recall working across sessions

---

## What This Guide Covers

1. Install OpenClaw
2. Prepare sandbox runtime
3. Install and start SideQuests Brain
4. Install the OpenClaw SideQuests plugin from this repo
5. Configure OpenClaw so plugin tools are usable from agent sessions
6. Restart and verify the integration
7. Troubleshoot the common failure modes

---

## Prerequisites

### Required

- macOS or Linux
- Node.js + npm
- Docker-compatible runtime
  - macOS: OrbStack or Docker Desktop
  - Linux: Docker Engine
- Python environment capable of running SideQuests Brain
- OpenClaw CLI installed

### Nice to Have

- Ollama already running for local model use
- Discord bot token if you want chat-channel access

---

## 1) Install OpenClaw

```bash
npm install -g openclaw@latest
openclaw --version
```

Useful help commands:

```bash
openclaw --help
openclaw gateway --help
openclaw plugins --help
openclaw sandbox --help
```

---

## 2) Prepare Sandbox Runtime

OpenClaw uses Docker-based sandboxing. Make sure your container runtime is alive:

```bash
docker info >/dev/null && echo "Docker OK"
```

If you are on macOS and using OrbStack:

```bash
open -a OrbStack
```

If you need the OpenClaw sandbox image and do not already have it, build it from the
OpenClaw source repo you trust. Example flow:

```bash
git clone --depth 1 https://github.com/anthropics/openclaw.git /tmp/openclaw-src
docker build -t openclaw-sandbox:bookworm-slim /tmp/openclaw-src/sandbox/
```

Verify:

```bash
openclaw sandbox explain
```

---

## 3) Install / Start SideQuests Brain

If SideQuests Brain is not already installed, use the project installer first.

From this repo:

```bash
cd ~/Desktop/GitProjects/sidequests-brain
python3 -m sidequests.cli.main install
```

If you already have it installed, make sure the daemon is running and healthy.

Expected daemon URL used by the OpenClaw plugin:

- `http://127.0.0.1:7799`

Quick health checks:

```bash
curl -sS http://127.0.0.1:7799/health || true
curl -sS -X POST http://127.0.0.1:7799/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

If you need to start the daemon manually from the repo:

```bash
cd ~/Desktop/GitProjects/sidequests-brain
.venv/bin/python -u brain_daemon.py > /tmp/brain_daemon.log 2>&1 &
```

If you installed via `sidequests install`, prefer the managed service path instead of
manually backgrounding it.

---

## 4) Configure OpenClaw Base Settings

OpenClaw config lives at:

- `~/.openclaw/openclaw.json`

At minimum, make sure:

- the gateway is configured for local use
- sandboxing is enabled
- plugin trust is explicit
- plugin tools are allowed to surface to agent sessions

### Recommended Integration Snippet

Merge the following into `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "allow": ["sidequests-brain"]
  },
  "tools": {
    "sandbox": {
      "tools": {
        "alsoAllow": ["group:plugins"]
      }
    }
  },
  "agents": {
    "defaults": {
      "sandbox": {
        "mode": "all",
        "scope": "session"
      }
    }
  }
}
```

### Why these settings matter

- `plugins.allow`: avoids the recurring "plugins.allow is empty" trust warning and
  explicitly trusts the SideQuests plugin.
- `tools.sandbox.tools.alsoAllow: ["group:plugins"]`: this is the critical fix for tool
  surfacing in agent sessions. Without it, plugin-registered tools may exist at the gateway
  level but still be unavailable to the running agent.
- sandbox `mode: "all"`: safest default.

### Optional Explicit Allowlist

If you want to be extra explicit, you can also allow the individual memory tools:

```json
{
  "tools": {
    "sandbox": {
      "tools": {
        "allow": [
          "memory_recall",
          "memory_search",
          "memory_get",
          "memory_store",
          "memory_search_analogies",
          "memory_status",
          "memory_open_loops"
        ],
        "alsoAllow": ["group:plugins"]
      }
    }
  }
}
```

The SideQuests OpenClaw extension currently registers these 7 tools:

- `memory_recall`
- `memory_search` (alias)
- `memory_get` (alias)
- `memory_store`
- `memory_search_analogies`
- `memory_status`
- `memory_open_loops`

---

## 5) Install the SideQuests OpenClaw Plugin

From the SideQuests Brain repo root:

```bash
cd ~/Desktop/GitProjects/sidequests-brain
openclaw plugins install ./extensions/sidequests-brain
```

Useful plugin checks:

```bash
openclaw plugins list
openclaw plugins info sidequests-brain
openclaw plugins doctor
```

Notes:

- Plugin manifest ID: `sidequests-brain`
- Package name in the repo is aligned with the manifest: `@sidequests/sidequests-brain`
- The plugin defaults to Brain URL `http://127.0.0.1:7799`

---

## 6) Start or Restart the Gateway

Use the OpenClaw gateway service commands:

```bash
openclaw gateway status
openclaw gateway restart
```

If the gateway is not installed as a service yet:

```bash
openclaw gateway install
openclaw gateway start
```

For direct foreground testing:

```bash
openclaw gateway run --force
```

---

## 7) Verify the Integration

### A. Confirm plugin loads

```bash
openclaw plugins list
openclaw plugins info sidequests-brain
openclaw plugins doctor
```

You want the plugin present and no manifest/package mismatch errors.

### B. Confirm sandbox policy includes plugin tools

```bash
openclaw sandbox explain
```

You want to see either:

- `group:plugins` included via `alsoAllow`, or
- the individual `memory_*` tools in the effective allowlist.

### C. Confirm Brain daemon is reachable

The plugin warns if `http://127.0.0.1:7799` is down.

Manual probe:

```bash
curl -sS -X POST http://127.0.0.1:7799/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

### D. Confirm agent session sees memory tools

Start an agent/TUI session and ask it to use memory tools, or inspect session behavior after
startup. A healthy integration should support:

- explicit memory recall/search calls
- memory storage from agent turns
- passive ingestion of conversation turns
- auto-recall injection before agent start

The plugin registers a `before_agent_start` hook that prepends a memory block when relevant,
formatted like:

```text
<sidequests-memory>
[Decision] ...
[Constraint] ...
</sidequests-memory>
```

---

## Discord Integration (Optional)

If you want OpenClaw to operate through Discord after local setup:

```bash
openclaw channels add --channel discord --token <YOUR_BOT_TOKEN>
openclaw channels list
openclaw channels status --probe
```

You still want the local gateway + plugin + Brain daemon working first before adding chat
transport complexity.

---

## Common Failure Modes

### 1. Plugin installs but memory tools are unavailable in agent sessions

**Symptom:** plugin appears in `plugins list`, but the agent cannot call the memory tools.

**Cause:** sandbox tool policy is blocking plugin-registered tools.

**Fix:** ensure this exists in `~/.openclaw/openclaw.json`:

```json
{
  "tools": {
    "sandbox": {
      "tools": {
        "alsoAllow": ["group:plugins"]
      }
    }
  }
}
```

Then restart the gateway.

---

### 2. Startup warns that Brain daemon is unreachable

**Symptom:** plugin loads but logs warn that the Brain daemon is not reachable at
`http://127.0.0.1:7799`.

The plugin now distinguishes two cases:

**A. "No persistent service found"**
```
Brain Daemon not running and no persistent service found.
Run `sidequests install` or `sidequests setup` to register the daemon...
```
This means `sidequests install` (or `sidequests setup`) was never run. The Brain Daemon
is not configured to start at login. Fix:
```bash
sidequests install    # or: sidequests setup --target openclaw
```
This writes `~/Library/LaunchAgents/ai.sidequests.brain.plist` (macOS) or
`~/.config/systemd/user/sidequests-brain.service` (Linux) and enables `RunAtLoad + KeepAlive`
so the daemon starts at login and auto-restarts on crash.

**B. "Service registered but not reachable"**
```
Brain Daemon service is registered but not currently reachable at http://127.0.0.1:7799.
The service should restart automatically.
```
This means the plist/unit exists but the daemon is transiently down (crash, cold boot delay).
It should recover automatically. If it stays offline:
```bash
sidequests status                           # check what's wrong
launchctl start ai.sidequests.brain         # macOS: kick the service
systemctl --user start sidequests-brain     # Linux: kick the service
cat ~/.sidequests/daemon.log                # check daemon logs
```

**Opt-in auto-launch (advanced):** You can configure the plugin to attempt launching the daemon
itself when it detects no service is installed. Add to your OpenClaw plugin config:
```json
{ "brainUrl": "http://127.0.0.1:7799", "autoLaunch": true }
```
This is disabled by default to avoid duplicate daemon instances. Prefer the managed service path.

---

### 3. Plugin trust/config warnings on every startup

**Symptom:** repeated warnings around plugin allowlists.

**Fix:** set:

```json
{
  "plugins": {
    "allow": ["sidequests-brain"]
  }
}
```

`sidequests setup --target openclaw` now writes this explicit trust entry before running
`openclaw plugins install`, so the normal setup flow does not trip over the empty-allowlist
warning first.

---

### 4. Old tool count assumptions in logs/docs

Some older notes mention **5 memory tools**. Current repo state registers **7**:

- `memory_recall`
- `memory_search`
- `memory_get`
- `memory_store`
- `memory_search_analogies`
- `memory_status`
- `memory_open_loops`

If you see 5-tool logs, you are likely looking at an older installed plugin build rather than
this repo's current source state.

---

## Operational Notes

- The OpenClaw plugin is a thin bridge only. The memory logic lives in the Python Brain daemon.
- Transport from the plugin to the Brain daemon is **Streamable HTTP** via `POST /mcp`.
- The plugin supports:
  - passive ingestion from `llm_input` and `llm_output`
  - pre-run recall injection via `before_agent_start`
- The plugin does **not** manage the Brain daemon lifecycle by default. It warns on startup
  with a diagnostic message that distinguishes "service not installed" from "service temporarily
  unreachable". The recommended setup (`sidequests install`) configures a persistent user service
  (launchd on macOS, systemd on Linux) with `RunAtLoad + KeepAlive` so the daemon is available
  before OpenClaw starts and auto-recovers from crashes.
- Opt-in `autoLaunch` config is available for power users, but the managed service path is
  strongly preferred.

---

## Recommended Next Steps

After this guide is working manually:

1. ~~Implement `sidequests setup --target openclaw` (B25)~~ ✅ Done.
2. ~~Ensure the Brain daemon is installed as a persistent service for OpenClaw users (B41)~~ ✅ Done.
   - `sidequests install` now configures launchd (macOS) / systemd (Linux) with RunAtLoad + KeepAlive.
   - Plugin startup warning now distinguishes "service not installed" vs "service temporarily unreachable".
3. Keep this guide updated if OpenClaw CLI subcommands or plugin policy semantics change.

---

## Quick Verification Checklist

- [ ] `openclaw --version` works
- [ ] Docker runtime is healthy
- [ ] Brain daemon responds at `http://127.0.0.1:7799`
- [ ] `openclaw plugins install ./extensions/sidequests-brain` succeeds
- [ ] `plugins.allow` includes `sidequests-brain`
- [ ] sandbox tool policy includes `group:plugins` and/or explicit memory tools
- [ ] `openclaw gateway restart` succeeds
- [ ] `openclaw sandbox explain` shows plugin tools are reachable
- [ ] agent sessions can use SideQuests memory tools
