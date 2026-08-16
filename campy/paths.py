"""Centralized path and resource resolution for installed-mode operation.

New HippoCampy installs use ``~/.campy``. Existing SideQuests installs keep
using ``~/.sidequests`` until the user explicitly migrates, which protects
existing memory databases from surprise moves.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from campy.branding import (
    LEGACY_LAUNCHD_LABEL,
    LEGACY_RUNTIME_DIR,
    PRIMARY_LAUNCHD_LABEL,
    PRIMARY_RUNTIME_DIR,
)


def legacy_runtime_dir() -> Path:
    """Return the legacy SideQuests runtime directory without creating it."""
    return Path.home() / LEGACY_RUNTIME_DIR


def primary_runtime_dir() -> Path:
    """Return the primary HippoCampy runtime directory without creating it."""
    return Path.home() / PRIMARY_RUNTIME_DIR


def runtime_dir() -> Path:
    """Get or create the active runtime data directory.

    Fresh installs create ``~/.campy``. If ``~/.sidequests`` already exists and
    ``~/.campy`` does not, continue using the legacy path to avoid moving or
    duplicating user memory data implicitly.
    """
    primary = primary_runtime_dir()
    legacy = legacy_runtime_dir()
    runtime = legacy if legacy.exists() and not primary.exists() else primary
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    return runtime


def package_root() -> Path:
    """Get the root of the installed sidequests compatibility package."""
    return Path(__file__).resolve().parent


def resource_path(package: str, name: str) -> Path:
    """Resolve a package resource file path."""
    try:
        return Path(str(resources.files(package).joinpath(name)))
    except (AttributeError, TypeError):
        return package_root() / name


def get_config_dir() -> Path:
    config_dir = runtime_dir() / "config"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return config_dir


def get_config_path() -> Path:
    return runtime_dir() / "config.toml"


def get_legacy_config_path() -> Path:
    return legacy_runtime_dir() / "config.toml"


def get_daemon_socket_path() -> Path:
    return runtime_dir() / "brain.sock"


def get_database_path() -> Path:
    return runtime_dir() / "brain.db"


def get_activity_log_path() -> Path:
    return runtime_dir() / "activity.log"


def get_daemon_log_path() -> Path:
    return runtime_dir() / "daemon.log"


def get_launchd_plist_path(label: str = PRIMARY_LAUNCHD_LABEL) -> Path:
    launchd_dir = Path.home() / "Library" / "LaunchAgents"
    launchd_dir.mkdir(parents=True, exist_ok=True)
    return launchd_dir / f"{label}.plist"


def get_legacy_launchd_plist_path() -> Path:
    return get_launchd_plist_path(LEGACY_LAUNCHD_LABEL)


def get_bin_dir() -> Path:
    bin_dir = runtime_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    return bin_dir


def tables_dir() -> Path:
    """Return path to tabular data storage directory, creating if needed."""
    d = runtime_dir() / "tables"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_backup_root() -> Path:
    """Return the root directory for `campy backup` snapshots, creating it.

    B319. Layout is workspace-first (``<root>/<workspace_id>/<timestamp>/``)
    so a single-database install (today: one implicit ``local`` workspace)
    and a future B316 multi-workspace router both fall out of the same
    directory walk with no rewrite — see ``campy/cli/backup.py``.
    """
    d = runtime_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def ensure_runtime_paths() -> None:
    runtime_dir()
    get_config_dir()
    get_bin_dir()
    tables_dir()


__all__ = [
    "legacy_runtime_dir",
    "primary_runtime_dir",
    "runtime_dir",
    "package_root",
    "resource_path",
    "get_config_dir",
    "get_config_path",
    "get_legacy_config_path",
    "get_daemon_socket_path",
    "get_database_path",
    "get_activity_log_path",
    "get_daemon_log_path",
    "get_launchd_plist_path",
    "get_legacy_launchd_plist_path",
    "get_bin_dir",
    "tables_dir",
    "get_backup_root",
    "ensure_runtime_paths",
]
