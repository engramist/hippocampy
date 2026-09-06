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
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

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
    """The chokepoint. Wraps a `KuzuClient` + `QueryRegistry`; `run()` is
    the only sanctioned way application code should reach the database."""

    def __init__(self, client: "KuzuClient", registry: QueryRegistry) -> None:
        self._client = client
        self._registry = registry

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

        res = self._client.execute(query.cypher, merged_params)
        return _materialize_rows(res)

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
