# Install Troubleshooting

Common failures for the one-click install path (`scripts/bootstrap.sh`,
`campy install`, `campy setup`, `campy doctor`) and how to fix them. If you
just want the fastest path back to a working install, start with:

```bash
campy doctor --repair
```

`campy doctor --repair` fixes most of the problems on this page
automatically. The sections below explain what it fixes, what it can't fix,
and how to check by hand.

## Quick diagnostics

```bash
campy doctor            # full health check, human-readable
campy doctor --json     # same checks, machine-readable (for scripting)
campy doctor --repair   # attempt safe, automatic repairs
campy status            # daemon status only
campy activity --follow # live feed of what Campy is doing right now
campy activity --lines 20  # last 20 activity-log lines, no follow
```

`campy doctor` runs these checks, in order: Python Version, Installation
Mode, Runtime Dir, Config File, Database, Daemon, Activity Log, Fail-Open
State, Launchd (macOS only), MCP Clients, Plugin Status. The failure below is
organized by which of those checks reports the problem.

---

## Daemon socket missing

**Symptom:** `campy doctor` reports `Daemon  FAIL  not responding at
~/.campy/brain.sock` (or `~/.sidequests/brain.sock` on a legacy install).
`campy status` reports the daemon is not running.

**Cause:** the daemon was never started, crashed, or was killed without a
supervisor restarting it.

**Fix:**

```bash
campy start              # start the daemon in the foreground/background per platform
campy doctor --repair    # will also attempt to (re)start it as part of repair
campy status             # confirm it's now responding
```

If it starts and immediately dies, check `~/.campy/daemon.log` (not the
redacted `activity.log`) for a stack trace.

## Launchd plist missing (macOS)

**Symptom:** `campy doctor` reports `Launchd  FAIL  plist missing:
~/Library/LaunchAgents/<label>.plist`. Only relevant on macOS — on Linux
this check reports `not macOS` and always passes.

**Cause:** `campy install` didn't run, or ran with daemon auto-start
skipped, or the plist was manually removed.

**Fix:**

```bash
campy doctor --repair     # writes the plist and loads it via launchctl
campy status              # confirm the daemon is now running under launchd
```

If repair reports the plist was written but `launchctl` failed to load it,
check for a stale/legacy label already loaded (`launchctl list | grep
campy`) and unload it first (`launchctl unload <path>`).

## Codex TOML duplicate or malformed block

**Symptom:** `campy doctor` reports `MCP Clients` with `stale/repaired:
Codex`, or Codex itself fails to start / complains about `config.toml`.

**Cause:** `~/.codex/config.toml` has more than one `[mcp_servers.*]` block
for Campy (e.g. one under the legacy name `sidequests-brain` and one under
the current name), or a stale block still points at old module paths
(`sidequests.adapters`, `sidequests.cli`).

**Fix:**

```bash
campy doctor --repair     # re-registers Codex, replacing stale/duplicate blocks
```

If repair doesn't fully clean it up (e.g. you hand-edited the file and it's
now malformed TOML), open `~/.codex/config.toml`, remove every
`[mcp_servers.*]` block whose name looks Campy-related (`campy`,
`sidequests-brain`, `sidequests-brain-desktop`), save, then re-run `campy
doctor --repair` to write one clean block.

## Claude MCP entry already exists

**Symptom:** `campy setup` or `campy install` reports Claude Desktop/Claude
Code already has an entry; `campy doctor` shows `MCP Clients` with
`stale/repaired: Claude Desktop`.

**Cause:** an old entry (legacy name, or a stale path pointing at
`sidequests.*` modules) is already present in
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or the equivalent Claude Code config.

**Fix:**

```bash
campy doctor --repair     # rewrites the entry in place to the current name/path
```

Campy never creates a second, duplicate entry alongside the old one — repair
replaces in place. If you see two entries after a repair, that's a bug;
please report it rather than hand-editing around it.

## VS Code config missing

**Symptom:** `campy doctor`'s `Plugin Status` line lists VS Code under
"not detected" even though VS Code is installed.

**Cause:** either VS Code itself wasn't detected (`campy` looks for its
usual install locations), or its `mcp.json` doesn't have a Campy entry yet.

**Fix:**

```bash
campy setup     # re-run client detection and registration
```

Check `~/Library/Application Support/Code/User/mcp.json` (macOS) or the
platform-equivalent path afterward for a Campy entry. If VS Code is
installed somewhere non-standard, detection can miss it — this is a known
limitation, not something `doctor --repair` can fix automatically.

## Kùzu DB health check fails

**Symptom:** `campy doctor` reports `Database  FAIL` or an error opening
`~/.campy/brain.db`.

**Cause:** most commonly a version mismatch between the Kùzu database file
format on disk and the `kuzu` Python package version currently installed,
or the daemon was killed mid-write and left a lock file behind.

**Fix:**

```bash
campy status                       # confirm nothing is holding the DB open unexpectedly
campy doctor --repair              # safe repairs only; never deletes brain.db
```

`campy doctor --repair` **never deletes or truncates `brain.db`** — repair
is limited to config/registration issues, not database recovery. If the
database itself is corrupted, back it up first
(`cp ~/.campy/brain.db ~/.campy/brain.db.bak`) before attempting anything
destructive, and treat DB corruption as a bug report, not a routine
troubleshooting step.

## Ollama / embedding provider unavailable

**Symptom:** commands that need an LLM or embedding call fail with a
provider-not-available error (or, in CI/sandbox environments without
network access to Hugging Face, `RuntimeError: All embedding providers
failed`).

**Cause:** the configured local model provider (e.g. Ollama) isn't running,
isn't installed, or the configured model was never pulled; or, in isolated
sandboxes, the embedding provider can't reach its model host at all.

**Fix:**

```bash
ollama list              # confirm Ollama is installed and see pulled models
ollama pull qwen2.5:3b    # or whatever model campy.toml configures
campy doctor              # re-check after fixing the provider
```

If you're intentionally running Campy in a network-isolated environment,
set `HF_HUB_OFFLINE=1` (and configure a fully local provider) rather than
expecting outbound Hugging Face calls to succeed.

## Activity feed is empty

**Symptom:** `campy activity --follow` prints nothing, or `campy activity
--lines 5` says no activity log found.

**Cause:** either this is a genuinely fresh install with no captured turns
yet (expected — not a bug), or the activity log path doesn't exist because
the daemon has never successfully started.

**Fix:**

```bash
campy doctor                # check the "Activity Log" line for the resolved path
ls -la ~/.campy/activity.log  # does the file exist at all?
campy start                 # if the daemon isn't running, start it first
```

If `campy doctor` shows the Activity Log check passing (file exists) but
`--follow` still shows nothing, that's expected on a brand-new install —
activity appears once your AI agent actually starts sending turns through
Campy.

---

## Verifying each agent integration

`campy doctor`'s `MCP Clients` and `Plugin Status` lines report per-client
status, but here's how to check each of the four supported clients
directly if you want independent confirmation:

- **Codex:** `grep -n "mcp_servers.campy" ~/.codex/config.toml` should show
  a `[mcp_servers.campy]` block. `ls ~/.codex/skills/campy-memory/SKILL.md`
  should exist (installed by `campy install`/`campy setup`).
- **Claude Code:** `cat ~/.claude/plugins/hippocampy/.mcp.json` should
  exist. Inside Claude Code itself, running `/mcp` (or checking installed
  plugins) should list `hippocampy`.
- **Claude Desktop:** `cat "~/Library/Application Support/Claude/claude_desktop_config.json"`
  (macOS) should have a `campy` entry under `mcpServers`. Restart Claude
  Desktop after registration for it to pick up the new server.
- **VS Code Copilot:** `cat "~/Library/Application Support/Code/User/mcp.json"`
  (macOS; path varies by platform) should have a `campy` entry. `campy
  doctor`'s `Plugin Status` line reports `VS Code (config OK)` when this is
  correct.

If any of these are missing but the client is installed, re-run `campy
setup` (registers detected clients) or `campy doctor --repair` (also
repairs stale/duplicate entries).

## Where your memory lives, and what repair/uninstall will and won't touch

All user memory — the Kùzu graph database, activity log, config, and daemon
runtime state — lives under `~/.campy` (or `~/.sidequests` if you have a
pre-existing legacy install that hasn't been migrated; Campy will keep
using that path rather than silently moving your data). See
[`campy/paths.py`](../campy/paths.py) for the exact resolution logic.

- **`campy doctor --repair`** never deletes `~/.campy/brain.db`, activity
  logs, or config — it only fixes registration/config/daemon-supervision
  issues.
- **Uninstalling the package** (`pipx uninstall hippocampy`, `brew uninstall
  hippocampy`, or `pip uninstall hippocampy`) removes the CLI and its
  Python dependencies. It does **not** touch `~/.campy` by itself.
- **`campy uninstall`** (run before removing the package) is the supported
  way to clean up client registrations (Codex/Claude/VS Code config
  entries, launchd plist) while **preserving your memory data by default**.
- **`campy uninstall --delete-data`** is the explicit, separate opt-in step
  that actually deletes `~/.campy` (database, logs, config). This is
  intentionally a distinct flag from plain `campy uninstall` — deleting
  years of accumulated agent memory should never be a side effect of "I
  don't want the CLI installed anymore."

If you only ever run `campy uninstall` (no `--delete-data`) and later
reinstall, your memory picks up right where it left off.
