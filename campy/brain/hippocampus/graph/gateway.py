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

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# Matches a `{` that is NOT immediately (modulo whitespace) followed by
# either a closing `}` (empty map literal, `{}`) or an identifier + `:`
# (a Kùzu node/relationship/struct property map, e.g. `{lesson_id: $lid}`
# or a CREATE literal `{ plan_id: $plan_id, goal: $goal, ... }`). Any other
# `{` is almost certainly a leftover Python format placeholder
# (`f"MATCH (a:{table})"` or a `.format()` template that never got filled
# in) — exactly the interpolation-at-the-call-site defect this registry
# exists to catch at import time rather than in production.
_BARE_BRACE_RE = re.compile(r"\{")
_SAFE_BRACE_TAIL_RE = re.compile(r"\s*(\}|[A-Za-z_][A-Za-z0-9_]*\s*:)")


def _find_unsafe_brace(cypher: str) -> int | None:
    """Return the index of the first `{` that isn't part of a Kùzu literal
    map, or None if every `{` in `cypher` looks like a legitimate map."""
    for match in _BARE_BRACE_RE.finditer(cypher):
        tail = cypher[match.end():]
        if not _SAFE_BRACE_TAIL_RE.match(tail):
            return match.start()
    return None


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
    """

    name: str
    cypher: str
    params: tuple[str, ...]
    mutating: bool
    description: str

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

        bad_brace = _find_unsafe_brace(self.cypher)
        if bad_brace is not None:
            snippet = self.cypher[max(0, bad_brace - 20):bad_brace + 20]
            raise ValueError(
                f"NamedQuery {self.name!r}: cypher contains a '{{' at offset {bad_brace} that "
                f"is not a Kùzu literal map (looks like an unresolved template/format "
                f"placeholder — near: ...{snippet!r}...). All variable input must go through "
                f"$param placeholders, not string interpolation."
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


class GraphGateway:
    """The chokepoint. Wraps a `KuzuClient` + `QueryRegistry`; `run()` is
    the only sanctioned way application code should reach the database."""

    def __init__(self, client: "KuzuClient", registry: QueryRegistry) -> None:
        self._client = client
        self._registry = registry

    async def run(self, name: str, /, **params: Any) -> Any:
        """Look up `name`, validate `params` against the query's declared
        set, then route to `execute_read`/`execute_write` by `mutating`.

        Raises:
            KeyError: `name` isn't registered (message includes `name`).
            TypeError: `params` doesn't exactly match the query's declared
                parameter names — raised before the database is touched.
        """
        query = self._registry.get(name)

        declared = set(query.params)
        provided = set(params)
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

        if query.mutating:
            return await self._client.execute_write(query.cypher, params)
        return await self._client.execute_read(query.cypher, params)

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
            return await self._client.execute_write(cypher, params)
        return await self._client.execute_read(cypher, params)
