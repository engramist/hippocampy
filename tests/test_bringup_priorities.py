"""
Targeted regression tests for the prioritized Codex + GPT Desktop bring-up checklist
in backlog.md.

Goal: one test per prioritized item where coverage was missing.
- Tests that describe pending fixes are marked xfail so they document expected behavior
  without breaking the current suite.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _patch_run_install_happy_path(monkeypatch, call_log: list[str], *, daemon_ok: bool = True):
    """Patch run_install dependencies so orchestration can be tested deterministically."""
    import campy.cli.install as install_mod

    monkeypatch.setattr(install_mod.click, "prompt", lambda *a, **k: "1")
    monkeypatch.setattr(install_mod.time, "sleep", lambda *_: None)

    class FakeOllamaInstaller:
        def setup(self):
            call_log.append("step1_ollama")
            return True

    class FakeVenvManager:
        def __init__(self, *a, **k):
            pass

        def create(self):
            call_log.append("step2_venv_create")
            return True

        def install_deps(self):
            call_log.append("step2_install_deps")
            return True

        def install_spacy_model(self):
            call_log.append("step2_spacy")
            return True

        def prewarm_embeddings(self):
            call_log.append("step2_prewarm")
            return True

    class FakeConfigWriter:
        @staticmethod
        def write(_cfg):
            call_log.append("step3_config")

    class FakeSchemaInitializer:
        def __init__(self, *_):
            pass

        def init(self):
            call_log.append("step4_schema")
            return True

    class FakeAdapterRegistrar:
        def __init__(self, *_):
            pass

        def register_all(self):
            call_log.append("step5_register")
            return {"codex": True, "chatgpt-desktop": True}

    class FakeDaemonSetup:
        def __init__(self, *_):
            pass

        def setup(self):
            call_log.append("step6_daemon")
            import subprocess
            subprocess.run(["pkill", "-f", "brain_daemon.py"], capture_output=True)
            subprocess.run(["pkill", "-f", "campy.daemon"], capture_output=True)
            return daemon_ok

    def fake_check_status():
        call_log.append("step7_smoke")
        return True

    monkeypatch.setattr(install_mod, "OllamaInstaller", FakeOllamaInstaller)
    monkeypatch.setattr(install_mod, "VenvManager", FakeVenvManager)
    monkeypatch.setattr(install_mod, "ConfigWriter", FakeConfigWriter)
    monkeypatch.setattr(install_mod, "SchemaInitializer", FakeSchemaInitializer)
    monkeypatch.setattr(install_mod, "AdapterRegistrar", FakeAdapterRegistrar)
    monkeypatch.setattr(install_mod, "DaemonSetup", FakeDaemonSetup)

    import campy.cli.smoke_test as smoke_mod

    monkeypatch.setattr(smoke_mod, "check_status", fake_check_status)
    monkeypatch.setattr(install_mod, "_wait_for_daemon", lambda **k: True)

    # Steps run_install calls that the fakes above do NOT cover. Without
    # these, the tests only pass on a machine where Ollama happens to be
    # running (verify_llm_connectivity probes localhost:11434 for real) and
    # they mutate the developer's environment (plugin_installer writes to
    # ~/.codex etc., FakeDaemonSetup's pkill kills a live campy daemon).
    monkeypatch.setattr(
        install_mod, "verify_llm_connectivity",
        lambda cfg: (True, "mocked connectivity"),
    )
    monkeypatch.setattr(install_mod, "_is_installed_mode", lambda: False)

    import campy.cli.plugin_installer as plugin_mod
    monkeypatch.setattr(plugin_mod, "install_plugin_for_agents", lambda: {})

    try:
        import campy.cli.indicator as indicator_mod
        monkeypatch.setattr(indicator_mod, "install_autostart", lambda: None)
    except ImportError:
        pass  # pystray extra not installed — run_install skips the step itself

    # Default subprocess guard: FakeDaemonSetup deliberately shells out to
    # pkill so the reload test can observe it; on a dev machine an unpatched
    # subprocess.run would genuinely kill the user's running brain daemon.
    # Individual tests may re-patch this to record calls.
    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda *a, **k: MagicMock(returncode=0))


# ---------------------------------------------------------------------------
# P0.1 — Installer seed-path packaging bug
# ---------------------------------------------------------------------------


def test_schema_initializer_uses_wheel_safe_seed_resource(tmp_path, monkeypatch):
    """Schema init should not rely on PROJECT_ROOT/InvertorsDocs absolute path."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python3").touch()

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return MagicMock(returncode=0, stdout="SCHEMA_OK\\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Mock Path.exists to simulate wheel-installed environment (no InvertorsDocs)
    from pathlib import Path
    original_exists = Path.exists
    
    def mocked_exists(self):
        if "InvertorsDocs" in str(self):
            return False
        if "campy/data" in str(self):
            return True
        return original_exists(self)
    
    monkeypatch.setattr(Path, "exists", mocked_exists)

    from campy.cli.install import SchemaInitializer, VenvManager

    vm = VenvManager(venv_dir=tmp_path)
    si = SchemaInitializer(vm)

    assert si.init() is True
    inline_script = captured["args"][2]

    # Verify seed_path in script is the resolved one, not the hardcoded dev one
    assert "GistSeedExamples.md" in inline_script
    assert "InvertorsDocs" not in inline_script


# ---------------------------------------------------------------------------
# P0.2 — launchd python interpreter resolution
# ---------------------------------------------------------------------------


def test_launchd_write_plist_resolves_real_python_interpreter(tmp_path, monkeypatch):
    """launchd plist should use a concrete interpreter path, not a pyenv shim path."""
    import plistlib
    import campy.cli.launchd as launchd

    plist_path = tmp_path / "agent.plist"
    log_path = tmp_path / "daemon.log"

    monkeypatch.setattr(launchd, "PLIST_PATH", plist_path)
    monkeypatch.setattr(launchd, "LOG_PATH", log_path)
    monkeypatch.setattr(launchd, "_daemon_script", lambda: "/tmp/brain_daemon.py")

    # Simulate pyenv shim resolution.
    monkeypatch.setattr(launchd.shutil, "which", lambda cmd: "/usr/local/bin/python3.12")
    monkeypatch.setattr(launchd.Path, "exists", lambda self: False)

    # Expected target interpreter after fix.
    import os

    monkeypatch.setattr(os.path, "realpath", lambda p: "/opt/homebrew/Cellar/python@3.12/bin/python3.12")

    out = launchd.write_plist()
    with open(out, "rb") as f:
        plist = plistlib.load(f)

    python_arg = plist["ProgramArguments"][0]
    assert python_arg == "/opt/homebrew/Cellar/python@3.12/bin/python3.12"


# ---------------------------------------------------------------------------
# P0.3 + P1.1 — install orchestration (7-step path)
# ---------------------------------------------------------------------------


def test_run_install_executes_all_7_steps_in_order(monkeypatch):
    """run_install should drive all 7 installer phases on the happy path."""
    import campy.cli.install as install_mod

    call_log: list[str] = []
    _patch_run_install_happy_path(monkeypatch, call_log, daemon_ok=True)

    install_mod.run_install()

    assert call_log == [
        "step1_ollama",
        "step2_venv_create",
        "step2_install_deps",
        "step2_spacy",
        "step2_prewarm",
        "step3_config",
        "step4_schema",
        "step5_register",
        "step6_daemon",
        "step7_smoke",
    ]


def test_run_install_forces_daemon_reload_before_smoke(monkeypatch):
    """Installer should force-reload daemon process to avoid stale tool registry."""
    import campy.cli.install as install_mod
    import subprocess

    call_log: list[str] = []
    _patch_run_install_happy_path(monkeypatch, call_log, daemon_ok=True)

    pkills = []
    def fake_subprocess_run(args, **kwargs):
        if args[0] == "pkill":
            pkills.append(" ".join(args))
        return MagicMock(returncode=0)
    
    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    # We want to see that setup() was called (which is in call_log as step6_daemon)
    # and that pkill was called.
    install_mod.run_install()

    assert "step6_daemon" in call_log
    assert any("pkill -f brain_daemon.py" in pk for pk in pkills)
    assert any("pkill -f campy.daemon" in pk for pk in pkills)
    assert call_log.index("step6_daemon") < call_log.index("step7_smoke")


# ---------------------------------------------------------------------------
# P2.1 — offline queue replay on recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_adapter_replays_offline_queue_after_recovery(tmp_path, monkeypatch):
    """After daemon comes back, codex adapter replays queued notify_turn entries first."""
    import adapters.codex.adapter as codex

    queue_file = tmp_path / "offline.jsonl"
    queue_file.write_text(
        json.dumps({
            "method": "notify_turn",
            "params": {"role": "user", "content": "queued", "session_id": "s1"},
            "ts": "2026-03-24T00:00:00Z",
        })
        + "\n",
        encoding="utf-8",
    )

    # Daemon was offline (queue has entries), but has now recovered.
    # Recovery detection fires when _daemon_online is False and the live call succeeds.
    monkeypatch.setattr(codex, "OFFLINE_QUEUE", queue_file)
    monkeypatch.setattr(codex, "_daemon_online", False)

    calls: list[tuple[str, dict]] = []

    async def fake_call_brain(method, params):
        calls.append((method, params))
        return {"status": "ok"}

    monkeypatch.setattr(codex, "_call_brain", fake_call_brain)

    # Trigger a live tool call — daemon is back, so it succeeds.
    await codex.handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "notify_turn",
                "arguments": {"role": "assistant", "content": "live", "session_id": "s1"},
            },
        }
    )

    # Live call executes first (it's the recovery trigger), then replay fires.
    # Total: 1 live call + 1 replayed queued entry.
    assert len(calls) >= 2
    # The queued entry is replayed (order: live call first, then replay)
    replayed = [c for c in calls if c[1].get("content") == "queued"]
    assert len(replayed) == 1, f"Expected 1 replayed queued call, got: {calls}"
    # Queue file must be deleted after replay
    assert not queue_file.exists()


@pytest.mark.asyncio
async def test_codex_adapter_queue_cleared_even_if_replay_entry_fails(tmp_path, monkeypatch):
    """Queue file is deleted before replay so a failed entry doesn't get re-queued."""
    import adapters.codex.adapter as codex

    queue_file = tmp_path / "offline.jsonl"
    queue_file.write_text(
        json.dumps({"method": "notify_turn",
                    "params": {"role": "user", "content": "will fail", "session_id": "s1"},
                    "ts": "2026-03-24T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(codex, "OFFLINE_QUEUE", queue_file)
    monkeypatch.setattr(codex, "_daemon_online", False)

    call_count = {"n": 0}

    async def fake_call_brain(method, params):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise RuntimeError("replay failed")
        return {"status": "ok"}

    monkeypatch.setattr(codex, "_call_brain", fake_call_brain)

    await codex.handle_mcp_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "notify_turn",
                   "arguments": {"role": "assistant", "content": "live", "session_id": "s1"}},
    })

    # Queue file must be gone regardless of replay entry failure
    assert not queue_file.exists()


# ---------------------------------------------------------------------------
# P2.2 — smoke-test readiness retry/backoff
# ---------------------------------------------------------------------------


def test_run_install_retries_smoke_until_ready(monkeypatch):
    """Installer should poll for daemon socket with retry helper, not a bare sleep."""
    import campy.cli.install as install_mod

    call_log: list[str] = []
    _patch_run_install_happy_path(monkeypatch, call_log, daemon_ok=True)

    # Replace _wait_for_daemon with a recording stub so we can verify it was used.
    wait_calls: list[dict] = []

    def fake_wait_for_daemon(max_wait: int = 20, interval: int = 2) -> bool:
        wait_calls.append({"max_wait": max_wait, "interval": interval})
        call_log.append("step7_wait")
        return True  # simulates socket appearing after polling

    monkeypatch.setattr(install_mod, "_wait_for_daemon", fake_wait_for_daemon)

    install_mod.run_install()

    # A retry-capable wait helper must be invoked with a meaningful max_wait window.
    assert len(wait_calls) == 1, "Expected exactly one _wait_for_daemon call"
    assert wait_calls[0]["max_wait"] >= 10, "max_wait should be at least 10 seconds"

    # wait must happen before smoke test.
    assert "step7_wait" in call_log
    assert "step7_smoke" in call_log
    assert call_log.index("step7_wait") < call_log.index("step7_smoke")
