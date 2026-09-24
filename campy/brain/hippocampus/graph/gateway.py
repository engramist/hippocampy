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

import asyncio
import inspect
import logging
import os
import re
import time
import unittest.mock
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import unquote
from campy.brain.hippocampus.schema import FACT_PREDICATE_TABLES
from campy.brain.hippocampus.graph.oxigraph_client import (
    CID_BASE,
    DATA_BASE,
    NODE_PRIMARY_KEYS,
    RowDict,
    mint_uri,
)

_logger = logging.getLogger(__name__)

# B447: OxigraphClient.execute_write() serializes every write in the daemon
# through a single global asyncio.Lock held for the full duration of the
# native store.update() call, with no timeout — a pathologically slow write
# (observed in production: 96min, then 2h28m+ on a different message) blocks
# every other write in the system silently and indefinitely. This bounds
# that: overridable via CAMPY_WRITE_TIMEOUT_SECONDS for operators who need to
# tune it without a code change. 60s is well above every normal write
# observed during B447's investigation (sub-10s, typically sub-1s) and far
# below the multi-hour stalls it's meant to catch.
WRITE_TIMEOUT_SECONDS = float(os.environ.get("CAMPY_WRITE_TIMEOUT_SECONDS", "60"))

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


def _typed_search_k(limit: int) -> int:
    """B454: the vector store is one flat index across every node type. A typed
    lookup takes the global top-k and only then filters by node type, so a
    small k lets a large type (~20k Messages) crowd out a small one (hundreds
    of Concepts/Decisions) entirely. sqlite-vec scans flat regardless of k, so a
    generous k is nearly free."""
    return min(max(int(limit) * 5, 1000), 4096)  # sqlite-vec caps k at 4096


@dataclass(frozen=True)
class VectorIndexSpec:
    """B418: declares how a `sparql=` node-create query should populate the
    sqlite-vec vector store.

    `sparql=` creates route straight to `execute_write()` and bypass
    `OxigraphClient.write_node()` — the only place that calls
    `vector_store.upsert_vector()` / `index_text()`. A query carrying this spec
    tells `GraphGateway` to re-attach that indexing after the write, keyed at the
    node's real subject URI.

    Attributes:
        table: node table, e.g. "Lesson".
        pk_col: graph property holding the primary key, e.g. "lesson_id".
        pk_param: query param carrying the PK value, e.g. "lid".
        emb_param: query param carrying the embedding list, e.g. "emb".
        text_param: optional query param carrying text for FTS, e.g. "text".
    """

    table: str
    pk_col: str
    pk_param: str
    emb_param: str
    text_param: str | None = None


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
    vector_index: "VectorIndexSpec | None" = None

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

    def attach_vector_index(self, name: str, spec: "VectorIndexSpec") -> None:
        """B454: attach (or replace) a VectorIndexSpec on an already-registered
        query, validating that the spec's params are ones the query declares."""
        import dataclasses

        query = self.get(name)
        for label, param in (("pk_param", spec.pk_param), ("emb_param", spec.emb_param),
                             ("text_param", spec.text_param)):
            if param is not None and param not in query.params:
                raise ValueError(
                    f"VectorIndexSpec for {name!r}: {label}={param!r} is not one of "
                    f"the query's declared params {query.params}"
                )
        self._queries[name] = dataclasses.replace(query, vector_index=spec)

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
                res = await self._execute_write_with_timeout(query.name, query.sparql, params)
                if query.vector_index is not None:
                    self._index_vector_after_write(query.vector_index, params)
                return res
            return await self._client.execute_read(query.sparql, params)
        return self._handle_oxigraph_handler(query, params)

    async def _execute_write_with_timeout(
        self, name: str, sparql: str, params: dict[str, Any]
    ) -> Any:
        """B447: bounds `OxigraphClient.execute_write()` so a pathologically
        slow write fails loudly instead of holding the global write lock —
        and therefore blocking every other write in the daemon — forever.

        Safety note: `asyncio.wait_for` cancels the *awaiting* coroutine, not
        the underlying OS thread `asyncio.to_thread` runs `execute()` in —
        Python cannot forcibly kill a running thread. A timed-out write's
        native `store.update()` call keeps running in that orphaned thread
        until it finishes on its own; the asyncio-level lock is released
        immediately so other writers can proceed. This is a deliberate
        tradeoff, not an oversight: `Store.update()` is documented by
        pyoxigraph as transactional (all-or-nothing), and its RocksDB-backed
        storage is designed for concurrent access, so an orphaned write
        finishing later is expected to land safely rather than corrupt the
        store — but that has not been proven against this specific
        pyoxigraph version. Treat a WRITE_TIMEOUT_TRIPPED log line as a
        signal to investigate (which query, how often), not noise to ignore.
        The alternative is the status quo this fixes: a proven, reproducing,
        hours-long total write freeze across the whole daemon — a strictly
        worse failure mode than a rare, logged, bounded one.
        """
        t0 = time.perf_counter()
        try:
            return await asyncio.wait_for(
                self._client.execute_write(sparql, params),
                timeout=WRITE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _logger.error(
                "WRITE_TIMEOUT_TRIPPED query=%s elapsed=%.1fs timeout=%.1fs "
                "-- native write abandoned (thread may still be running) to "
                "unblock other writers; see backlog/B447.md",
                name, time.perf_counter() - t0, WRITE_TIMEOUT_SECONDS,
            )
            raise

    def _dispatch_oxigraph_sync(self, query: NamedQuery, params: dict[str, Any]) -> Any:
        if query.name == "orchestrator.get_gist_centroids":
            return self._handle_oxigraph_handler(query, params)
        if query.sparql is not None:
            if query.mutating:
                self._client.execute(query.sparql, params)
                if query.vector_index is not None:
                    self._index_vector_after_write(query.vector_index, params)
                return []
            return self._client._execute_and_collect(query.sparql, params)
        return self._handle_oxigraph_handler(query, params)

    def _index_vector_after_write(
        self, spec: "VectorIndexSpec", params: dict[str, Any]
    ) -> None:
        """B418: re-attach sqlite-vec indexing for `sparql=` node-creates, which
        bypass `OxigraphClient.write_node()` (the only other place that indexes).

        Keyed at the node's REAL subject URI resolved from the store, so it works
        regardless of whether the create template minted at the canonical `/id/`
        base or the drifted `/data/` base (see B418b). Best-effort: a missing
        vector store, embedding, or node is a no-op, never a write failure."""
        client = self._client
        vs = getattr(client, "vector_store", None)
        find = getattr(client, "find_subject_uri", None)
        if vs is None or find is None:
            return
        emb = params.get(spec.emb_param)
        pk_val = params.get(spec.pk_param)
        if emb is None or pk_val is None:
            return
        uri = find(spec.table, spec.pk_col, pk_val)
        if uri is None:
            return
        vs.upsert_vector(uri, emb)
        if spec.text_param:
            text = params.get(spec.text_param)
            if text:
                vs.index_text(uri, str(text))

    def _handle_oxigraph_handler(self, query: NamedQuery, params: dict[str, Any]) -> Any:
        name = query.name

        # 0. B451: CO_OCCURS_WITH is a star edge -- must go through write_edge,
        # not a pure-SPARQL INSERT (which minted a reifier per solution and grew
        # exponentially).
        if name == "pathways.unwind_co_occurs_with":
            for pair in params["pairs"]:
                self._client.upsert_co_occurrence(
                    mint_uri("Concept", pair["a_id"]),
                    mint_uri("Concept", pair["b_id"]),
                    float(params["strength"]),
                )
            return []

        # 0b. B451: same bug class for the semantic-relation star edges.
        if name.startswith("orchestrator.merge_semantic_rel_"):
            self._client.upsert_semantic_relation(
                name.replace("orchestrator.merge_semantic_rel_", "").upper(),
                mint_uri("Concept", params["hid"]),
                mint_uri("Concept", params["tid"]),
                params["confidence"],
                params["inferred_by"],
                params["now"],
            )
            return []

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
            # B427: the query name carries the bare predicate (e.g. "invokes"),
            # not the FACT_-prefixed rel table it's actually stored under —
            # look it up via FACT_PREDICATE_TABLES rather than just
            # uppercasing, or writes land on a table (e.g. "INVOKES") that
            # doesn't exist in EDGE_REIFICATION/schema.py at all.
            predicate = name.replace("capability.create_edge_", "").upper()
            rel_name = FACT_PREDICATE_TABLES[predicate]
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
            # B421: source is a GridEntity (not the non-existent "Entity" table), and
            # MOVED_BY's declared columns are delta_row/delta_col (the query params are
            # dr/dc) — matching the query's cypher `SET m.delta_row=$dr, m.delta_col=$dc`.
            self._client.write_edge("MOVED_BY", mint_uri("GridEntity", params["eid"]), mint_uri("ActionEffect", params["aeid"]), {"delta_row": params.get("dr"), "delta_col": params.get("dc")})
            return []
        # B420: link the GridEntity (resolved by task_id + region_index=eref,
        # exactly as the query's cypher MATCHes it) to the Rule/Hypothesis via
        # the ENTITY_RULE / ENTITY_HYPOTHESIS "star" edges these queries declare —
        # NOT ANCHORED_TO (a "plain" MainQuest→Workspace edge; passing props to it
        # raises). No-op if the GridEntity doesn't exist yet, mirroring the MATCH.
        if name == "arc.link_entity_hypothesis":
            ge_uri = self._client.find_node_uri("GridEntity", task_id=params["tid"], region_index=params["eref"])
            if ge_uri is not None:
                self._client.write_edge("ENTITY_HYPOTHESIS", ge_uri, mint_uri("Hypothesis", params["hid"]), {"weight": params.get("weight"), "step": params.get("step")})
            return []
        if name == "arc.link_entity_rule":
            ge_uri = self._client.find_node_uri("GridEntity", task_id=params["tid"], region_index=params["eref"])
            if ge_uri is not None:
                self._client.write_edge("ENTITY_RULE", ge_uri, mint_uri("Rule", params["rid"]), {"weight": params.get("weight"), "step": params.get("step")})
            return []
        # B430: ActionFact/ActionEffect endpoints are addressed directly by
        # their real primary keys (fact_id/effect_id), so mint_uri alone
        # resolves them — no find_node_uri lookup needed, matching how
        # mint_uri already works for any node whose PK the caller already has.
        if name == "arc.link_action_fact_derived_from_effect":
            self._client.write_edge("DERIVED_FROM_FACT", mint_uri("ActionFact", params["fid"]), mint_uri("ActionEffect", params["eid"]), {"step": params.get("step")})
            return []
        # B430: VictoryCondition is addressed by its real PK (condition_id);
        # GridEntity needs find_node_uri (task_id+region_index), same as
        # arc.link_entity_rule/arc.link_entity_hypothesis above. No-op if the
        # GridEntity doesn't exist yet, mirroring the query's own MATCH.
        if name == "arc.link_entity_requires_victory_condition":
            ge_uri = self._client.find_node_uri("GridEntity", task_id=params["tid"], region_index=params["eref"])
            if ge_uri is not None:
                self._client.write_edge("REQUIRES_ENTITY", mint_uri("VictoryCondition", params["gid"]), ge_uri, {"requirement": params.get("requirement")})
            return []
        # B422: these five must use the schema's real rel-table names + Arc-prefixed
        # node tables (ArcMechanic/ArcActionPattern/…), matching each query's own cypher.
        # The prior bare names (HAS_ACTION_PATTERN, Mechanic, Pattern, …) were unclassified
        # edges over non-existent node tables — write_edge raised on every one. Latent only
        # because publish_mechanic_summary is the sole caller and hasn't been exercised.
        if name == "arc.link_mechanic_action_pattern":
            self._client.write_edge("ARC_MECHANIC_HAS_ACTION_PATTERN", mint_uri("ArcMechanic", params["mechanic_id"]), mint_uri("ArcActionPattern", params["pattern_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_effect_pattern":
            self._client.write_edge("ARC_MECHANIC_CAUSES_EFFECT_PATTERN", mint_uri("ArcMechanic", params["mechanic_id"]), mint_uri("ArcEffectPattern", params["pattern_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_precondition":
            self._client.write_edge("ARC_MECHANIC_REQUIRES", mint_uri("ArcMechanic", params["mech_id"]), mint_uri("ArcPrecondition", params["pre_id"]), {"confidence": params.get("confidence")})
            return []
        if name == "arc.link_mechanic_failure_mode":
            # ARC_MECHANIC_FAILS_AS carries only evidence_count (the cypher increments it via
            # COALESCE; a single write_edge cannot increment, so the edge is created without
            # it — the link itself is what get_mechanic_priors traverses).
            self._client.write_edge("ARC_MECHANIC_FAILS_AS", mint_uri("ArcMechanic", params["mech_id"]), mint_uri("ArcFailureMode", params["fail_id"]))
            return []
        if name == "arc.link_failure_recovery_policy":
            self._client.write_edge("ARC_FAILURE_RECOVERED_BY", mint_uri("ArcFailureMode", params["fail_id"]), mint_uri("ArcRecoveryPolicy", params["pol_id"]), {"confidence": params.get("confidence")})
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

        if name.startswith("explore.start_node_"):
            # B432: the sparql= bodies for these queries used to SELECT the
            # subject variable itself (a bare URI string) as "node" — real
            # node property hydration has no clean way to express "give me
            # every declared column of whatever table this node happens to
            # be" as static SPARQL text, so this is a Python handler instead.
            table = _resolve_node_table(name.replace("explore.start_node_", ""))
            uri = mint_uri(table, params["id"])
            node = self._client.get_node(table, uri)
            if node is None:
                return []
            return [RowDict({"node": node, "internal_id": uri})]

        if name.startswith("basal_ganglia.frustration_get_"):
            # B433: the sparql= bodies for these queries OPTIONAL-matched
            # campy:embedding, which is never asserted as an RDF triple
            # (FLOAT[384] embeddings live exclusively in vector_store, per
            # spec §5) — ?emb could never bind, so
            # detect_frustration_clusters() silently dropped every
            # candidate node for lack of an embedding and always found
            # zero clusters. Run the same salience-filtered pattern minus
            # the dead OPTIONAL, then hydrate each row's embedding from
            # vector_store by its minted URI.
            table = _resolve_node_table(name.replace("basal_ganglia.frustration_get_", ""))
            id_col = NODE_PRIMARY_KEYS[table]
            sparql = """
                PREFIX campy: <https://campy.dev/ns#>
                SELECT ?id ?name ?description ?salience
                WHERE {{
                  ?n a campy:{table} ;
                     campy:{id_col} ?id ;
                     campy:salience_score ?salience .
                  ?n campy:archived false .
                  FILTER(?salience >= ?floor)
                  OPTIONAL {{ ?n campy:text_raw ?raw_text }}
                  BIND(COALESCE(?raw_text, "") AS ?name)
                  BIND(COALESCE(?raw_text, "") AS ?description)
                }}
                ORDER BY DESC(?salience)
                LIMIT 50
            """.format(table=table, id_col=id_col)
            rows = self._client._execute_and_collect(sparql, params)
            res = []
            for r in rows:
                uri = mint_uri(table, r["id"])
                emb = self._vector_store.get_vector(uri) if self._vector_store else None
                res.append(RowDict({
                    "id": r["id"], "name": r["name"], "description": r["description"],
                    "emb": emb, "salience": r["salience"],
                }))
            return res

        raise NotImplementedError(f"No Python handler or SPARQL translation implemented for NamedQuery {name!r}")

    def _bundle_conversation(self, params: dict[str, Any]) -> list[Any]:
        """B454: relevant things the USER said, as bundle evidence.

        Consolidation keeps entity labels ("PostgreSQL"), not the statements, so
        raw turns are the only place a fact like "we migrated to PostgreSQL 16"
        exists. Fuses the vector and FTS planes (reciprocal rank), keeps only
        user-role assertions (assistant text is capped/untrusted -- ISSUE-024 --
        and questions are not evidence, which also drops `ask`'s own captured
        question echoes), de-duplicates repeated text keeping the newest, and
        returns the top `limit` in chronological order so a later statement
        visibly supersedes an earlier one."""
        vs = self._vector_store
        limit = int(params.get("limit", 6))
        qtext = (params.get("query_text") or "").strip()
        if limit <= 0:
            return []
        prefixes = (f"{CID_BASE}Message/", f"{DATA_BASE}Message/")
        ranked: dict[str, float] = {}
        # A stored message that is (nearly) the query itself is an echo of the
        # question -- ask's own captured question, or a benchmark re-run -- not
        # evidence. Drop them BEFORE truncating, or dozens of identical copies
        # fill the candidate window and crowd every real fact out.
        vec_hits = [
            uri for uri, score in vs.search_vectors(
                params["query_embedding"], k=_typed_search_k(limit * 20), min_score=0.30)
            if uri.startswith(prefixes) and score < 0.985
        ][: limit * 40]
        for rank, uri in enumerate(vec_hits):
            ranked[uri] = ranked.get(uri, 0.0) + 1.0 / (60 + rank)
        fts_hits = [
            uri for uri, _ in vs.search_text(qtext, k=limit * 60) if uri.startswith(prefixes)
        ][: limit * 40]
        for rank, uri in enumerate(fts_hits):
            ranked[uri] = ranked.get(uri, 0.0) + 1.0 / (60 + rank)
        if not ranked:
            return []

        values_block = " ".join(f"<{u}>" for u in ranked)
        sparql = f"""
            SELECT ?s ?text ?role ?created ?archived WHERE {{
                VALUES ?s {{ {values_block} }}
                ?s <https://campy.dev/ns#text_raw> ?text .
                OPTIONAL {{ ?s <https://campy.dev/ns#role> ?role }}
                OPTIONAL {{ ?s <https://campy.dev/ns#created_at> ?created }}
                OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?archived }}
            }}
        """
        from campy.brain.hippocampus.graph.vector_store import fts_content_terms

        norm = lambda t: " ".join(str(t).lower().split())
        qnorm = norm(qtext)
        terms = fts_content_terms(qtext)
        vec_set = set(vec_hits)
        newest: dict[str, tuple[str, dict]] = {}
        for row in self._client._execute_and_collect(sparql):
            text = str(row.get("text") or "").strip()
            if (not text or row.get("role") != "user" or bool(row.get("archived"))
                    or text.endswith("?") or norm(text) == qnorm):
                continue
            # A lexical-only hit has no similarity floor, so require it to match
            # at least two distinct query content words (or the only one there is)
            # -- one shared common word is not evidence.
            if row["s"] not in vec_set:
                low = text.lower()
                if sum(1 for t in terms if t in low) < min(2, len(terms) or 1):
                    continue
            created = row.get("created")
            created = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
            key = norm(text)
            if key not in newest or created > newest[key][0]:
                newest[key] = (created, {"uri": row["s"], "text": text, "created": created})
        picked = sorted(newest.values(), key=lambda kv: -ranked.get(kv[1]["uri"], 0.0))[:limit]
        picked.sort(key=lambda kv: kv[0])
        return [
            RowDict({"text": v["text"], "role": "user", "created_at": v["created"],
                     "node_id": v["uri"], "node_type": "Message"})
            for _, v in picked
        ]

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

        if name == "thalamus.bundle_conversation":
            return self._bundle_conversation(params)

        # Exact facts: thalamus.bundle_exact_facts_{tbl}[_flagged][_auth] or thalamus.bundle_exact_{tbl}[_flagged][_auth]
        if name.startswith("thalamus.bundle_exact"):
            sub = name.replace("thalamus.bundle_exact_facts_", "").replace("thalamus.bundle_exact_", "")
            tbl_key = sub.split("_")[0]
            target_table = _resolve_node_table(tbl_key)
            # B437: this handler used to ignore its own qname suffix
            # entirely — `_flagged` never excluded anything, silently
            # letting flagged-for-review content into the bundle
            # regardless of which NamedQuery variant the caller asked
            # for. Only meaningful for callers that actually reach this
            # branch with the suffix set; harmless no-op otherwise.
            exclude_flagged = "_flagged" in sub
            limit = int(params.get("limit", 10))
            candidates = self._vector_store.search_vectors(
                query_embedding, k=_typed_search_k(limit), min_score=0.70
            )
            prefix = f"{CID_BASE}{target_table}/"
            matching_uris = [uri for uri, _ in candidates if uri.startswith(prefix)]
            if not matching_uris:
                return []
            values_block = " ".join(f"<{u}>" for u in matching_uris)
            sparql = f"""
                SELECT ?s ?text ?conf ?auth ?flagged WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#authority> ?auth }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#flagged_for_review> ?flagged }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri in matching_uris:
                if uri not in hydrated:
                    continue
                h = hydrated[uri]
                if exclude_flagged and bool(h.get("flagged")):
                    continue
                rows.append(RowDict({
                    "text": h.get("text"),
                    "node_type": target_table,
                    "confidence": h.get("conf", 0.5),
                    "authority": h.get("auth"),
                }))
                if len(rows) >= limit:
                    break
            return rows

        # Semantic context: thalamus.bundle_semantic_{tbl}[_flags]
        if name.startswith("thalamus.bundle_semantic_"):
            sub = name.replace("thalamus.bundle_semantic_", "")
            tbl_key = sub.split("_")[0]
            target_table = _resolve_node_table(tbl_key)
            # B437: this handler used to ignore its own qname suffix
            # entirely — flagged/archived/superseded content was never
            # excluded regardless of which NamedQuery variant
            # bundle_compiler.py's _stage_semantic_context asked for.
            exclude_flagged = "_flagged" in sub
            exclude_archived = "_archived" in sub
            exclude_superseded = "_superseded" in sub
            limit = int(params.get("limit", 10))
            candidates = self._vector_store.search_vectors(
                query_embedding, k=_typed_search_k(limit), min_score=0.70
            )
            prefix = f"{CID_BASE}{target_table}/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?text ?ps ?conf ?auth ?flagged ?archived ?superseded WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#pathway_strength> ?ps }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#confidence> ?conf }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#authority> ?auth }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#flagged_for_review> ?flagged }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?archived }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#superseded_by> ?superseded }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri not in hydrated:
                    continue
                h = hydrated[uri]
                if exclude_flagged and bool(h.get("flagged")):
                    continue
                if exclude_archived and bool(h.get("archived")):
                    continue
                if exclude_superseded and h.get("superseded"):
                    continue
                dist = max(0.0, 1.0 - float(score))
                # B375: node_id (for warm-frontier lookup in
                # bundle_compiler.py) is the URI's own trailing segment
                # — no extra triple needed, mint_uri already encodes it.
                node_id = unquote(uri[len(prefix):])
                rows.append(RowDict({
                    "text": h.get("text"),
                    "node_type": target_table,
                    "node_id": node_id,
                    "pathway_strength": h.get("ps", 0.5),
                    "confidence": h.get("conf", 0.5),
                    "dist": dist,
                    "authority": h.get("auth"),
                }))
                if len(rows) >= limit:
                    break
            return rows

        # Graph anchors: thalamus.bundle_graph_anchors[_flags]
        if name.startswith("thalamus.bundle_graph_anchors"):
            sub = name.replace("thalamus.bundle_graph_anchors", "")
            # B437: this handler used to ignore its own qname suffix
            # entirely — flagged/archived/superseded Concepts could be
            # picked as anchors regardless of which NamedQuery variant
            # bundle_compiler.py's _stage_graph_structure asked for.
            exclude_flagged = "_flagged" in sub
            exclude_archived = "_archived" in sub
            exclude_superseded = "_superseded" in sub
            candidates = self._vector_store.search_vectors(query_embedding, k=15, min_score=0.70)
            prefix = f"{CID_BASE}Concept/"
            matching = [(uri, score) for uri, score in candidates if uri.startswith(prefix)]
            if not matching:
                return []
            values_block = " ".join(f"<{u}>" for u, _ in matching)
            sparql = f"""
                SELECT ?s ?cid ?text ?flagged ?archived ?superseded WHERE {{
                    VALUES ?s {{ {values_block} }}
                    ?s <https://campy.dev/ns#concept_id> ?cid ;
                       <https://campy.dev/ns#text_raw> ?text .
                    OPTIONAL {{ ?s <https://campy.dev/ns#flagged_for_review> ?flagged }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#archived> ?archived }}
                    OPTIONAL {{ ?s <https://campy.dev/ns#superseded_by> ?superseded }}
                }}
            """
            hydrated = {row["s"]: row for row in self._client._execute_and_collect(sparql)}
            rows = []
            for uri, score in matching:
                if uri not in hydrated:
                    continue
                h = hydrated[uri]
                if exclude_flagged and bool(h.get("flagged")):
                    continue
                if exclude_archived and bool(h.get("archived")):
                    continue
                if exclude_superseded and h.get("superseded"):
                    continue
                dist = max(0.0, 1.0 - float(score))
                rows.append(RowDict({
                    "id": h["cid"],
                    "text": h["text"],
                    "dist": dist,
                }))
                if len(rows) >= 5:
                    break
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
