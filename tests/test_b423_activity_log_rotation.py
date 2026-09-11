"""tests/test_b423_activity_log_rotation.py — B423 proof.

activity.log is append-only and was never rotated (found at 26 MB in the field).
emit_activity now rolls it to `.1` once it reaches the configured max_bytes, so the
live operator feed stays bounded without an external logrotate.
"""

from __future__ import annotations

import json

from campy.brain.hippocampus import schema  # noqa: F401 (import parity with suite)
from campy.brain.brainstem.activity_log import emit_activity


def _cfg(path, max_bytes):
    return {"activity": {"log_path": str(path), "max_bytes": max_bytes}}


def test_activity_log_rotates_at_max_bytes(tmp_path):
    log = tmp_path / "activity.log"
    cfg = _cfg(log, 500)  # tiny cap so a few records trip it

    for i in range(200):
        emit_activity("tool", config=cfg, method="notify_turn", status="ok",
                      details={"i": i})

    backup = tmp_path / "activity.log.1"
    assert backup.exists(), "expected a rotated .1 backup once over max_bytes"
    # live file stays bounded (< cap + one record's worth), never the full history
    assert log.stat().st_size < 500 + 512
    # newest record survived in the live file
    last = log.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(last)["details"]["i"] == 199


def test_rotation_disabled_when_max_bytes_zero(tmp_path):
    log = tmp_path / "activity.log"
    cfg = _cfg(log, 0)  # 0 disables rotation
    for i in range(200):
        emit_activity("tool", config=cfg, method="notify_turn", details={"i": i})
    assert not (tmp_path / "activity.log.1").exists()
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 200
