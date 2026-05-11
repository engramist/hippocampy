"""Centralized path and resource resolution for installed-mode operation.

This module provides helpers for resolving:
- Package data locations (configs, templates, assets)
- Runtime state directories (user data under ~/.sidequests)
- Package root (for development/editable installs)

Use these helpers instead of __file__, os.path.dirname, or hardcoded paths.

Related card: B230 - Packaging Hardening for Installed Mode
"""

import os
from importlib import resources
from pathlib import Path


def runtime_dir() -> Path:
    """Get or create the SideQuests runtime data directory.

    Returns:
        Path to ~/.sidequests with correct permissions (0o700).

    This directory is created with restricted permissions to protect:
    - Local Kuzu database (brain.db)
    - Daemon socket (brain.sock)
    - Activity logs
    - User-created memories and sessions
    """
    runtime = Path.home() / ".sidequests"
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    return runtime


def package_root() -> Path:
    """Get the root of the installed sidequests package.

    Works for both:
    - Regular installs (package under site-packages)
    - Editable installs (symlink to source tree)

    Returns:
        Path to sidequests package root.
    """
    return Path(__file__).resolve().parent


def resource_path(package: str, name: str) -> Path:
    """Resolve a package resource file path.

    Works for both development and installed modes by using importlib.resources.

    Args:
        package: Dotted package name (e.g., 'sidequests', 'sidequests.adapters')
        name: Filename within the package (e.g., 'config.toml', 'template.md')

    Returns:
        Path to the resource file.

    Examples:
        >>> config = resource_path('sidequests', 'default_config.toml')
        >>> schema = resource_path('sidequests', 'schema.sql')
    """
    try:
        # Python 3.9+: files() API
        resource_path_obj = resources.files(package).joinpath(name)
        return Path(str(resource_path_obj))
    except (AttributeError, TypeError):
        # Fallback for older Python or resource not found
        return package_root() / name


def get_config_dir() -> Path:
    """Get the directory for user configuration files.

    Returns:
        Path to ~/.sidequests/config
    """
    config_dir = runtime_dir() / "config"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return config_dir


def get_config_path() -> Path:
    """Get the primary SideQuests user config file path."""
    return runtime_dir() / "config.toml"


def get_daemon_socket_path() -> Path:
    """Get the path for the daemon socket file.

    Returns:
        Path to ~/.sidequests/brain.sock
    """
    return runtime_dir() / "brain.sock"


def get_database_path() -> Path:
    """Get the path for the Kuzu database file.

    Returns:
        Path to ~/.sidequests/brain.db
    """
    return runtime_dir() / "brain.db"


def get_activity_log_path() -> Path:
    """Get the path for the activity log file.

    Returns:
        Path to ~/.sidequests/activity.log
    """
    return runtime_dir() / "activity.log"


def get_daemon_log_path() -> Path:
    """Get the path for the daemon log file.

    Returns:
        Path to ~/.sidequests/daemon.log
    """
    return runtime_dir() / "daemon.log"


def get_launchd_plist_path() -> Path:
    """Get the path for the launchd plist file (macOS only).

    Returns:
        Path to ~/Library/LaunchAgents/ai.sidequests.brain.plist
    """
    launchd_dir = Path.home() / "Library" / "LaunchAgents"
    launchd_dir.mkdir(parents=True, exist_ok=True)
    return launchd_dir / "ai.sidequests.brain.plist"


def get_bin_dir() -> Path:
    """Get the directory for runtime wrapper scripts.

    Returns:
        Path to ~/.sidequests/bin (for generated entry point wrappers)
    """
    bin_dir = runtime_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    return bin_dir


def ensure_runtime_paths() -> None:
    """Initialize all runtime directories with correct permissions.

    Called during installation/setup to ensure ~/.sidequests is ready.
    """
    runtime_dir()  # Creates ~/.sidequests with 0o700
    get_config_dir()  # Creates ~/.sidequests/config
    get_bin_dir()  # Creates ~/.sidequests/bin


__all__ = [
    "runtime_dir",
    "package_root",
    "resource_path",
    "get_config_dir",
    "get_config_path",
    "get_daemon_socket_path",
    "get_database_path",
    "get_activity_log_path",
    "get_daemon_log_path",
    "get_launchd_plist_path",
    "get_bin_dir",
    "ensure_runtime_paths",
]
