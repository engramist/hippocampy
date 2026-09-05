"""
mcp_engine/config.py — Configuration Loader

Loads campy/sidequests config using stdlib tomllib (Python 3.11+) or tomli fallback.
Returns a plain dict — all modules read config from this dict.
"""

from __future__ import annotations
import copy
import sys
from pathlib import Path


_DEFAULT_CONFIG = {
    "retrieval": {
        "lexical_window_days": 14,
        "lexical_limit": 10,
        "timeline_limit": 200,
    },
    # B283: supernode monitoring + session cache edge pruning
    "sweep": {
        "degree_report_top_k": 10,
        "degree_alert_threshold": 5000,
        "session_edge_ttl_days": 30,
        "prune_session_edges": True,
        "index_rebuild_archived_ratio": 0.5,
        "index_rebuild_enabled": True,
    },
    "loop": {
        "max_co_occurrence_pairs": 45,
    },
    "compression": {
        "strategy": "two_lane",       # two_lane (Protected Lane zero loss + Bulk Lane lossy)
        "budget_tokens": 4000,        # threshold above which pressure-relief compression triggers
        "compression_model": "",      # empty = inherit from [llm]
        "graph_prune_threshold": 0.30,
        "structured_format": "toon",
        "ast_compression": True,
    },
    # B304: ask harness variant toggle. "H0" = baseline, unchanged behavior.
    "ask": {
        "harness_variant": "H0",
    },
    # B325: remote MCP transport bind address + auth mode, explicit and
    # guarded (see campy/brain_daemon.py::_enforce_bind_guard). Defaults
    # reproduce today's local-only behavior exactly — bind_host stays
    # loopback and auth stays "none" unless a config file opts in.
    "server": {
        "bind_host": "127.0.0.1",
        "auth": "none",   # "none" | "iam" | "oidc"
    },
}


def _merge_defaults(config: dict, defaults: dict) -> dict:
    for key, default_value in defaults.items():
        if key not in config:
            config[key] = copy.deepcopy(default_value)
            continue

        current_value = config.get(key)
        if isinstance(default_value, dict) and isinstance(current_value, dict):
            _merge_defaults(current_value, default_value)
    return config


def load_config(config_path: str | Path | None = None) -> dict:
    """
    Load campy.toml. Searches in order:
      1. Explicit path (if provided)
      2. Current working directory
      3. ~/.campy/config.toml or legacy ~/.sidequests/config.toml
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
                f"config not found at {explicit}. Run: campy setup"
            )
        with open(explicit, "rb") as f:
            config = tomllib.load(f)
        _merge_defaults(config, _DEFAULT_CONFIG)
        config["_config_path"] = str(explicit)
        return config

    # No explicit path — search default locations.
    search_paths = [
        Path.cwd() / "campy.toml",
        Path.cwd() / "sidequests.toml",
        Path.home() / ".campy" / "config.toml",
        Path.home() / ".sidequests" / "config.toml",
    ]

    for path in search_paths:
        if path.exists():
            with open(path, "rb") as f:
                config = tomllib.load(f)
            _merge_defaults(config, _DEFAULT_CONFIG)
            config["_config_path"] = str(path)
            return config

    raise FileNotFoundError(
        "campy/sidequests config not found. Run: campy setup"
    )
