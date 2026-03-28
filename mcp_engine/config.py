"""
mcp_engine/config.py — Configuration Loader

Loads sidequests.toml using stdlib tomllib (Python 3.11+) or tomli fallback.
Returns a plain dict — all modules read config from this dict.
"""

from __future__ import annotations
import sys
from pathlib import Path


def load_config(config_path: str | Path | None = None) -> dict:
    """
    Load sidequests.toml. Searches in order:
      1. Explicit path (if provided)
      2. Current working directory
      3. ~/.sidequests/config.toml (global fallback)
    Raises FileNotFoundError if no config found.
    """
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    # If an explicit path is given, use it strictly — no fallback.
    if config_path:
        explicit = Path(config_path)
        if not explicit.exists():
            raise FileNotFoundError(
                f"sidequests.toml not found at {explicit}. Run: sidequests setup"
            )
        with open(explicit, "rb") as f:
            config = tomllib.load(f)
        config["_config_path"] = str(explicit)
        return config

    # No explicit path — search default locations.
    search_paths = [
        Path.cwd() / "sidequests.toml",
        Path.home() / ".sidequests" / "config.toml",
    ]

    for path in search_paths:
        if path.exists():
            with open(path, "rb") as f:
                config = tomllib.load(f)
            config["_config_path"] = str(path)
            return config

    raise FileNotFoundError(
        "sidequests.toml not found. Run: sidequests setup"
    )
