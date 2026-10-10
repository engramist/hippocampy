"""
mcp_engine/config.py — Configuration Loader

Loads campy/sidequests config using stdlib tomllib (Python 3.11+) or tomli fallback.
Returns a plain dict — all modules read config from this dict.
"""

from __future__ import annotations
import copy
import json
import os
import sys
from pathlib import Path


_DEFAULT_CONFIG = {
    "retrieval": {
        "lexical_window_days": 14,
        "lexical_limit": 10,
        "timeline_limit": 200,
        # B479: conversation-stage boosts for the speaker / explicit date the
        # question names (a fraction of the best fused score; 0 = off).
        "speaker_boost": 0.0,
        "time_boost": 0.0,
        # B375: exposes warm_frontier.py's previously-hardcoded module
        # constants. Values match those prior hardcoded defaults exactly,
        # so an absent/partial [retrieval.warm_frontier] section changes
        # nothing for existing installs.
        "warm_frontier": {
            "max_warm_nodes": 20,
            "similarity_weight": 0.6,
            "hops_decay": 0.5,
            "min_activation": 0.3,
            "supernode_degree_threshold": 50,
            "supernode_top_n": 5,
        },
    },
    # B382: Dynamic Phase-Aware Model Router. Advisory only -- Campy
    # never calls a cloud model itself; route_task() just recommends a
    # tier for the caller. Defaults match model_router.py's own
    # DEFAULT_ROUTING_CONFIG exactly, so an absent/partial [routing]
    # section changes nothing for existing installs.
    "routing": {
        "enabled": True,
        "default_tier": "economy",
        "tiers": {
            "frontier": {
                "provider": "anthropic",
                "model": "claude-opus-5",
                "trigger_phases": ["planning"],
            },
            "economy": {
                "provider": "ollama",
                "model": "llama3.1:8b",
                "trigger_phases": ["implementation"],
            },
            "local_reflex": {
                "provider": "ollama",
                "model": "qwen2.5-coder:7b",
                "trigger_phases": ["reflex"],
            },
        },
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
    # B472 Phase 3: source-grounded Observations. Ships disabled until a
    # reader exists (Phase 5); 3a only declares the keys. The worker and the
    # LLM route (3b/3c) are the only consumers of the rest.
    "observations": {
        "enabled": False,
        "llm_enabled": True,       # only read when enabled
        "llm_batch_turns": 20,
        "idle_flush_seconds": 5,
        "max_turn_chars": 600,
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
        # M1.3 (B475): "cite" = answer only from the lines shown, quote the
        # line used, abstain when none answers; "legacy" = the pre-M1.3
        # "NOT empty ... must be used" instruction.
        "answer_style": "cite",
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


# ---------------------------------------------------------------------------
# B385: 12-factor environment overrides. A container sets these instead of
# editing campy.toml. Applied after the file and defaults are loaded, so an
# env var always wins. A malformed value fails loudly at startup, naming the
# variable, rather than silently falling back to the file.
# ---------------------------------------------------------------------------

def _parse_bool(raw: str) -> bool:
    low = raw.strip().lower()
    if low in {"1", "true", "yes", "on"}:
        return True
    if low in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected true/false")


def _parse_json_str_map(raw: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError("expected a JSON object of string -> string")
    return value


def _parse_json_scope_map(raw: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
        for k, v in value.items()
    ):
        raise ValueError("expected a JSON object of string -> list of strings")
    return value


def _parse_json_str_list(raw: str) -> list:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError("expected a JSON list of strings")
    return value


def _parse_boost(raw: str) -> float:
    value = float(raw)
    if not 0.0 <= value <= 10.0:
        raise ValueError("expected a number 0-10")
    return value


def _parse_port(raw: str) -> int:
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError("expected a port number 1-65535")
    return port


# env var -> (config section, key, parser)
ENV_OVERRIDES: dict[str, tuple[str, str, object]] = {
    "CAMPY_SERVER_AUTH": ("server", "auth", str.strip),
    "CAMPY_SERVER_BIND_HOST": ("server", "bind_host", str.strip),
    "CAMPY_SERVER_DASHBOARD_ENABLED": ("server", "dashboard_enabled", _parse_bool),
    "CAMPY_WEB_PORT": ("web", "port", _parse_port),
    "CAMPY_LLM_PROVIDER": ("llm", "provider", str.strip),
    "CAMPY_LLM_MODEL": ("llm", "model", str.strip),
    "CAMPY_LLM_REGION": ("llm", "region", str.strip),
    "CAMPY_LLM_BASE_URL": ("llm", "base_url", str.strip),
    "CAMPY_RETRIEVAL_SPEAKER_BOOST": ("retrieval", "speaker_boost", _parse_boost),
    "CAMPY_RETRIEVAL_TIME_BOOST": ("retrieval", "time_boost", _parse_boost),
    "CAMPY_IAM_TENANT_ID": ("server", "iam_tenant_id", str.strip),
    "CAMPY_IAM_WORKSPACE_ID": ("server", "iam_workspace_id", str.strip),
    "CAMPY_IAM_WORKSPACE_MAP_JSON": ("server", "iam_workspace_map", _parse_json_str_map),
    "CAMPY_IAM_TENANT_MAP_JSON": ("server", "iam_tenant_map", _parse_json_str_map),
    "CAMPY_IAM_PRINCIPAL_SCOPE_MAP_JSON": ("server", "iam_principal_scope_map", _parse_json_scope_map),
    "CAMPY_IAM_DEFAULT_SCOPES_JSON": ("server", "iam_default_scopes", _parse_json_str_list),
}


def apply_env_overrides(config: dict, environ=None) -> dict:
    """Apply ENV_OVERRIDES to `config` in place and return it. Records the
    names (never the values) of applied variables in `_env_overrides`."""
    environ = os.environ if environ is None else environ
    applied = []
    for var, (section, key, parse) in ENV_OVERRIDES.items():
        raw = environ.get(var)
        if raw is None or raw == "":
            continue
        try:
            value = parse(raw)
        except (ValueError, TypeError) as e:
            raise ValueError(f"invalid {var}: {e}") from None
        if not isinstance(config.get(section), dict):
            config[section] = {}
        config[section][key] = value
        applied.append(var)
    config["_env_overrides"] = applied
    return config


def load_config(config_path: str | Path | None = None) -> dict:
    """
    Load campy.toml. Searches in order:
      1. Explicit path (if provided)
      2. Current working directory
      3. ~/.campy/config.toml or legacy ~/.sidequests/config.toml
         -- or, when CAMPY_HOME is set, only $CAMPY_HOME/config.toml (an
         isolated instance must never pick up the user's personal config)
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
        return apply_env_overrides(config)

    # No explicit path — search default locations.
    from campy.paths import home_override

    search_paths = [
        Path.cwd() / "campy.toml",
        Path.cwd() / "sidequests.toml",
    ]
    override = home_override()
    if override is not None:
        search_paths.append(override / "config.toml")
    else:
        search_paths += [
            Path.home() / ".campy" / "config.toml",
            Path.home() / ".sidequests" / "config.toml",
        ]

    for path in search_paths:
        if path.exists():
            with open(path, "rb") as f:
                config = tomllib.load(f)
            _merge_defaults(config, _DEFAULT_CONFIG)
            config["_config_path"] = str(path)
            return apply_env_overrides(config)

    raise FileNotFoundError(
        "campy/sidequests config not found. Run: campy setup"
    )
