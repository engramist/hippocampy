# B-286 — Consolidate Node Table Registry

Card: backlog/B286.md
Priority: P2
Dependencies: none (land before B280/B282/B285 if possible)

## Summary

One derived registry for node-table metadata; five consumer sites import it. Mirrors the existing `get_relationship_types()` pattern (B72) for rel tables.

## Design

### `campy/brain/hippocampus/table_registry.py`

```python
"""Single source of truth for node-table metadata (B286).

Derived from schema.NODE_TABLES DDL. Capability tags encode which subsystems
operate on each table — membership was lifted from the previously hand-written
lists in sweep.py, explore_graph.py, warm_frontier.py, and current_truth.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from functools import lru_cache

from campy.brain.hippocampus.schema import NODE_TABLES


@dataclass(frozen=True)
class TableInfo:
    name: str
    pk: str
    has_embedding: bool
    vector_index: str | None        # e.g. "concept_emb_idx"; None if no embedding
    tags: frozenset[str]            # {"sweepable","retrievable","traversable","warmable"}


_PK_RE = re.compile(r"PRIMARY\s+KEY\s*\(\s*(\w+)\s*\)", re.IGNORECASE)

# Capability membership — lifted verbatim from the current hand-written lists.
# CHANGING MEMBERSHIP IS A BEHAVIOR CHANGE; do it in its own commit.
_SWEEPABLE   = {"Concept","GlobalConstraint","GlobalPreference","Decision","Constraint",
                "Requirement","ActionItem","Message","DocumentExtract"}          # = SWEEP_TABLES
_RETRIEVABLE = {"Concept","Decision","Constraint","Requirement","ActionItem",
                "GlobalConstraint","GlobalPreference","Lesson","Message","DocumentExtract"}  # = current_truth artifact_tables
_TRAVERSABLE = {"Concept","Decision","Constraint","Requirement","ActionItem",
                "GlobalConstraint","GlobalPreference","MainQuest","SideQuest",
                "Message","Document","Lesson"}                                   # = explore_graph _NODE_TABLES
_WARMABLE    = {"Concept","Decision","Constraint","Requirement","ActionItem",
                "GlobalConstraint","GlobalPreference"}                            # = warm_frontier NODE_PK_MAP


def _index_name(table: str) -> str:
    return f"{table.lower()}_emb_idx"     # matches schema.py ensure_schema convention


@lru_cache(maxsize=1)
def get_registry() -> dict[str, TableInfo]:
    registry = {}
    for name, ddl in NODE_TABLES.items():
        pk_match = _PK_RE.search(ddl)
        if not pk_match:
            continue   # tables without simple PK are excluded; assert none exist in test
        has_emb = re.search(r"^\s*embedding\s+FLOAT\[\d+\]", ddl, re.MULTILINE) is not None
        tags = set()
        if name in _SWEEPABLE:   tags.add("sweepable")
        if name in _RETRIEVABLE: tags.add("retrievable")
        if name in _TRAVERSABLE: tags.add("traversable")
        if name in _WARMABLE:    tags.add("warmable")
        registry[name] = TableInfo(
            name=name, pk=pk_match.group(1), has_embedding=has_emb,
            vector_index=_index_name(name) if has_emb else None,
            tags=frozenset(tags),
        )
    return registry


def tables_with(tag: str) -> list[TableInfo]:
    return [t for t in get_registry().values() if tag in t.tags]


def pk_for(table: str) -> str | None:
    info = get_registry().get(table)
    return info.pk if info else None
```

Verification step for the implementer: check `schema.py ensure_schema` (~line 1256) — the index naming there is `f"{table.lower()}_emb_idx"`. Confirm it matches each hand-written index name (note `actionitem_emb_idx` vs `action_item` — `"ActionItem".lower()` = `"actionitem"` ✓; `documentextract_emb_idx` ✓; `globalconstraint_emb_idx` ✓). If any existing list disagrees with the convention, the LIST is wrong only if tests prove it — reconcile carefully.

Also confirm exact membership of each hand-written list before encoding the tag sets — read the four files; the sets above were taken from the current code but MUST be re-verified at implementation time. The ordering of SWEEP_TABLES (Concept first) is intentional in sweeps? Check; if order matters anywhere, preserve via explicit ordering key.

### Consumer migrations (one commit each)

1. **sweep.py**: replace the literal with
   ```python
   from campy.brain.hippocampus.table_registry import tables_with
   SWEEP_TABLES = [(t.name, t.pk, _config_key(t.name), t.vector_index)
                   for t in tables_with("sweepable")]
   ```
   The third element (config key like `"global_constraint"`) is snake_case of the table name — write `_config_key()` (regex `(?<!^)(?=[A-Z])` → `_`, lower). Assert equality with the old literal in the test BEFORE deleting it.

2. **explore_graph.py**: `_NODE_TABLES = [(t.name, t.pk) for t in tables_with("traversable")]`. Note both quest tables share pk `quest_id` — fine.

3. **warm_frontier.py**: `NODE_PK_MAP = {t.name: t.pk for t in tables_with("warmable")}`.

4. **thalamus/tools/__init__.py**: in `current_truth`, `artifact_tables = [(t.name, t.vector_index, t.pk) for t in tables_with("retrievable")]`. Search the file for OTHER hardcoded `(table, index, pk)` triples (`rg "_emb_idx" campy/brain/thalamus/tools/__init__.py`) — vector_search calls with literal index names for Lesson/Plan/Procedure singletons can stay (single-table calls), but replace the index-name literals with `get_registry()["Lesson"].vector_index` where convenient. Don't over-reach: multi-table loops are the target; single-table calls are optional cleanup.

## Tests (`tests/test_table_registry.py`)

```python
def test_every_embedding_table_registered():
    from campy.brain.hippocampus.schema import NODE_TABLES
    from campy.brain.hippocampus.table_registry import get_registry
    reg = get_registry()
    for name, ddl in NODE_TABLES.items():
        if "embedding     FLOAT" in ddl or "embedding FLOAT" in ddl:
            assert name in reg and reg[name].has_embedding

def test_sweep_tables_match_legacy_literal():
    # paste the old SWEEP_TABLES literal here as EXPECTED; compare
def test_explore_tables_match_legacy_literal(): ...
def test_warm_pk_map_matches_legacy_literal(): ...
def test_retrievable_matches_current_truth_literal(): ...
def test_pk_parsed_for_all_tables():
    # every NODE_TABLES entry has a parsed PK (or document exclusions)
```

The "match legacy literal" tests are the heart of the card — they freeze current behavior. Future membership changes then edit the tag sets AND the test expectations deliberately.

## Validation Commands

```bash
pytest tests/test_table_registry.py -v
pytest tests/ -q -k "sweep or explore or warm or truth or web"
rg "concept_emb_idx" campy/brain --include='*.py' -g '!__pycache__'   # registry+schema only
python3 -c "from campy.brain.hippocampus.table_registry import get_registry; print(len(get_registry()))"
```

## Risks

- Import-cycle: registry imports schema; schema must not import registry. Check schema.py imports — it imports kuzu_client and embeddings only. Safe.
- Ecosystem layer rules (`docs/ecosystem-rules.md`): thalamus/temporal_lobe/brainstem importing from hippocampus is the existing direction (they already import schema/kuzu_client) — verify and cite in PR.
- ARC tables (GridEntity, ArcMechanic, ...) get registry entries with empty tags — harmless, and B278's ARC tools can adopt tags later.
