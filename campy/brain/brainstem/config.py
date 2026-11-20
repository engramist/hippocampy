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
        # B524 (default ON since B575; env CAMPY_GRAPH_COUNT=0 turns it off): a count/list question ("how many pets does
        # X have") adds a `graph_count` bundle section computed by a subject-anchored graph query (needs the
        # B522 object_roles and B523 ownership_rule edges). Gate pending.
        "graph_count": True,
        # Step 3 of the e2e plan (default OFF; env CAMPY_GRAPH_FACTS=1 turns it on; in no profile until gated): the
        # subject-anchored query_hits.* rows enter the bundle as a `graph_facts` section in the fact contract's
        # fixed-shape lines, shaped by the question analysis. When on, the graph_count section is not built.
        "graph_facts": False,
        # Object-text matching (default OFF; env CAMPY_OBJECT_TEXT_MATCH=1 turns it on; in no profile until gated;
        # needs graph_facts): the question's words are matched by sentence vector against the object text of the
        # subject's own live facts (top 3 per word, cosine >= 0.75); the matched facts are read with the exact-label
        # ones in the graph_facts section. Reads only; writes nothing.
        "object_text_match": False,
        # B547 (default ON since B575; env CAMPY_QUESTION_ANALYSIS=0 turns it off): the
        # question is analysed once (shape, subject, kind, the Concepts it names) at the top of the bundle
        # compile and the stages read that instead of parsing it themselves. Gate: with the profile (B545).
        "question_analysis": True,
        # B548 (default ON since B575; env CAMPY_GRAPH_VOTE=0 turns it off): the graph's
        # list (evidence turns of the subject's Observations that match the kind asked or the entities named)
        # joins vector and lexical in conversation seed selection. Needs question_analysis. Gate: with the
        # profile (B545).
        "graph_vote": True,
        # B578 (default ON since the window-mode gates, 2026-11-19; env CAMPY_TURN_RERANK=0 turns it off): a
        # cross-encoder reranks the conversation section's turns plus the top 100 Messages by vector score;
        # graph-vote turns keep their slots. The model is read from a local folder (turn_rerank_path, env
        # CAMPY_TURN_RERANK_PATH); nothing is downloaded, and without it the section is unchanged (one
        # warning per process). Gates: job 1011 +2.3 points, job 1012 +2.8 (682 of 809 prompts shared).
        "turn_rerank": True,
        "turn_rerank_model": "Xenova/ms-marco-MiniLM-L-6-v2",
        "turn_rerank_path": "",
        # B578 modes: "window" (default; ND-7, passed both gates) keeps the section's turn count and fills it with
        # reranked seeds, each with its session window; "replace" (killed, -2.2) and "add" (killed, -5.3) remain
        # for comparison only.
        "turn_rerank_mode": "window",
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
        # B544: every named entity (PERSON, WORK_OF_ART, GPE, ORG, PRODUCT, LOC, FAC, EVENT,
        # NORP) step 1 finds in a user turn becomes a Concept with its NER label and a MENTIONS
        # edge from the turn, whatever Loop steps 2 and 4 decide. Default ON since B575.
        # CAMPY_ENTITY_ADMISSION=0 turns it off.
        "entity_admission": True,
        # B549 (default ON since B575; env CAMPY_ENTITY_STANDING=0 turns it off): an admitted entity's standing
        # (confirmed | doubtful | unverified) is derived by rule from a speaker list and capitalisation evidence, the
        # tagger's label staying evidence; a wrapped span ("Yep Deb") is trimmed to the name it holds. The kind guard,
        # the kind-label guard and the B547 persons read it. A no-op without entity_admission. Gate: part of the
        # principled-profile gate.
        "entity_standing": True,
        # B543 (default ON since B575; env CAMPY_TRACKER_SIDE_BRANCH=0 turns it off): Loop steps
        # 2-7 (the original decision tracker, deprecated) only add records: a contradiction verdict stores the new
        # Concept and a DisambiguationEvent and archives nothing, and a Loop failure never drops the turn's
        # Observation extraction. Warns at daemon start when entity_admission is off. Gate: part of the
        # principled-profile gate.
        "tracker_side_branch": True,
        # B560 (default ON since B575; env CAMPY_SPOKEN_BY=0 turns it off): a user turn's named
        # speaker is linked from the turn by `Message -SPOKEN_BY-> Concept` (the speaker's Person Concept, the one the
        # Loop already seeds). The concept walk (B503, B560) reads it to keep only the subject's own turns. Gate: part
        # of the principled-profile gate.
        "spoken_by": True,
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
        # B522 (default ON since B575; env CAMPY_OBSERVATIONS_OBJECT_ROLES=0 turns it off): each Observation
        # records its subject and object Concepts as HAS_SUBJECT / HAS_OBJECT edges (OBSERVATION_ABOUT
        # is unchanged). Gate pending.
        "object_roles": True,
        # B523 (default ON since B575; env CAMPY_OBSERVATIONS_OWNERSHIP_RULE=0 turns it off): a grammar rule writes
        # `owns` Observations for first-person possession of an existing Concept ("my X Name", "I
        # adopted Name"), whatever predicate the extractor chose. Gate pending.
        "ownership_rule": True,
        # B525 (default ON since B575; env CAMPY_KIND_HYGIENE=0 turns it off): a kind label is written as a clean singular
        # noun ("my dogs" -> "dog", the wording kept as an altLabel) and a meta-noun ("name", "thing", ...) is
        # never a kind. Gate pending.
        "kind_hygiene": True,
        # B534 (default ON since B575; env CAMPY_WORDNET_KINDS=0 turns it off): when a kind is created, WordNet (if
        # installed) proposes BROADER links to existing kinds that are its hypernyms, and from existing
        # narrower kinds to it. Closed set; each link carries link_source "wordnet". Gate pending.
        "wordnet_kinds": True,
        # B535 (default ON since B575; env CAMPY_VOCAB_STEWARD=0 turns it off): a vocabulary steward above the NLP pipeline
        # proposes kind parents, entity kinds and reviews of WordNet links, each from a closed numbered list.
        # Everything it writes is a candidate (invisible to retrieval) until an independent source agrees
        # (WordNet's closure, the same proposal from two evidence sets, or a second model family set under
        # [llm.steward_second]). The steward's own model is [llm.steward] (default: the global [llm]). Gate pending.
        "vocab_steward": True,
        # B546 (default ON since B575; env CAMPY_TYPED_OBJECTS=0 turns it off): the object of a fact is a typed entity. At
        # Observation write time a rule links the object to an existing admitted Concept (HAS_OBJECT) or, when no
        # entity is named, to one ObjectPhrase node per Observation, and types it (INSTANCE_OF) from a kind the
        # sentence states, WordNet places, the conversation's speakers, or the head noun matched to a kind that
        # exists; else it is only a candidate. No model call; no Concept is created except a kind. Gate pending
        # (judged with the principled profile, B545).
        "typed_objects": True,
        # B554 (default ON since B575; env CAMPY_EVIDENCE_ENTITY_LINKS=0 turns it off): an Observation is linked
        # (OBSERVATION_ABOUT) to every entity B544 admitted whose occurrence lies in its evidence: the quote located
        # in its source turn, then the clause holding it (dependency parse). The model's wording plays no part.
        # A no-op without [loop] entity_admission. Gate: part of the principled-profile gate.
        "evidence_entity_links": True,
        # B564 (default OFF; env CAMPY_OBSERVATION_ROLES=1 turns it on; in no profile until step 1 of the
        # 2026-11-10 plan passes its gate): the extraction form gains "action", "with" and "place"; a rule confirms each
        # span in the turn and writes HAS_ACTION (a WordNet action Concept), HAS_PARTICIPANT and HAS_PLACE. No backfill.
        "roles": False,
        # Item 3 of the 2026-11-10 plan (user ruling 2026-11-14; default OFF; env CAMPY_OBSERVATION_GROUP_SUBJECTS=1; in no
        # profile): the extraction prompt also asks for facts about "we" and people named by relation ("my kids"); a rule
        # anchors "we" on the speaker (group_subject) and "my kids" on a relation Concept RELATION_OF the speaker.
        "group_subjects": False,
        # User ruling 2026-11-15 (default OFF; env CAMPY_OBSERVATION_GROUP_ANCHOR=1; in no profile): a fact the extractor
        # already proposes about "we" gets the speaker as subject (group_subject = true), by rule; the prompt is untouched
        # and no relation ("my ...") Concept is made. A partner only as the PERSON X in "X and I" or after "with".
        "group_anchor": False,
        "supersede": False,        # B499: newer attribute value supersedes older (CAMPY_OBSERVATIONS_SUPERSEDE=1)
        # B538 (default ON; env CAMPY_TURN_DATES=0 turns it off): every user turn's relative time
        # expressions ("yesterday", "last week") are resolved by rule against the turn's date at
        # capture (TimeMention nodes) and shown as "yesterday [= 2023-05-07]" in the bundle.
        # Gate R104 vs R103 (unseen LoCoMo): 0.450 -> 0.503, 28 gained / 12 lost, all 5 conversations up.
        "turn_dates": True,
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
    # ND-15: one B339 data boundary per prompt section instead of one per line (off by default).
    "answer": {
        "boundary_per_section": False,
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
    # B524: count/list questions answered by a subject-anchored graph query (bundle section).
    "CAMPY_GRAPH_COUNT": ("retrieval", "graph_count", _parse_bool),
    # Step 3: the query_hits rows as a fixed-shape bundle section (replaces graph_count when on).
    "CAMPY_GRAPH_FACTS": ("retrieval", "graph_facts", _parse_bool),
    # 2026-11-17: the answer instruction style (cite | legacy | cite_answer); cite is the default.
    "CAMPY_ANSWER_STYLE": ("ask", "answer_style", str),
    # ND-15: one B339 boundary per prompt section (off by default).
    "CAMPY_ANSWER_BOUNDARY_PER_SECTION": ("answer", "boundary_per_section", _parse_bool),
    # Object-text matching: question words matched by vector to the object text of the subject's facts (graph_facts).
    "CAMPY_OBJECT_TEXT_MATCH": ("retrieval", "object_text_match", _parse_bool),
    # B547: the question is analysed once; stages read the analysis (bundle section `reads`, `bundle.analysis`).
    "CAMPY_QUESTION_ANALYSIS": ("retrieval", "question_analysis", _parse_bool),
    # B548: the graph votes in conversation seed selection (needs question_analysis).
    "CAMPY_GRAPH_VOTE": ("retrieval", "graph_vote", _parse_bool),
    # B578: the turn reranker (off by default) and the local folder its model is read from.
    "CAMPY_TURN_RERANK": ("retrieval", "turn_rerank", _parse_bool),
    "CAMPY_TURN_RERANK_PATH": ("retrieval", "turn_rerank_path", str.strip),
    "CAMPY_TURN_RERANK_MODE": ("retrieval", "turn_rerank_mode", lambda v: str(v).strip().lower()),
    # B508: SKOS vocabulary for kinds (consolidation, INSTANCE_OF vs BROADER).
    "CAMPY_SKOS_VOCAB": ("retrieval", "skos_vocab", _parse_bool),
    # B544: admit every named entity of a user turn as a Concept (default on since B575).
    "CAMPY_ENTITY_ADMISSION": ("loop", "entity_admission", _parse_bool),
    # B549: a named entity's standing is derived by rule; the tagger's label stays evidence (default on since B575).
    "CAMPY_ENTITY_STANDING": ("loop", "entity_standing", _parse_bool),
    # B543: Loop steps 2-7 (the deprecated decision tracker) only add records (default on since B575).
    "CAMPY_TRACKER_SIDE_BRANCH": ("loop", "tracker_side_branch", _parse_bool),
    # B560: a turn's named speaker is linked by SPOKEN_BY (default on since B575).
    "CAMPY_SPOKEN_BY": ("loop", "spoken_by", _parse_bool),
    # B507: the SHACL write gate (default off).
    "CAMPY_SHACL_GATE": ("observations", "shacl_gate", _parse_bool),
    # B509: OWL attribute properties; functional properties drive supersession.
    "CAMPY_OWL_PROPERTIES": ("observations", "owl_properties", _parse_bool),
    # B522: HAS_SUBJECT / HAS_OBJECT edges for each Observation's subject and object Concepts.
    "CAMPY_OBSERVATIONS_OBJECT_ROLES": ("observations", "object_roles", _parse_bool),
    # B523: first-person possession rule writes `owns` Observations.
    "CAMPY_OBSERVATIONS_OWNERSHIP_RULE": ("observations", "ownership_rule", _parse_bool),
    # B525: kind labels are clean singular nouns; meta-nouns are never kinds.
    "CAMPY_KIND_HYGIENE": ("observations", "kind_hygiene", _parse_bool),
    # B534: WordNet proposes BROADER links between existing kinds.
    "CAMPY_WORDNET_KINDS": ("observations", "wordnet_kinds", _parse_bool),
    # B535: the vocabulary steward proposes kind links and entity kinds from closed choices.
    "CAMPY_VOCAB_STEWARD": ("observations", "vocab_steward", _parse_bool),
    # B546: the object of a fact is a typed entity (HAS_OBJECT to a Concept or an ObjectPhrase, INSTANCE_OF by rule).
    "CAMPY_TYPED_OBJECTS": ("observations", "typed_objects", _parse_bool),
    # B554: an Observation is linked (OBSERVATION_ABOUT) to the admitted entities its evidence names.
    "CAMPY_EVIDENCE_ENTITY_LINKS": ("observations", "evidence_entity_links", _parse_bool),
    # B564: the action / with / place roles of a fact (default off; not in a profile yet).
    "CAMPY_OBSERVATION_ROLES": ("observations", "roles", _parse_bool),
    # Item 3: "we" and people named by relation as subjects (default off; in no profile).
    "CAMPY_OBSERVATION_GROUP_SUBJECTS": ("observations", "group_subjects", _parse_bool),
    # 2026-11-15: "we" facts anchored on the speaker by rule, prompt untouched (default off; in no profile).
    "CAMPY_OBSERVATION_GROUP_ANCHOR": ("observations", "group_anchor", _parse_bool),
    # B538: relative dates in user turns resolved by rule at capture and shown inline (default on).
    "CAMPY_TURN_DATES": ("observations", "turn_dates", _parse_bool),
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


# ---------------------------------------------------------------------------
# B545: pipeline profiles. A profile is a named set of flag values; it adds no
# behaviour of its own (each part keeps its own flag, P7). Precedence for one
# flag, highest first: its env var > an explicit value in the user's config file
# > the profile > the built-in default. "main" is the empty table: today's
# defaults, unchanged. Choose with `[pipeline] profile = "..."` or CAMPY_PROFILE.
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = "main"
PROFILE_ENV = "CAMPY_PROFILE"

PROFILES: dict[str, dict[str, dict[str, object]]] = {
    "main": {},
    # B575 (review session ruling under the user's delegation, 2026-11-18): step 4 and step 0c measured the old
    # principled profile tied with main twice (+0.2 and +0.7 points on the 809), so its 14 members are now the
    # built-in defaults and the concept walk (graph_linking_limit 12) was deleted from it. "principled" is kept
    # as a name for the same config, so recorded runs and scripts that set CAMPY_PROFILE=principled still load.
    "principled": {},
}

# Flags `campy status` and benchmark provenance report: every profile member, plus current-default
# flags the profile leaves as they are (they are part of "what ran").
PROFILE_STAYS_ON = (
    ("observations", "enabled"), ("observations", "retrieval"), ("observations", "entities"),
    ("observations", "owl_properties"), ("observations", "shacl_gate"), ("observations", "turn_dates"),
    ("retrieval", "graph_linking"), ("retrieval", "skos_vocab"), ("retrieval", "graph_linking_limit"),
    # B575: the former principled members, default on since step 4.
    ("loop", "entity_admission"), ("loop", "entity_standing"), ("loop", "tracker_side_branch"), ("loop", "spoken_by"),
    ("observations", "object_roles"), ("observations", "ownership_rule"), ("observations", "kind_hygiene"),
    ("observations", "wordnet_kinds"), ("observations", "vocab_steward"), ("observations", "typed_objects"),
    ("observations", "evidence_entity_links"),
    ("retrieval", "graph_count"), ("retrieval", "question_analysis"), ("retrieval", "graph_vote"),
    # B578: on by default (window mode); reported so a run records whether the reranker was on.
    ("retrieval", "turn_rerank"), ("retrieval", "turn_rerank_mode"),
)


# B553: profile members that read WordNet (the optional extra `wordnet`: nltk + its corpus). Without it they
# run but do less (B523 falls back to graph kinds, B534/B535 propose no WordNet links, B546 types nothing).
# Decision (user, 2026-11-05): the profile warns, it does not refuse to start.
PROFILE_NEEDS_WORDNET = (
    ("observations", "ownership_rule"), ("observations", "wordnet_kinds"),
    ("observations", "vocab_steward"), ("observations", "typed_objects"),
)


def wordnet_available() -> bool:
    """Whether NLTK and its WordNet corpus load (the one check: temporal_lobe/lexicon/wordnet.py)."""
    try:
        from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

        return wn_mod.available()
    except Exception:
        return False


def wordnet_degraded(config: dict, available: bool | None = None) -> list[str]:
    """The switched-on flags that read WordNet, when WordNet is missing ([] when it is present)."""
    if available is None:
        available = wordnet_available()
    if available:
        return []
    return [f"{sec}.{key}" for sec, key in PROFILE_NEEDS_WORDNET if (config.get(sec) or {}).get(key) is True]


def warn_if_wordnet_missing(config: dict, available: bool | None = None) -> list[str]:
    """Log one warning naming the members that degrade without WordNet; returns them."""
    import logging

    degraded = wordnet_degraded(config, available)
    if degraded:
        logging.getLogger(__name__).warning(
            "profile %r: WordNet is not installed, so %s run degraded; install it with "
            "`pip install 'hippocampy[wordnet]' && python -m nltk.downloader wordnet`",
            config.get("_profile", DEFAULT_PROFILE), ", ".join(degraded))
    return degraded


def profile_flag_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for table in PROFILES.values():
        for section, items in table.items():
            for key in items:
                if (section, key) not in keys:
                    keys.append((section, key))
    return keys + [k for k in PROFILE_STAYS_ON if k not in keys]


def resolve_profile_name(file_config: dict, environ=None) -> str:
    """Env CAMPY_PROFILE > `[pipeline] profile` > "main". An unknown name raises: a typo must
    never silently run `main` and be recorded as a different pipeline (P6)."""
    environ = os.environ if environ is None else environ
    raw = (environ.get(PROFILE_ENV) or "").strip()
    source = PROFILE_ENV
    if not raw:
        raw = str(((file_config.get("pipeline") or {}).get("profile")) or "").strip()
        source = "[pipeline] profile"
    name = (raw or DEFAULT_PROFILE).lower()
    if name not in PROFILES:
        raise ValueError(f"invalid {source}: unknown profile {raw!r}; known profiles: {', '.join(sorted(PROFILES))}")
    return name


def apply_profile(config: dict, environ=None) -> dict:
    """Fill the profile's values into `config` (the user's file, before defaults are merged) where
    the file sets no value of its own. Records `_profile` and, per reported flag, `_profile_sources`."""
    import logging

    name = resolve_profile_name(config, environ)
    sources: dict[str, str] = {}
    for section, items in PROFILES[name].items():
        if not isinstance(config.get(section), dict):
            config[section] = {}
        for key, value in items.items():
            if key in config[section]:
                sources[f"{section}.{key}"] = "file"
                if config[section][key] != value:
                    logging.getLogger(__name__).warning(
                        "profile %r wants %s.%s = %r but the config file sets %r; the file wins",
                        name, section, key, value, config[section][key])
            else:
                config[section][key] = copy.deepcopy(value)
                sources[f"{section}.{key}"] = "profile"
    # B575: any reported flag the file sets is "file", profile member or not (both profiles are empty now).
    for section, key in profile_flag_keys():
        if isinstance(config.get(section), dict) and key in config[section]:
            sources.setdefault(f"{section}.{key}", "file")
    config["_profile"] = name
    config["_profile_sources"] = sources
    return config


def _finish_config(config: dict, environ=None) -> dict:
    apply_profile(config, environ)
    _merge_defaults(config, _DEFAULT_CONFIG)
    apply_env_overrides(config, environ)
    return config


def profile_report(config: dict) -> dict:
    """{"profile": name, "flags": {"section.key": {"value", "source"}}} for a loaded config. Source is
    env / file / profile / default, so a flag pinned by the user's file shows as such."""
    sources = dict(config.get("_profile_sources") or {})
    env_hit = set(config.get("_env_overrides") or [])
    env_for = {(sec, key): var for var, (sec, key, _p) in ENV_OVERRIDES.items()}
    flags: dict[str, dict] = {}
    for section, key in profile_flag_keys():
        name = f"{section}.{key}"
        value = (config.get(section) or {}).get(key)
        if value is None:
            value = (_DEFAULT_CONFIG.get(section) or {}).get(key)
        source = sources.get(name, "default")
        if env_for.get((section, key)) in env_hit:
            source = "env"
        flags[name] = {"value": value, "source": source}
    available = wordnet_available()
    return {"profile": config.get("_profile", DEFAULT_PROFILE), "flags": flags,
            "wordnet": {"available": available, "degraded": wordnet_degraded(config, available)}}


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
        config["_config_path"] = str(explicit)
        return _finish_config(config)

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
            config["_config_path"] = str(path)
            return _finish_config(config)

    raise FileNotFoundError(
        "campy/sidequests config not found. Run: campy setup"
    )
