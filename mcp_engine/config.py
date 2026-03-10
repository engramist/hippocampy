"""
mcp_engine/config.py — Configuration Loader

Loads sidequests.toml using stdlib tomllib (Python 3.11+) or tomli fallback.
Returns a plain dict — all modules read config from this dict.
"""

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

    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    search_paths.append(Path.cwd() / "sidequests.toml")
    search_paths.append(Path.home() / ".sidequests" / "config.toml")

    for path in search_paths:
        if path.exists():
            with open(path, "rb") as f:
                config = tomllib.load(f)
            config["_config_path"] = str(path)
            return config

    raise FileNotFoundError(
        "sidequests.toml not found. Run: sidequests setup"
    )
