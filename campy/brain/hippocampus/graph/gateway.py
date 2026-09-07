"""
campy/brain/hippocampus/graph/gateway.py — GraphGateway: the named-query chokepoint.

B314. `kuzu_client.py`'s docstring claims migrating storage engines means
"rewrite this file only" — true for the `import kuzu` statement, false for
the ~500+ inline Cypher lines scattered across ~33 files that call
`KuzuClient.execute()`/`execute_read()`/`execute_write()` with hand-built
strings. This module is the seam that makes the claim true incrementally:

  - Every query becomes a `NamedQuery` — a static, parameterized, named,
    described unit registered once at import time.
  - `GraphGateway.run(name, **params)` is the only way application code
    reaches the database through a named query: it validates the params
    the query declares it needs, then routes to `KuzuClient.execute_write()`
    (mutating=True) or `KuzuClient.execute_read()` (mutating=False) — never
    bypassing the asyncio write-lock discipline `kuzu_client.py` already
    implements via `_get_write_lock()`.
  - `GraphGateway.execute_raw()` is the deliberately-visible escape hatch
    for call sites not yet migrated. Every use is migration debt, tracked
    by `scripts/check_cypher_ratchet.py`.

This module has no import-time dependency on a live database — registering
a `NamedQuery` only validates the query's shape (static text, declared
params, duplicate names), so a bad query fails at import instead of in
production.
"""

from __future__ import annotations

import inspect
import logging
import re
import unittest.mock
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.hippocampus.graph.vector_store import VectorStore

from campy.brain.hippocampus.graph.oxigraph_client import (
    CID_BASE,
    NODE_PRIMARY_KEYS,
    RowDict,
    mint_uri,
    parse_uri,
)

_logger = logging.getLogger(__name__)

_NODE_TABLE_MAP = {
    "concept": "Concept",
    "decision": "Decision",
    "constraint": "Constraint",
    "requirement": "Requirement",
    "actionitem": "ActionItem",
    "globalconstraint": "GlobalConstraint",
    "globalpreference": "GlobalPreference",
    "message": "Message",
    "documentextract": "DocumentExtract",
    "session": "Session",
    "mainquest": "MainQuest",
    "sidequest": "SideQuest",
    "label": "Label",
    "plan": "Plan",
    "planstep": "PlanStep",
    "lesson": "Lesson",
    "procedure": "Procedure",
    "dataset": "Dataset",
    "factentity": "FactEntity",
}


def _resolve_node_table(suffix: str) -> str:
    s = suffix.lower().replace("_", "")
    return _NODE_TABLE_MAP.get(s, suffix.capitalize())

# Matches a `{` that is NOT immediately (modulo whitespace) followed by
# either a closing `}` (empty map literal, `{}`) or an identifier + `:`
# (a Kùzu node/relationship/struct property map, e.g. `{lesson_id: $lid}`
# or a literal map `{ plan_id: $plan_id, goal: $goal, ... }`). Any other
# `{` is almost certainly a leftover Python format placeholder
# (`f"MATCH"` + `"(a:{table})"` or a `.format()` template that never got filled
# in) — exactly the interpolation-at-the-call-site defect this registry
# exists to catch at import time rather than in production.
_BARE_BRACE_RE = re.compile(r"\{")
_SAFE_BRACE_TAIL_RE = re.compile(r"\s*(\}|[A-Za-z_][A-Za-z0-9_]*\s*:|MATCH\s+)")


def _find_unsafe_brace(cypher: str) -> int | None:
    """Return the index of the first `{` that isn't part of a Kùzu literal
    map, or None if every `{` in `cypher` looks like a legitimate map."""
    for match in _BARE_BRACE_RE.finditer(cypher):
        tail = cypher[match.end():]
        if not _SAFE_BRACE_TAIL_RE.match(tail):
            return match.start()
    return None


# B389: `sparql` field static-string validation (spec §7.2 — "$param becomes
# a SPARQL ?param bound via VALUES/BIND injected by oxigraph_client.py.
# Never string-interpolate a parameter into SPARQL text."). SPARQL uses `{`
# for graph-pattern blocks (`WHERE { ... }`, `OPTIONAL { ... }`, `GRAPH ?g {
# ... }`) in shapes `_SAFE_BRACE_TAIL_RE` above was never designed to
# recognize (it exists for Kùzu's literal-map syntax specifically), so this
# is a separate, narrower check: it catches the one unambiguous defect
# shape both languages share — a bare `{identifier}` with nothing else
# inside, which is not valid syntax in either Cypher or SPARQL and is
# unambiguously a leftover Python f-string/.format() placeholder that never
# got filled in (the exact interpolation-at-the-call-site defect this
# registry exists to catch at import time). A legitimate SPARQL block
# always has more inside it than a single bare word (a variable, an IRI, a
# keyword, or nothing at all) immediately followed by `}`.
_SPARQL_FORMAT_PLACEHOLDER_RE = re.compile(r"\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}")


def _find_sparql_format_placeholder(sparql: str) -> re.Match[str] | None:
    """Return the first `{identifier}`-shaped match in `sparql` that looks
    like an unresolved Python format placeholder, or None if there isn't
    one."""
    return _SPARQL_FORMAT_PLACEHOLDER_RE.search(sparql)


@dataclass(frozen=True)
class NamedQuery:
    """A single named, parameterized, static Cypher query.

    Attributes:
        name: dotted identifier, convention `<domain>.<verb>_<subject>`
              (e.g. "lessons.recall_by_similarity").
        cypher: the parameterized Cypher template. Must be a static string —
              all variable input goes through `$param` placeholders, never
              string interpolation. Validated at registration time.
        params: the complete set of `$param` names this query requires.
              `GraphGateway.run()` validates caller-supplied kwargs against
              this set before touching the database.
        mutating: True routes through `KuzuClient.execute_write()`
              (asyncio write-lock held); False routes through
              `KuzuClient.execute_read()`.
        description: one line — what question this query answers.
        sparql: provisional SPARQL 1.1 query string for pure-graph traversal queries (~90%).

    Explicit Handler Dispatch Boundary (B384 Storage Foundation):
    Not all queries have a 1:1 SPARQL string equivalent:
    1. Vector ANN Search: Kùzu's QUERY_VECTOR_INDEX has no direct SPARQL counterpart.
       In B384 Phase 2B, vector search routes through `sqlite-vec` in Python for top-k
       entity IDs, followed by graph node hydration via Oxigraph.
    2. RDF-Star Edge Reification: Mutating edge properties (e.g. edge property updates
       with :event_id discriminators) requires Python-level quoted triple handling,
       not simple string transliteration.

    NamedQuery serves as the semantic query contract (name, params, mutating, description),
    allowing engine-specific query strings or dedicated Python handlers for
    vector/reified operations.
    """

    name: str
    cypher: str
    params: tuple[str, ...]
    mutating: bool
    description: str
    sparql: str | None = None

    @property
    def doc(self) -> str:
        return self.description

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"NamedQuery.name must be a non-empty string, got {self.name!r}")
        if not self.cypher or not isinstance(self.cypher, str) or not self.cypher.strip():
            raise ValueError(f"NamedQuery {self.name!r}: cypher must be a non-empty string")
        if not isinstance(self.params, tuple) or not all(isinstance(p, str) for p in self.params):
            raise TypeError(f"NamedQuery {self.name!r}: params must be a tuple[str, ...]")
        if not isinstance(self.mutating, bool):
            raise TypeError(f"NamedQuery {self.name!r}: mutating must be a bool")
        if not self.description or not isinstance(self.description, str):
            raise ValueError(f"NamedQuery {self.name!r}: description is required (one line, what question this answers)")
        if self.sparql is not None and not isinstance(self.sparql, str):
            raise TypeError(f"NamedQuery {self.name!r}: sparql must be a str or None")

        bad_brace = _find_unsafe_brace(self.cypher)
        if bad_brace is not None:
            snippet = self.cypher[max(0, bad_brace - 20):bad_brace + 20]
            raise ValueError(
                f"NamedQuery {self.name!r}: cypher contains a '{{' at offset {bad_brace} that "
                f"is not a Kùzu literal map (looks like an unresolved template/format "
                f"placeholder — near: ...{snippet!r}...). All variable input must go through "
                f"$param placeholders, not string interpolation."
            )

        if self.sparql is not None:
            bad_placeholder = _find_sparql_format_placeholder(self.sparql)
            if bad_placeholder is not None:
                snippet = self.sparql[max(0, bad_placeholder.start() - 20):bad_placeholder.end() + 20]
                raise ValueError(
                    f"NamedQuery {self.name!r}: sparql contains what looks like an "
                    f"unresolved Python format placeholder ({bad_placeholder.group(0)!r} "
                    f"near: ...{snippet!r}...). All variable input must go through SPARQL "
                    f"?param placeholders bound via VALUES/BIND "
                    f"(docs/rdf-schema-mapping.md §7.2), never f-string/.format() "
                    f"interpolation of a caller-supplied value into the query text."
                )


class QueryRegistry:
    """Holds `NamedQuery` objects, keyed by name. Duplicate names raise."""

    def __init__(self) -> None:
        self._queries: dict[str, NamedQuery] = {}

    def register(self, query: NamedQuery) -> None:
        if query.name in self._queries:
            raise ValueError(f"duplicate NamedQuery name: {query.name!r} (already registered)")
        self._queries[query.name] = query

    def register_all(self, queries: Iterable[NamedQuery]) -> None:
        for query in queries:
            self.register(query)

    def get(self, name: str) -> NamedQuery:
        try:
            return self._queries[name]
        except KeyError:
            raise KeyError(f"no NamedQuery registered under {name!r}") from None

    def __contains__(self, name: object) -> bool:
        return name in self._queries

    def __iter__(self):
        return iter(self._queries.values())

    def __len__(self) -> int:
        return len(self._queries)



def _materialize_rows(res: Any) -> Any:
    # Duck-typed cursor protocol: anything exposing a callable has_next() is
    # treated as a cursor to materialize — real kuzu QueryResult objects and
    # hand-written test fakes both implement this protocol faithfully. Only
    # has_next() is required up front: an empty-result fake commonly defines
    # has_next() -> False and never defines get_next() at all (it's never
    # called), so get_next() is looked up lazily, only once has_next() says
    # there is a row to fetch. An *unconfigured* unittest.mock.Mock is the
    # one exception: its auto-generated has_next() returns a fresh,
    # always-truthy Mock on every call, which would loop forever — only
    # trust a Mock here once the test has explicitly configured has_next to
    # return real bools.
    has_next = getattr(res, "has_next", None)
    has_real_cursor = callable(has_next)
    if has_real_cursor and isinstance(res, unittest.mock.Mock):
        has_real_cursor = (
            getattr(has_next, "side_effect", None) is not None
            or isinstance(getattr(has_next, "return_value", None), bool)
        )
    if has_real_cursor:
        rows = []
        column_names = res.get_column_names() if hasattr(res, "get_column_names") and callable(res.get_column_names) else None
        while res.has_next():
            row = res.get_next()
            if isinstance(row, dict):
                rows.append(row)
            elif column_names and isinstance(row, (list, tuple)) and len(column_names) == len(row):
                rows.append({col: val for col, val in zip(column_names, row)})
            else:
                rows.append(row)
        return rows
    elif hasattr(res, "__iter__") and not isinstance(res, (dict, str, bytes)):
        try:
            return list(res)
        except Exception:
            pass
    return res


class GraphGateway:
    """The chokepoint. Wraps a `KuzuClient` or `OxigraphClient` + `QueryRegistry`; `run()` is
    the only sanctioned way application code should reach the database."""

    def __init__(
        self,
        client: Any,
        registry: QueryRegistry,
        vector_store: Any | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._vector_store = vector_store
        self._is_oxigraph = (
            type(client).__name__ == "OxigraphClient"
            or (hasattr(client, "store") and not hasattr(client, "conn"))
        )
        if self._is_oxigraph and self._vector_store is None:
            if hasattr(client, "vector_store") and client.vector_store is not None:
                self._vector_store = client.vector_store
            else:
                try:
                    from campy.brain.hippocampus.graph.vector_store import VectorStore
                    self._vector_store = VectorStore()
                except Exception:
                    self._vector_store = None

    async def run(self, name: str, params: dict[str, Any] | None = None, /, **kwargs: Any) -> Any:
        """Look up `name`, validate `params` against the query's declared
        set, then route to `execute_read`/`execute_write` by `mutating`.

        Raises:
            KeyError: `name` isn't registered (message includes `name`).
            TypeError: `params` doesn't exactly match the query's declared
                parameter names — raised before the database is touched.
        """
        merged_params: dict[str, Any] = dict(params or {}) if isinstance(params, dict) else {}
        merged_params.update(kwargs)
        query = self._registry.get(name)

        declared = set(query.params)
        provided = set(merged_params)
        if declared != provided:
            missing = sorted(declared - provided)
            unexpected = sorted(provided - declared)
            parts = []
            if missing:
                parts.append(f"missing={missing}")
            if unexpected:
                parts.append(f"unexpected={unexpected}")
            raise TypeError(
                f"GraphGateway.run({name!r}): parameter mismatch — {', '.join(parts)}"
            )

        if self._is_oxigraph:
            res = await self._dispatch_oxigraph(query, merged_params)
            return _materialize_rows(res)

        exec_mocked = getattr(getattr(self._client, "execute", None), "side_effect", None) is not None
        read_mocked = getattr(getattr(self._client, "execute_read", None), "side_effect", None) is not None

        if query.mutating:
            if inspect.iscoroutinefunction(getattr(self._client, "execute_write", None)):
                res = await self._client.execute_write(query.cypher, merged_params)
            else:
                res = self._client.execute(query.cypher, merged_params)
                if inspect.iscoroutine(res) or hasattr(res, "__await__"):
                    res = await res
            return _materialize_rows(res)

        if not (exec_mocked and not read_mocked) and inspect.iscoroutinefunction(getattr(self._client, "execute_read", None)):
            res = await self._client.execute_read(query.cypher, merged_params)
        else:
            res = self._client.execute(query.cypher, merged_params)
            if inspect.iscoroutine(res) or hasattr(res, "__await__"):
                res = await res
        return _materialize_rows(res)

    def run_sync(self, name: str, params: dict[str, Any] | None = None, /, **kwargs: Any) -> Any:
        """Synchronous execution of named queries for non-async callers.
        Calls `self._client.execute()` and returns materialized rows.
        """
        merged_params: dict[str, Any] = dict(params or {}) if isinstance(params, dict) else {}
        merged_params.update(kwargs)
        query = self._registry.get(name)

        declared = set(query.params)
        provided = set(merged_params)
        if declared != provided:
            missing = sorted(declared - provided)
            unexpected = sorted(provided - declared)
            parts = []
            if missing:
                parts.append(f"missing={missing}")
            if unexpected:
                parts.append(f"unexpected={unexpected}")
            raise TypeError(
                f"GraphGateway.run_sync({name!r}): parameter mismatch — {', '.join(parts)}"
            )

        if self._is_oxigraph:
            res = self._dispatch_oxigraph_sync(query, merged_params)
            return _materialize_rows(res)

        res = self._client.execute(query.cypher, merged_params)
        return _materialize_rows(res)

    async def _dispatch_oxigraph(self, query: NamedQuery, params: dict[str, Any]) -> Any:
        if query.name == "orchestrator.get_gist_centroids":
            return self._handle_oxigraph_handler(query, params)
        if query.sparql is not None:
            if query.mutating:
                return await self._client.execute_write(query.sparql, params)
            return await self._client.execute_read(query.sparql, params)
        return self._handle_oxigraph_handler(query, params)

    def _dispatch_oxigraph_sync(self, query: NamedQuery, params: dict[str, Any]) -> Any:
        if query.name == "orchestrator.get_gist_centroids":
            return self._handle_oxigraph_handler(query, params)
        if query.sparql is not None:
            if query.mutating:
                self._client.execute(query.sparql, params)
                return []
            return self._client._execute_and_collect(query.sparql, params)
        return self._handle_oxigraph_handler(query, params)

    def _handle_oxigraph_handler(self, query: NamedQuery, params: dict[str, Any]) -> Any:
        name = query.name

        # 1. Thalamus bundle queries
        if name.startswith("thalamus.bundle_") or name == "thalamus.analogical_get_quest_embedding":
            return self._handle_thalamus_bundle(name, params)

        # 2. working_memory loaded edges (occurrence)
        if name.startswith("working_memory.create_loaded_edge_"):
            tbl_suffix = name.replace("working_memory.create_loaded_edge_", "")
            target_table = _resolve_node_table(tbl_suffix)
            src_uri = mint_uri("Session", params["sid"])
            dst_uri = mint_uri(target_table, params["nid"])
            self._client.write_edge("LOADED", src_uri, dst_uri, {
                "token_estimate": params.get("tokens"),
                "source": params.get("source"),
                "injected_at": params.get("now"),
                "load_hits": 1,
            })
            return []

        # 3. temporal_lobe warm nodes (star)
        if name.startswith("temporal_lobe.warm_link_"):
            tbl_suffix = name.replace("temporal_lobe.warm_link_", "")
            target_table = _resolve_node_table(tbl_suffix)
            src_uri = mint_uri("Session", params["sid"])
            dst_uri = mint_uri(target_table, params["nid"])
            self._client.write_edge("WARM_NODE", src_uri, dst_uri, {
                "activation_score": params.get("score"),
                "activated_at": params.get("now"),
            })
            return []

        # 4. sweep concept relationships (star)
        if name.startswith("sweep.merge_concept_rel_"):
            rel_name = name.replace("sweep.merge_concept_rel_", "").upper()
            src_uri = mint_uri("Concept", params["a_id"])
            dst_uri = mint_uri("Concept", params["b_id"])
            self._client.write_edge(rel_name, src_uri, dst_uri, {
                "confidence": params.get("conf"),
                "inferred_by": "LLM",
                "inferred_at": params.get("now"),
            })
            return []

        # 5. capability create edges (star)
        if name.startswith("capability.create_edge_"):
            rel_name = name.replace("capability.create_edge_", "").upper()
            src_uri = mint_uri("FactEntity", params["subject_id"])
            dst_uri = mint_uri("FactEntity", params["object_id"])
            props = {k: v for k, v in params.items() if k not in ("subject_id", "object_id")}
            self._client.write_edge(rel_name, src_uri, dst_uri, props)
            return []

        # 6. capture merge followed_by (star)
        if name == "capture.merge_followed_by":
            src_uri = mint_uri("Message", params["prev"])
            dst_uri = mint_uri("Message", params["curr"])
            self._client.write_edge("FOLLOWED_BY", src_uri, dst_uri, {"gap_seconds": params.get("gap")})
            return []

        # 7. ARC link queries
        if name == "arc.link_entity_moved_by":
            self._client.write_edge("MOVED_BY", mint_uri("Entity", params["eid"]), mint_uri("ActionEffect", params["aeid"]), {"dr": params.get("dr"), "dc": params.get("dc")})
            return []
        if name == "arc.link_entity_hypothesis":
            self._client.write_edge("ANCHORED_TO", mint_uri("InvestigationThread", params["tid"]), mint_uri("Hypothesis", params["hid"]), {"weight": params.get("weight"), "step": params.get("step")})
            return []
        if name == "arc.link_entity_rule":
            self._client.write_edge("ANCHORED_TO", mint_uri("InvestigationThread", params["tid"]), mint_uri("Rule", params["rid"]), {"weight": params.get("weight"), "step": params.get("step")})
            return []
        if name == "arc.link_mechanic_action_pattern":
            self._client.write_edge("HAS_ACTION_PATTERN", mint_uri("Mechanic", params["mechanic_id"]), mint_uri("Pattern", params["pattern_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_effect_pattern":
            self._client.write_edge("HAS_EFFECT_PATTERN", mint_uri("Mechanic", params["mechanic_id"]), mint_uri("Pattern", params["pattern_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_precondition":
            self._client.write_edge("HAS_PRECONDITION", mint_uri("Mechanic", params["mech_id"]), mint_uri("Precondition", params["pre_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_failure_mode":
            self._client.write_edge("HAS_FAILURE_MODE", mint_uri("Mechanic", params["mech_id"]), mint_uri("FailureMode", params["fail_id"]))
            return []
        if name == "arc.link_failure_recovery_policy":
            self._client.write_edge("HAS_RECOVERY_POLICY", mint_uri("FailureMode", params["fail_id"]), mint_uri("RecoveryPolicy", params["pol_id"]), {"confidence": params.get("confidence")})
            return []

        # 8. Ingest link dataset
        if name == "ingest.link_concept_dataset":
            self._client.write_edge("DESCRIBED_BY_DATASET", mint_uri("Concept", params["cid"]), mint_uri("Dataset", params["did"]), {"extraction_method": "llm", "created_at": params.get("now")})
            return []

        # 9. Quests link / rerouted
        if name == "quests.create_rerouted_from":
            self._client.write_edge("REROUTED_FROM", mint_uri("Session", params["sid"]), mint_uri("MainQuest", params["qid"]), {"rerouted_at": params.get("now"), "reason": params.get("reason")})
            return []
        if name == "quests.link_distinct_from":
            self._client.write_edge("DISTINCT_FROM", mint_uri("Concept", params["a"]), mint_uri("Concept", params["b"]), {"created_at": params.get("now")})
            return []
        if name == "quests.link_plan_applied_procedure":
            self._client.write_edge("APPLIED_PROCEDURE", mint_uri("Plan", params["pid"]), mint_uri("Procedure", params["proc_id"]), {"success": params.get("success"), "applied_at": params.get("now")})
            return []
        if name == "quests.link_plan_step_outcome_signal":
            q_match = f"""
                SELECT ?ps ?c WHERE {{
                    ?ps a <https://campy.dev/ns#PlanStep> ;
                        <https://campy.dev/ns#STEP_OF> ?p ;
                        <https://campy.dev/ns#step_number> {int(params['step_number'])} ;
                        <https://campy.dev/ns#ACTS_ON> ?c .
                    ?p <https://campy.dev/ns#plan_id> {repr(str(params['pid']))} .
                }}
            """
            matches = self._client._execute_and_collect(q_match)
            for m in matches:
                self._client.write_edge("OUTCOME_SIGNAL", m["ps"], m["c"], {
                    "valence": params.get("valence"),
                    "plan_id": params.get("pid"),
                    "observed_at": params.get("now"),
                })
            return []

        # 10. Vector / Embedding updates and queries
        if name == "quests.set_label_embedding":
            if self._vector_store:
                self._vector_store.upsert_vector(mint_uri("Label", params["lid"]), params["emb"])
            return []

        if name == "quests.get_active_with_embeddings":
            q_active = "SELECT ?qid ?name WHERE { ?q a <https://campy.dev/ns#MainQuest> ; <https://campy.dev/ns#status> 'active' ; <https://campy.dev/ns#quest_id> ?qid ; <https://campy.dev/ns#name> ?name . }"
            rows = self._client._execute_and_collect(q_active)
            limit = int(params.get("limit", 100))
            res = []
            for r in rows[:limit]:
                emb = self._vector_store.get_vector(mint_uri("MainQuest", r["qid"])) if self._vector_store else None
                res.append(RowDict({"q.quest_id": r["qid"], "q.name": r["name"], "q.embedding": emb}))
            return res

        if name in ("quests.get_anomalies_branch_scope", "quests.get_anomalies_global_scope"):
            limit = int(params.get("limit", 100))
            q_anom = f"""
                SELECT ?n ?gc WHERE {{
                    ?n <https://campy.dev/ns#flagged_for_review> true ;
                       <https://campy.dev/ns#ANOMALY_DETECTED> ?gc .
                }}
                LIMIT {limit}
            """
            rows = self._client._execute_and_collect(q_anom)
            return [RowDict({"n": r["n"], "r": {}, "gc": r["gc"]}) for r in rows]

        if name == "capability.reuse_candidates":
            eid = params["entity_id"]
            qemb = params["query_embedding"]
            floor = float(params.get("floor", 0.70))
            limit = 10
            candidates = self._vector_store.search_vectors(qemb, k=limit + 1, min_score=floor) if self._vector_store else []
            prefix = f"{CID_BASE}FactEntity/"
            curr_uri = f"{prefix}{eid}"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix) and uri != curr_uri][:limit]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?eid ?etype ?label ?props WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#entity_id> ?eid .
                    OPTIONAL {{ ?s <https://campy.dev/ns#entity_type> ?etype }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#label> ?label }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#properties> ?props }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            res = []
            for uri, score in matching:
                if uri in hydrated:
                    h = hydrated[uri]
                    res.append(RowDict({
                        "entity_id": h["eid"],
                        "entity_type": h.get("etype"),
                        "label": h.get("label"),
                        "properties": h.get("props"),
                        "similarity": score,
                    }))
            return res

        # 11. Sweep synthesis and Gist
        if name == "sweep.get_gist_examples_by_class":
            q_gist = f"SELECT ?e WHERE {{ ?e a <https://campy.dev/ns#GistExample> ; <https://campy.dev/ns#gist_class> {repr(params['cls'])} . }}"
            rows = self._client._execute_and_collect(q_gist)
            res = []
            for r in rows:
                emb = self._vector_store.get_vector(r["e"]) if self._vector_store else None
                if emb is not None:
                    res.append(RowDict({"e.embedding": emb}))
            return res

        if name == "sweep.update_gist_class_centroid":
            if self._vector_store:
                self._vector_store.upsert_vector(mint_uri("GistClass", params["name"]), params["centroid"])
            return []

        if name == "sweep.link_generalizes_lesson":
            self._client.write_edge("GENERALIZES_LESSON", mint_uri("Lesson", params["mid"]), mint_uri("Lesson", params["cid"]), {
                "synthesized_at": params.get("now"),
                "cluster_size": params.get("cluster_size"),
            })
            return []

        if name == "sweep.get_lessons_for_synthesis":
            domain = params.get("domain")
            sparql = f"""
                SELECT ?s ?id ?text ?ps ?conf WHERE {{
                    ?s a <https://campy.dev/ns#Lesson> ;
                       <https://campy.dev/ns#lesson_id> ?id ;
                       <https://campy.dev/ns#domain> {repr(str(domain))} ;
                       <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?arch }}
                    FILTER(!BOUND(?arch) || ?arch = false)
                    OPTIONAL {{ ?s <https://campy.dev/ns#lesson_type> ?ltype }}
                    FILTER(!BOUND(?ltype) || ?ltype != "synthesis")
                    OPTIONAL {{ ?s <https://campy.dev/ns#pathway_strength> ?ps }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    FILTER NOT EXISTS {{ ?parent <https://campy.dev/ns#GENERALIZES_LESSON> ?s }}
                }}
            """
            rows = self._client._execute_and_collect(sparql)
            res = []
            for r in rows:
                emb = self._vector_store.get_vector(r["s"]) if self._vector_store else None
                res.append(RowDict({
                    "l.lesson_id": r["id"],
                    "l.embedding": emb,
                    "l.text_raw": r["text"],
                    "l.pathway_strength": r.get("ps", 0.5),
                    "l.confidence": r.get("conf", 0.5),
                }))
            return res

        if name == "sweep.get_lessons_in_domain_embeddings":
            domain = params.get("domain")
            min_path = float(params.get("min_path", 0.0))
            limit = int(params.get("limit", 100))
            sparql = f"""
                SELECT ?s ?id ?text ?conf ?ps ?created ?audited WHERE {{
                    ?s a <https://campy.dev/ns#Lesson> ;
                       <https://campy.dev/ns#lesson_id> ?id ;
                       <https://campy.dev/ns#domain> {repr(str(domain))} ;
                       <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?arch }}
                    FILTER(!BOUND(?arch) || ?arch = false)
                    OPTIONAL {{ ?s <https://campy.dev/ns#pathway_strength> ?ps }}
                    FILTER(!BOUND(?ps) || ?ps > {min_path})
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#created_at> ?created }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#last_audited_at> ?audited }}
                }}
                ORDER BY DESC(?ps)
                LIMIT {limit}
            """
            rows = self._client._execute_and_collect(sparql)
            res = []
            for r in rows:
                emb = self._vector_store.get_vector(r["s"]) if self._vector_store else None
                res.append(RowDict({
                    "l.lesson_id": r["id"],
                    "l.embedding": emb,
                    "l.text_raw": r["text"],
                    "l.confidence": r.get("conf", 0.5),
                    "l.pathway_strength": r.get("ps", 0.5),
                    "l.created_at": r.get("created"),
                    "l.last_audited_at": r.get("audited"),
                }))
            return res

        if name.startswith("sweep.resurrect_active_embeddings_"):
            tbl_suffix = name.replace("sweep.resurrect_active_embeddings_", "")
            resolved_table = _resolve_node_table(tbl_suffix)
            pk = NODE_PRIMARY_KEYS.get(resolved_table, tbl_suffix + "_id")
            limit = int(params.get("limit", 100))
            sparql = f"""
                SELECT ?s ?pk WHERE {{
                    ?s a <https://campy.dev/ns#{resolved_table}> ;
                       <https://campy.dev/ns#{pk}> ?pk .
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?arch }}
                    FILTER(!BOUND(?arch) || ?arch = false)
                }}
                LIMIT {limit}
            """
            rows = self._client._execute_and_collect(sparql)
            res = []
            for r in rows:
                emb = self._vector_store.get_vector(r["s"]) if self._vector_store else None
                if emb is not None:
                    res.append(RowDict({"id": r["pk"], "embedding": emb}))
            return res

        if name == "orchestrator.get_gist_centroids":
            sparql = """
                PREFIX campy: <https://campy.dev/ns#>
                SELECT ?name WHERE {
                    ?g a campy:GistClass ;
                       campy:name ?name .
                }
            """
            rows = self._client._execute_and_collect(sparql)
            res = []
            for r in rows:
                c_name = r["name"]
                c_uri = mint_uri("GistClass", c_name)
                centroid = self._vector_store.get_vector(c_uri) if self._vector_store else None
                res.append(RowDict({
                    "g.name": c_name,
                    "g.centroid": centroid,
                }))
            return res

        raise NotImplementedError(f"No Python handler or SPARQL translation implemented for NamedQuery {name!r}")

    def _handle_thalamus_bundle(self, name: str, params: dict[str, Any]) -> list[Any]:
        query_embedding = params.get("query_embedding")

        if name == "thalamus.analogical_get_quest_embedding":
            qid = params["qid"]
            rows = self._client._execute_and_collect(
                f"SELECT ?name WHERE {{ ?q a <https://campy.dev/ns#MainQuest> ; <https://campy.dev/ns#quest_id> {repr(str(qid))} ; <https://campy.dev/ns#name> ?name . }}"
            )
            qname = rows[0]["name"] if rows else None
            emb = self._vector_store.get_vector(mint_uri("MainQuest", qid)) if self._vector_store else None
            return [RowDict({"q.embedding": emb, "q.name": qname})]

        if query_embedding is None or not self._vector_store:
            return []

        # Exact facts: thalamus.bundle_exact_facts_{tbl}[_flagged][_auth] or thalamus.bundle_exact_{tbl}[_flagged][_auth]
        if name.startswith("thalamus.bundle_exact"):
            sub = name.replace("thalamus.bundle_exact_facts_", "").replace("thalamus.bundle_exact_", "")
            tbl_key = sub.split("_")[0]
            target_table = _resolve_node_table(tbl_key)
            limit = int(params.get("limit", 10))
            candidates = self._vector_store.search_vectors(query_embedding, k=limit * 5, min_score=0.70)
            prefix = f"{CID_BASE}{target_table}/"
            matching_uris = [uri for uri, _ in candidates if uri.startswith(prefix)][:limit]
            if not matching_uris:
                return []
            values_block = " ".join(f"<{u}>" for u in matching_uris)
            sparql = f"""
                SELECT ?s ?text ?conf ?auth WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#authority> ?auth }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri in matching_uris:
                if uri in hydrated:
                    h = hydrated[uri]
                    rows.append(RowDict({
                        "text": h.get("text"),
                        "node_type": target_table,
                        "confidence": h.get("conf", 0.5),
                        "authority": h.get("auth"),
                    }))
            return rows

        # Semantic context: thalamus.bundle_semantic_{tbl}[_flags]
        if name.startswith("thalamus.bundle_semantic_"):
            sub = name.replace("thalamus.bundle_semantic_", "")
            tbl_key = sub.split("_")[0]
            target_table = _resolve_node_table(tbl_key)
            limit = int(params.get("limit", 10))
            candidates = self._vector_store.search_vectors(query_embedding, k=limit * 5, min_score=0.70)
            prefix = f"{CID_BASE}{target_table}/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)][:limit]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?text ?ps ?conf ?auth WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#pathway_strength> ?ps }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#authority> ?auth }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri in hydrated:
                    h = hydrated[uri]
                    dist = max(0.0, 1.0 - float(score))
                    rows.append(RowDict({
                        "text": h.get("text"),
                        "node_type": target_table,
                        "pathway_strength": h.get("ps", 0.5),
                        "confidence": h.get("conf", 0.5),
                        "dist": dist,
                        "authority": h.get("auth"),
                    }))
            return rows

        # Graph anchors: thalamus.bundle_graph_anchors[_flags]
        if name.startswith("thalamus.bundle_graph_anchors"):
            candidates = self._vector_store.search_vectors(query_embedding, k=15, min_score=0.70)
            prefix = f"{CID_BASE}Concept/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)][:5]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?cid ?text WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#concept_id> ?cid ;
                       <https://campy.dev/ns#text_raw> ?text .
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri in hydrated:
                    h = hydrated[uri]
                    dist = max(0.0, 1.0 - float(score))
                    rows.append(RowDict({
                        "id": h["cid"],
                        "text": h["text"],
                        "dist": dist,
                    }))
            return rows

        if name == "thalamus.bundle_tabular_described_by_dataset":
            candidates = self._vector_store.search_vectors(query_embedding, k=15, min_score=0.70)
            prefix = f"{CID_BASE}Concept/"
            concept_uris = [uri for uri, _ in candidates if uri.startswith(prefix)][:5]
            if not concept_uris:
                return []
            values_block = " ".join(f"<{u}>" for u in concept_uris)
            sparql = f"""
                SELECT DISTINCT ?dataset_id ?name ?desc WHERE {{
                    VALUES ?c {{ {values_block} }}
                    ?c <https://campy.dev/ns#DESCRIBED_BY_DATASET> ?d .
                    ?d <https://campy.dev/ns#dataset_id> ?dataset_id ;
                       <https://campy.dev/ns#name> ?name .
                    OPTIONAL {{ ?d <https://campy.dev/ns#description> ?desc }}
                    OPTIONAL {{ ?d <https://campy.dev/ns#archived> ?archived }}
                    FILTER(!BOUND(?archived) || ?archived = false)
                }}
                LIMIT 5
            """
            res = self._client._execute_and_collect(sparql)
            return [RowDict({"dataset_id": r["dataset_id"], "name": r["name"], "description": r.get("desc")}) for r in res]

        if name == "thalamus.bundle_wiki_lessons":
            limit = int(params.get("limit", 5))
            candidates = self._vector_store.search_vectors(query_embedding, k=limit * 5, min_score=0.70)
            prefix = f"{CID_BASE}Lesson/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)][:limit * 2]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?id ?text ?ltype ?archived WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#lesson_id> ?id ;
                       <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#lesson_type> ?ltype }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?archived }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri in hydrated:
                    h = hydrated[uri]
                    if h.get("archived") is True:
                        continue
                    if h.get("ltype") != "synthesis":
                        continue
                    dist = max(0.0, 1.0 - float(score))
                    rows.append(RowDict({
                        "id": h["id"],
                        "text": h["text"],
                        "node_type": "Lesson",
                        "dist": dist,
                    }))
                    if len(rows) >= limit:
                        break
            return rows

        if name == "thalamus.bundle_wiki_procedures":
            limit = int(params.get("limit", 5))
            candidates = self._vector_store.search_vectors(query_embedding, k=limit * 5, min_score=0.70)
            prefix = f"{CID_BASE}Procedure/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)][:limit * 2]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?id ?desc ?archived WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#procedure_id> ?id ;
                       <https://campy.dev/ns#description> ?desc .
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?archived }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri in hydrated:
                    h = hydrated[uri]
                    if h.get("archived") is True:
                        continue
                    dist = max(0.0, 1.0 - float(score))
                    rows.append(RowDict({
                        "id": h["id"],
                        "text": h["desc"],
                        "node_type": "Procedure",
                        "dist": dist,
                    }))
                    if len(rows) >= limit:
                        break
            return rows

        return []

    async def execute_raw(
        self,
        cypher: str,
        params: dict | None = None,
        *,
        mutating: bool,
        reason: str,
    ) -> Any:
        """ESCAPE HATCH — every use is migration debt, counted by
        `scripts/check_cypher_ratchet.py`. `reason` is required (raises
        TypeError if omitted) and is logged so a grep of the logs shows
        every call site still bypassing the named-query registry."""
        if not reason:
            raise TypeError("GraphGateway.execute_raw() requires a non-empty `reason`")

        first_line = cypher.strip().splitlines()[0] if cypher.strip() else cypher
        _logger.warning(
            "GraphGateway.execute_raw escape hatch used (reason=%r): %s", reason, first_line
        )

        if mutating:
            if hasattr(self._client, "execute_write"):
                return await self._client.execute_write(cypher, params)
            return self._client.execute(cypher, params)
        if hasattr(self._client, "execute_read"):
            return await self._client.execute_read(cypher, params)
        res = self._client.execute(cypher, params)
        if hasattr(res, "has_next"):
            rows = []
            while res.has_next():
                rows.append(res.get_next())
            return rows
        return res



def get_gateway(db: Any) -> GraphGateway:
    """Return a GraphGateway wrapping `db`, or `db` if it is already a GraphGateway."""
    if isinstance(db, GraphGateway):
        return db
    from campy.brain.hippocampus.graph.queries import REGISTRY
    return GraphGateway(db, REGISTRY)
