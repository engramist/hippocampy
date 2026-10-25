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
        # B503/B514: graph linking (default ON; env CAMPY_GRAPH_LINKING=0 turns it off). Writes
        # Message/Observation -> Concept links by rule. Gate R96 (fresh-ingest LoCoMo, with
        # entities, skos_vocab and owl_properties on, limit 0): 0.517 vs main 0.525, 7 gained /
        # 8 lost (neutral); Observations linked to a Concept 79.5% -> 94.9%, user Messages
        # with MENTIONS 0 -> 79.7%.
        # graph_linking_limit caps the retrieval WALK's items; 0 (the default) writes the links
        # but adds no walk section: the v1 walk hurt (R95: 7 gained / 14 lost) and its redesign
        # is gated separately. CAMPY_GRAPH_LINKING_LIMIT=12 restores the v1 walk.
        "graph_linking": True,
        "graph_linking_limit": 0,
        # B508/B514: SKOS vocabulary for kinds (default ON; env CAMPY_SKOS_VOCAB=0 turns it off;
        # part of the R96 stack, see graph_linking). Kinds are
        # consolidated by rule (same label, head noun), entity -INSTANCE_OF-> kind and
        # kind -BROADER-> kind replace the single IS_A, and the walk follows both.
        # skos_closematch_threshold: cosine at or above which two kinds get an advisory
        # CLOSE_MATCH edge (never merged); 0 turns it off.
        "skos_vocab": True,
        "skos_closematch_threshold": 0.90,
        # B501/B514: a user turn ending in "?" that also states something in the first
        # person counts as evidence. Default ON (gates: LongMemEval oracle preference
        # 0.30 -> 0.567, 10 gained / 2 lost; LoCoMo-10 replay pooled over 4 conversations
        # 0.526 -> 0.548, 22 gained / 10 lost, up on 3 of 4).
        # CAMPY_RETRIEVAL_CONVERSATION_EMBEDDED_STATEMENTS=0 turns it off.
        "conversation_embedded_statements": True,
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
    # B472 Phase 3: source-grounded Observations. On by default
    # (3c gate: LoCoMo-10 65 gained/39 lost p~0.014; shown only when the
    # conversation section does not hold the whole history).
    # CAMPY_OBSERVATIONS_ENABLED=0 / CAMPY_OBSERVATIONS_RETRIEVAL=0 turn off.
    "observations": {
        "enabled": True,
        "llm_enabled": True,       # only read when enabled
        "llm_batch_turns": 20,     # reserved: 3b extracts per turn and does not read these two
        "idle_flush_seconds": 5,
        "max_turn_chars": 600,
        "queue_max": 5000,         # 3b: bounded worker queue; a full queue drops the newest, counted
        "retrieval": True,         # 3c: feed the bundle's semantic section from Observations
        "observation_limit": 8,    # 3c: most Observations the semantic section carries
        # B504/B514 (default ON; env CAMPY_OBSERVATIONS_ENTITIES=0 turns it off): the extractor
        # also emits each claim's object entity + kind (and cardinality), validated by rule and
        # written as Concepts, and extracts facts stated inside requests and plans. Costs roughly
        # 20-40% more output tokens per fact-bearing turn. Gate R96 (see retrieval.graph_linking):
        # neutral on LoCoMo (7 gained / 8 lost); SHACL Observation conformance 90.4% -> 95.1%,
        # fragment Concepts 4.9% -> 2.9%, dict-repr objects 35 -> 0.
        "entities": True,
        # B509/B514 (default ON; env CAMPY_OWL_PROPERTIES=0 turns it off): has_attribute names
        # become OWL attribute properties (vocabulary nodes); a functional property's newer value
        # supersedes the older (this replaces B499's string rule below; they are never both applied).
        "owl_properties": True,
        # B507/B514 (default ON; env CAMPY_SHACL_GATE=0 turns it off): validate each draft against
        # the SHACL shapes before writing. Gate R93: neutral, 1 gained / 1 lost. If pyshacl/rdflib
        # cannot be imported the gate logs once and is skipped.
        "shacl_gate": True,
        # B522 (default OFF; env CAMPY_OBSERVATIONS_OBJECT_ROLES=1 turns it on): each Observation
        # records its subject and object Concepts as HAS_SUBJECT / HAS_OBJECT edges (OBSERVATION_ABOUT
        # is unchanged). Gate pending.
        "object_roles": False,
        # B523 (default OFF; env CAMPY_OBSERVATIONS_OWNERSHIP_RULE=1 turns it on): a grammar rule writes
        # `owns` Observations for first-person possession of an existing Concept ("my X Name", "I
        # adopted Name"), whatever predicate the extractor chose. Gate pending.
        "ownership_rule": False,
        "supersede": False,        # B499: newer attribute value supersedes older (CAMPY_OBSERVATIONS_SUPERSEDE=1)
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
    # B494: output-token cap on every LLM call, so a runaway generation
    # cannot run until the request timeout. 0 = no cap.
    "llm": {
        "max_tokens": 2048,
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


def _parse_port(raw: str) -> int:
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError("expected a port number 1-65535")
    return port


def _parse_nonneg_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise ValueError("expected an integer >= 0")
    return value


CONVERSATION_BUDGET_MODES = ("fit_all", "fill")


def _parse_budget_mode(raw: str) -> str:
    value = raw.strip().lower()
    if value not in CONVERSATION_BUDGET_MODES:
        raise ValueError("expected one of: " + ", ".join(CONVERSATION_BUDGET_MODES))
    return value


# env var -> (config section, key, parser)
ENV_OVERRIDES: dict[str, tuple[str, str, object]] = {
    "CAMPY_SERVER_AUTH": ("server", "auth", str.strip),
    "CAMPY_SERVER_BIND_HOST": ("server", "bind_host", str.strip),
    "CAMPY_SERVER_DASHBOARD_ENABLED": ("server", "dashboard_enabled", _parse_bool),
    "CAMPY_WEB_PORT": ("web", "port", _parse_port),
    # B472 Phase 3b: lets a benchmark harness switch Observations on without
    # touching the config file it writes (the daemon inherits the environment).
    "CAMPY_OBSERVATIONS_ENABLED": ("observations", "enabled", _parse_bool),
    # B472 Phase 3c: same reason, for the reader (independent of the writer).
    "CAMPY_OBSERVATIONS_RETRIEVAL": ("observations", "retrieval", _parse_bool),
    # B504: extraction emits object entities and kinds (Concepts + IS_A/MENTIONS edges).
    "CAMPY_OBSERVATIONS_ENTITIES": ("observations", "entities", _parse_bool),
    # B503: link user turns / Observations to Concepts and walk the links at retrieval.
    "CAMPY_GRAPH_LINKING": ("retrieval", "graph_linking", _parse_bool),
    # 0 keeps the write-path links but adds no walk section at retrieval.
    "CAMPY_GRAPH_LINKING_LIMIT": ("retrieval", "graph_linking_limit", _parse_nonneg_int),
    # B508: SKOS vocabulary for kinds (consolidation, INSTANCE_OF vs BROADER).
    "CAMPY_SKOS_VOCAB": ("retrieval", "skos_vocab", _parse_bool),
    # B507: the SHACL write gate (default off).
    "CAMPY_SHACL_GATE": ("observations", "shacl_gate", _parse_bool),
    # B509: OWL attribute properties; functional properties drive supersession.
    "CAMPY_OWL_PROPERTIES": ("observations", "owl_properties", _parse_bool),
    # B522: HAS_SUBJECT / HAS_OBJECT edges for each Observation's subject and object Concepts.
    "CAMPY_OBSERVATIONS_OBJECT_ROLES": ("observations", "object_roles", _parse_bool),
    # B523: first-person possession rule writes `owns` Observations.
    "CAMPY_OBSERVATIONS_OWNERSHIP_RULE": ("observations", "ownership_rule", _parse_bool),
    # B499: rule-based supersession of attribute Observations (default off).
    "CAMPY_OBSERVATIONS_SUPERSEDE": ("observations", "supersede", _parse_bool),
    "CAMPY_LLM_PROVIDER": ("llm", "provider", str.strip),
    "CAMPY_LLM_MODEL": ("llm", "model", str.strip),
    "CAMPY_LLM_REGION": ("llm", "region", str.strip),
    "CAMPY_LLM_BASE_URL": ("llm", "base_url", str.strip),
    "CAMPY_LLM_MAX_TOKENS": ("llm", "max_tokens", _parse_nonneg_int),
    "CAMPY_RETRIEVAL_CONVERSATION_TOKEN_BUDGET": ("retrieval", "conversation_token_budget", _parse_nonneg_int),
    "CAMPY_RETRIEVAL_CONVERSATION_NEIGHBOURS": ("retrieval", "conversation_neighbours", _parse_nonneg_int),
    "CAMPY_RETRIEVAL_CONVERSATION_BUDGET_MODE": ("retrieval", "conversation_budget_mode", _parse_budget_mode),
    "CAMPY_RETRIEVAL_CONVERSATION_EMBEDDED_STATEMENTS": ("retrieval", "conversation_embedded_statements", _parse_bool),
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
