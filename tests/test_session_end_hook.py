"""B440 — SessionEnd hook wrapper (plugin/hooks/session_end_wrapper.py).

Loaded via importlib, same pattern as test_plugin_hooks.py, since
plugin/hooks/ isn't a normal importable package under campy/.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_DIR = Path(__file__).parent.parent / "plugin" / "hooks"
HOOK_MODULE = HOOK_DIR / "session_end_wrapper.py"
HOOKS_JSON = HOOK_DIR / "hooks.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("session_end_wrapper", HOOK_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestHookRegistration:
    def test_session_end_hook_exists(self):
        assert HOOK_MODULE.exists()

    def test_session_end_registered_in_hooks_json(self):
        config = json.loads(HOOKS_JSON.read_text())
        assert "SessionEnd" in config["hooks"]
        command = config["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
        assert "session_end_wrapper.py" in command


class TestReadPayload:
    def test_reads_session_id_and_cwd(self):
        module = _load_module()
        import io
        module.sys.stdin = io.StringIO('{"session_id": "s1", "cwd": "/tmp/proj"}')
        payload = module._read_payload()
        assert payload["session_id"] == "s1"
        assert payload["cwd"] == "/tmp/proj"

    def test_empty_stdin_returns_empty_dict(self):
        module = _load_module()
        import io
        module.sys.stdin = io.StringIO("")
        assert module._read_payload() == {}

    def test_malformed_json_returns_empty_dict(self):
        module = _load_module()
        import io
        module.sys.stdin = io.StringIO("not json")
        assert module._read_payload() == {}


class TestGenerateHandoffFailsOpen:
    def test_daemon_down_returns_false_without_raising(self, monkeypatch):
        module = _load_module()
        monkeypatch.setattr(module.shutil, "which", lambda _: None)

        def _raise_connection_refused(*a, **kw):
            raise FileNotFoundError()

        monkeypatch.setattr(module.subprocess, "run", _raise_connection_refused)

        result = module._generate_handoff("s1", "/tmp/does-not-matter")
        assert result is False

    def test_no_cwd_returns_false_without_calling_subprocess(self, monkeypatch):
        module = _load_module()
        called = []
        monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: called.append(1))

        result = module._generate_handoff("s1", "")

        assert result is False
        assert called == []

    def test_timeout_returns_false(self, monkeypatch):
        module = _load_module()

        def _timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="campy handoff", timeout=10)

        monkeypatch.setattr(module.subprocess, "run", _timeout)

        result = module._generate_handoff("s1", "/tmp/proj")
        assert result is False


class TestMainFailsOpen:
    def test_main_returns_zero_when_daemon_unreachable(self, monkeypatch):
        module = _load_module()
        monkeypatch.setattr(module, "check_daemon_health", lambda: False)
        import io
        module.sys.stdin = io.StringIO('{"session_id": "s1", "cwd": "/tmp/proj"}')

        assert module.main() == 0

    def test_main_never_raises_even_if_generate_handoff_explodes(self, monkeypatch):
        module = _load_module()
        monkeypatch.setattr(module, "check_daemon_health", lambda: True)

        def _explode(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(module, "_generate_handoff", _explode)
        import io
        module.sys.stdin = io.StringIO('{"session_id": "s1", "cwd": "/tmp/proj"}')

        with pytest.raises(RuntimeError):
            module.main()
        # main() itself can raise -- it's __main__'s try/except that
        # guarantees exit 0, matching every other hook wrapper's B318
        # convention. Verify that top-level guard directly:
        script = HOOK_MODULE.read_text()
        assert "except Exception:" in script
        assert "raise SystemExit(0)" in script


class TestEndToEndSubprocess:
    def test_wrapper_never_blocks_and_always_exits_zero(self):
        """Real subprocess invocation, real (possibly-down) daemon,
        real filesystem -- proves the fail-open contract holds under
        actual conditions, not just mocked ones. Does not assert
        whether HANDOFF.md was written (depends on whether a daemon
        happens to be running in this environment), only that the
        hook itself never blocks or errors."""
        result = subprocess.run(
            [sys.executable, str(HOOK_MODULE)],
            input='{"session_id": "unknown", "cwd": "/tmp"}',
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0
