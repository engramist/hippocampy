"""Single source of truth for node-table metadata (B286).

Derived from schema.NODE_TABLES DDL. Capability tags encode which subsystems
operate on each table. Membership was lifted from the previously hand-written
lists in sweep.py, explore_graph.py, warm_frontier.py, and current_truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from campy.brain.hippocampus.schema import NODE_TABLES


@dataclass(frozen=True)
class TableInfo:
    name: str
    pk: str
    has_embedding: bool
    vector_index: str | None
    tags: frozenset[str]


_PK_RE = re.compile(r"PRIMARY\s+KEY\s*\(\s*(\w+)\s*\)", re.IGNORECASE)
_EMBED_RE = re.compile(r"^\s*embedding\s+FLOAT\[\d+\]", re.IGNORECASE | re.MULTILINE)

# Capability membership — lifted verbatim from the prior hand-written lists.
# Changing membership is a behavior change; do it in its own card.
_TAG_ORDER = {
    "sweepable": (
        "Concept",
        "GlobalConstraint",
        "GlobalPreference",
        "Decision",
        "Constraint",
        "Requirement",
        "ActionItem",
        "Message",
        "DocumentExtract",
    ),
    "retrievable": (
        "Concept",
        "Decision",
        "Constraint",
        "Requirement",
        "ActionItem",
        "GlobalConstraint",
        "GlobalPreference",
        "Lesson",
        "Message",
        "DocumentExtract",
    ),
    "traversable": (
        "Concept",
        "Decision",
        "Constraint",
        "Requirement",
        "ActionItem",
        "GlobalConstraint",
        "GlobalPreference",
        "MainQuest",
        "SideQuest",
        "Message",
        "Document",
        "Lesson",
    ),
    "warmable": (
        "Concept",
        "Decision",
        "Constraint",
        "Requirement",
        "ActionItem",
        "GlobalConstraint",
        "GlobalPreference",
    ),
    "warm_seed": (
        "Concept",
        "Decision",
        "Constraint",
        "Requirement",
        "ActionItem",
    ),
}
_TAG_MEMBERSHIP = {tag: frozenset(names) for tag, names in _TAG_ORDER.items()}


def _index_name(table: str) -> str:
    return f"{table.lower()}_emb_idx"


@lru_cache(maxsize=1)
def get_registry() -> dict[str, TableInfo]:
    registry: dict[str, TableInfo] = {}
    for name, ddl in NODE_TABLES.items():
        pk_match = _PK_RE.search(ddl)
        if not pk_match:
            continue
        has_embedding = _EMBED_RE.search(ddl) is not None
        tags = {
            tag
            for tag, members in _TAG_MEMBERSHIP.items()
            if name in members
        }
        registry[name] = TableInfo(
            name=name,
            pk=pk_match.group(1),
            has_embedding=has_embedding,
            vector_index=_index_name(name) if has_embedding else None,
            tags=frozenset(tags),
        )
    return registry


def get_table(name: str) -> TableInfo | None:
    return get_registry().get(name)


def tables_with(tag: str) -> list[TableInfo]:
    registry = get_registry()
    ordered = _TAG_ORDER.get(tag)
    if ordered is not None:
        return [registry[name] for name in ordered if name in registry]
    return [info for info in registry.values() if tag in info.tags]


def pk_for(table: str) -> str | None:
    info = get_table(table)
    return info.pk if info else None


def vector_index_for(table: str) -> str | None:
    info = get_table(table)
    return info.vector_index if info else None
