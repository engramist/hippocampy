"""tests/test_b423b_daemon_log_rotation.py — B423 daemon.log capping.

Before this, daemon.log was launchd's StandardOut/ErrorPath redirect and grew
unbounded (69 MB in the field). Now the daemon owns it via a RotatingFileHandler
and launchd redirects only pre-init output to a tiny daemon.boot.log.
"""

from __future__ import annotations

import logging

from campy.brain_daemon import (
    _StreamToLogger,
    _build_daemon_log_handler,
)


def test_daemon_log_handler_rotates_by_size(tmp_path):
    log = tmp_path / "daemon.log"
    handler = _build_daemon_log_handler(log, max_bytes=2000, backup_count=3)
    logger = logging.getLogger("test.b423b.rotate")
    logger.setLevel(logging.INFO)
    logger.handlers[:] = [handler]
    logger.propagate = False
    try:
        for i in range(500):
            logger.info("daemon log line %d — padded to force rotation over 2000 bytes", i)
    finally:
        handler.close()

    assert log.exists()
    assert log.stat().st_size <= 2000 + 1024, "active daemon.log not bounded by maxBytes"
    assert (tmp_path / "daemon.log.1").exists(), "expected a rotated backup"
    # backupCount respected — never more than N backups
    backups = list(tmp_path.glob("daemon.log.*"))
    assert len(backups) <= 3


def test_stream_to_logger_forwards_print_lines():
    logger = logging.getLogger("test.b423b.stream")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger.handlers[:] = [_Capture()]
    stream = _StreamToLogger(logger, logging.INFO)

    stream.write("hello daemon\n")          # full line → one record
    stream.write("partial ")                 # buffered, no newline yet
    stream.write("then rest\n")              # completes the buffered line
    assert records == ["hello daemon", "partial then rest"]

    stream.write("no-newline tail")          # flush emits the remainder
    stream.flush()
    assert records[-1] == "no-newline tail"
    assert stream.isatty() is False


def test_plist_redirects_launchd_to_boot_log_not_daemon_log(tmp_path):
    from campy.cli import launchd
    from campy.paths import get_daemon_boot_log_path, get_daemon_log_path

    plist_path = tmp_path / "test.plist"
    assert launchd.generate_plist("/path/to/brain_daemon.py", str(plist_path), "test.label")
    content = plist_path.read_text()

    boot = str(get_daemon_boot_log_path())
    daemon = str(get_daemon_log_path())
    assert f"<string>{boot}</string>" in content, "launchd should redirect to daemon.boot.log"
    # daemon.log must NOT be a launchd redirect target (the handler owns it; a
    # launchd fd there would fight rotation).
    assert f"<key>StandardOutPath</key>\n    <string>{daemon}</string>" not in content
    assert f"<key>StandardErrorPath</key>\n    <string>{daemon}</string>" not in content
