"""tests/test_b417_legacy_kuzu_auto_heal.py — B417 proof.

Before this fix, `OxigraphClient.__init__` called `Path(db_path).mkdir(...)`
unconditionally. Oxigraph stores are always directories, so any pre-existing
*file* at that exact path — the default state of every user upgrading across
the Kùzu→Oxigraph cutover with a pre-cutover `~/.campy/brain.db` — made
`mkdir` raise `FileExistsError` and crash-loop the daemon before it could even
log anything useful.

The fix: on construction, if `db_path` exists and is not a directory, move it
aside to a timestamped, never-overwritten backup and proceed to create a
fresh store. Non-destructive, idempotent, and generic (it does not need to
recognize the Kùzu file format — any non-directory at a directory-store path
is, by construction, not a valid Oxigraph store).
"""

from __future__ import annotations

import logging

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient


def test_legacy_file_at_db_path_no_longer_crashes(tmp_path):
    """The exact real-world scenario: a pre-cutover single-file `brain.db`
    sitting at the store path. Construction must succeed, not raise
    FileExistsError."""
    db_path = tmp_path / "brain.db"
    db_path.write_bytes(b"not a real kuzu file, just needs to be a regular file" * 1000)
    original_size = db_path.stat().st_size

    client = OxigraphClient(db_path)  # must not raise

    assert db_path.is_dir(), "a fresh Oxigraph directory store must now exist at db_path"
    backups = list(tmp_path.glob("brain.db.kuzu-bak-*"))
    assert len(backups) == 1, f"expected exactly one backup, found {backups}"
    assert backups[0].stat().st_size == original_size, "backup must be byte-for-byte preserved"
    assert client.store is not None


def test_auto_heal_never_deletes_and_never_overwrites_a_prior_backup(tmp_path):
    """Constructing twice against the same legacy-file scenario (e.g. two
    daemon restarts before the operator notices) must not clobber the first
    backup — each gets its own timestamped name."""
    db_path = tmp_path / "brain.db"
    db_path.write_bytes(b"legacy kuzu content one")
    OxigraphClient(db_path)
    backups_after_first = list(tmp_path.glob("brain.db.kuzu-bak-*"))
    assert len(backups_after_first) == 1

    # Simulate the store somehow reverting to a non-directory state again
    # (defensive — should not happen in practice, but the guard must be safe
    # if it ever does): remove the fresh store dir, drop another "legacy" file.
    import shutil
    shutil.rmtree(db_path)
    db_path.write_bytes(b"legacy kuzu content two - a DIFFERENT prior state")

    OxigraphClient(db_path)
    backups_after_second = list(tmp_path.glob("brain.db.kuzu-bak-*"))
    assert len(backups_after_second) == 2, "second legacy file must get its own backup, not overwrite the first"

    # Both original files' bytes are recoverable, distinctly.
    contents = {b.read_bytes() for b in backups_after_second}
    assert b"legacy kuzu content one" in contents
    assert b"legacy kuzu content two - a DIFFERENT prior state" in contents


def test_normal_fresh_path_is_unaffected(tmp_path):
    """The overwhelmingly common case — a path that doesn't exist yet, or is
    already a directory (a real, already-created Oxigraph store) — must not
    trigger any backup at all."""
    fresh_path = tmp_path / "brain.db"
    OxigraphClient(fresh_path)
    assert not list(tmp_path.glob("*.kuzu-bak-*"))

    # Re-opening the now-real directory store must also be a no-op for the guard.
    OxigraphClient(fresh_path)
    assert not list(tmp_path.glob("*.kuzu-bak-*"))


def test_auto_heal_logs_an_actionable_warning(tmp_path, caplog):
    db_path = tmp_path / "brain.db"
    db_path.write_bytes(b"legacy")
    with caplog.at_level(logging.WARNING, logger="campy.brain.hippocampus.graph.oxigraph_client"):
        OxigraphClient(db_path)
    assert any("legacy" in r.message.lower() for r in caplog.records), (
        "expected a WARNING naming the legacy-file condition"
    )
    assert any("migrate" in r.message.lower() for r in caplog.records), (
        "expected the warning to point at the migration remediation"
    )


def test_memory_db_path_bypasses_the_guard_entirely():
    """':memory:' / None never touch the filesystem — nothing to heal."""
    OxigraphClient(None)
    OxigraphClient(":memory:")  # must not raise or attempt any filesystem check
