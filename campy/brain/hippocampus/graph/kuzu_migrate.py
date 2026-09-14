"""campy/brain/hippocampus/graph/kuzu_migrate.py — B417 item 3: the real
Kùzu -> Oxigraph data migrator.

Every user who upgraded across the B397 cutover with a pre-existing
`~/.campy/brain.db` had it auto-backed-up (B417 items 1+2,
`oxigraph_client._auto_heal_legacy_store_path`) rather than migrated — the
daemon now starts cleanly, but the prior graph sits inert in a
`brain.db.kuzu-bak-*` sibling file. This module reads that legacy file
directly via the `kuzu` package (an optional, on-demand dependency for this
one-shot operation only — never imported at daemon startup) and writes each
row into a live `OxigraphClient`.

**Never assume today's `schema.py` matches whatever schema the backup was
created under.** A backup may predate months of schema drift (B412/B413/
B420-B429 all changed columns/tables). This module discovers the ACTUAL
tables, columns, and rel from/to endpoints present in the specific legacy
file via Kùzu's own introspection procedures (`CALL show_tables()`,
`CALL TABLE_INFO(...)`, `CALL SHOW_CONNECTION(...)`) rather than hard-coding
anything from `schema.py`, then intersects each row against today's
`NODE_COLUMNS`/`REL_COLUMNS`/`EDGE_REIFICATION` at write time. Anything on
the legacy side that no longer has a home today (a renamed/removed table or
column) is skipped and reported, never a fatal error — a migration must not
abort halfway through a customer's only copy of months of memory over one
drifted table.

Idempotent by construction: `OxigraphClient.write_node()`/`write_edge()`
assert RDF triples via `INSERT DATA`, which is a set union — re-running this
migration (e.g. after an interrupted first attempt) reasserts identical
triples, not duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from campy.brain.hippocampus.graph.oxigraph_client import (
    NODE_COLUMNS,
    NODE_PRIMARY_KEYS,
    REL_COLUMNS,
    EDGE_REIFICATION,
    OxigraphClient,
    classify_edge,
)


class KuzuNotAvailableError(RuntimeError):
    """Raised when the optional `kuzu` package is not installed. This
    migration is the one legitimate runtime (not just test) need for it —
    see backlog/B427.md for why `kuzu` otherwise stays a test-only extra."""


def _import_kuzu():
    try:
        import kuzu
    except ImportError as exc:
        raise KuzuNotAvailableError(
            "The kuzu package is required to read a legacy brain.db backup and is "
            "not installed. Install it with: pip install kuzu==0.11.3"
        ) from exc
    return kuzu


@dataclass(frozen=True)
class KuzuNodeTableInfo:
    pk: str
    columns: dict[str, str]  # column name -> Kùzu type string


@dataclass(frozen=True)
class KuzuRelTableInfo:
    from_table: str
    to_table: str
    from_pk: str
    to_pk: str
    columns: dict[str, str]


@dataclass(frozen=True)
class KuzuSchemaInfo:
    node_tables: dict[str, KuzuNodeTableInfo]
    rel_tables: dict[str, KuzuRelTableInfo]


@dataclass
class MigrationReport:
    nodes_migrated: dict[str, int] = field(default_factory=dict)
    edges_migrated: dict[str, int] = field(default_factory=dict)
    node_tables_skipped_unknown: set[str] = field(default_factory=set)
    edge_tables_skipped_unknown: set[str] = field(default_factory=set)
    node_rows_skipped: dict[str, int] = field(default_factory=dict)
    edge_rows_skipped: dict[str, int] = field(default_factory=dict)
    dropped_columns: dict[str, set[str]] = field(default_factory=dict)

    def total_nodes(self) -> int:
        return sum(self.nodes_migrated.values())

    def total_edges(self) -> int:
        return sum(self.edges_migrated.values())

    def summary(self) -> str:
        lines = [
            f"Migrated {self.total_nodes()} node(s) across {len(self.nodes_migrated)} table(s), "
            f"{self.total_edges()} edge(s) across {len(self.edges_migrated)} table(s).",
        ]
        if self.node_tables_skipped_unknown:
            lines.append(f"Skipped unknown node table(s): {sorted(self.node_tables_skipped_unknown)}")
        if self.edge_tables_skipped_unknown:
            lines.append(f"Skipped unknown edge table(s): {sorted(self.edge_tables_skipped_unknown)}")
        if self.dropped_columns:
            for table, cols in sorted(self.dropped_columns.items()):
                lines.append(f"  {table}: dropped column(s) no longer in schema: {sorted(cols)}")
        if self.node_rows_skipped:
            lines.append(f"Node rows skipped (individual errors): {self.node_rows_skipped}")
        if self.edge_rows_skipped:
            lines.append(f"Edge rows skipped (individual errors): {self.edge_rows_skipped}")
        return "\n".join(lines)


def discover_kuzu_schema(conn: Any) -> KuzuSchemaInfo:
    """Introspect the ACTUAL tables/columns/rel-endpoints present in this
    specific Kùzu connection — never assumes today's schema.py."""
    node_tables: dict[str, KuzuNodeTableInfo] = {}
    rel_tables: dict[str, KuzuRelTableInfo] = {}

    table_rows = conn.execute("CALL show_tables() RETURN *")
    tables: list[tuple[str, str]] = []
    while table_rows.has_next():
        row = table_rows.get_next()
        # columns: [id, name, type, database name, comment]
        tables.append((row[1], row[2]))

    for name, kind in tables:
        info_rows = conn.execute(f"CALL TABLE_INFO('{name}') RETURN *")
        columns: dict[str, str] = {}
        pk: str | None = None
        while info_rows.has_next():
            row = info_rows.get_next()
            # node columns: [property id, name, type, default expression, primary key]
            # rel columns:  [property id, name, type, default expression, storage_direction]
            col_name, col_type = row[1], row[2]
            columns[col_name] = col_type
            if kind == "NODE" and len(row) >= 5 and row[4] is True:
                pk = col_name
        if kind == "NODE":
            if pk is None:
                continue  # a node table with no discoverable PK is unusable; skip it
            node_tables[name] = KuzuNodeTableInfo(pk=pk, columns=columns)
        elif kind == "REL":
            conn_rows = conn.execute(f"CALL SHOW_CONNECTION('{name}') RETURN *")
            if not conn_rows.has_next():
                continue
            crow = conn_rows.get_next()
            # [source table name, destination table name, source pk, destination pk]
            rel_tables[name] = KuzuRelTableInfo(
                from_table=crow[0], to_table=crow[1],
                from_pk=crow[2], to_pk=crow[3], columns=columns,
            )

    return KuzuSchemaInfo(node_tables=node_tables, rel_tables=rel_tables)


def _quote_col_list(cols: list[str]) -> str:
    return ", ".join(f"n.{c}" for c in cols)


def migrate_kuzu_to_oxigraph(kuzu_db_path: str, target: OxigraphClient) -> MigrationReport:
    """Read every node and edge from the legacy Kùzu file at `kuzu_db_path`
    and write it into `target` (a live `OxigraphClient`). Read-only against
    the Kùzu file — never writes back to it. See module docstring for the
    schema-drift and idempotency guarantees.

    Two-phase (all nodes, then all edges) so an edge is never written for a
    node that was itself skipped as an unknown table.
    """
    kuzu = _import_kuzu()
    db = kuzu.Database(str(kuzu_db_path), read_only=True)
    conn = kuzu.Connection(db)
    try:
        legacy_schema = discover_kuzu_schema(conn)
        report = MigrationReport()

        # Tables recognized as valid under today's schema — tracked
        # independently of row COUNT. A node table can be perfectly valid
        # (declared in NODE_COLUMNS/NODE_PRIMARY_KEYS) yet have zero rows in
        # this specific legacy backup (e.g. a table added to the schema after
        # the backup was taken); that must not make every edge touching it
        # look "unknown" — it just has nothing to migrate, which the edge
        # MATCH query below will correctly find on its own.
        known_node_tables: set[str] = set()
        for table, info in legacy_schema.node_tables.items():
            today_cols = NODE_COLUMNS.get(table)
            today_pk = NODE_PRIMARY_KEYS.get(table)
            if today_cols is None or today_pk is None:
                report.node_tables_skipped_unknown.add(table)
                continue
            usable_cols = [c for c in info.columns if c in today_cols]
            dropped = set(info.columns) - set(usable_cols)
            if dropped:
                report.dropped_columns.setdefault(table, set()).update(dropped)
            if info.pk not in usable_cols:
                # PK itself was renamed/removed from the current schema — cannot
                # address this table's rows at all under today's identity scheme.
                report.node_tables_skipped_unknown.add(table)
                continue
            known_node_tables.add(table)

            rows = conn.execute(f"MATCH (n:{table}) RETURN {_quote_col_list(usable_cols)}")
            col_names = usable_cols
            count = 0
            while rows.has_next():
                values = rows.get_next()
                props = dict(zip(col_names, values))
                if props.get(info.pk) is None:
                    report.node_rows_skipped[table] = report.node_rows_skipped.get(table, 0) + 1
                    continue
                try:
                    target.write_node(table, props)
                    count += 1
                except Exception:
                    report.node_rows_skipped[table] = report.node_rows_skipped.get(table, 0) + 1
            if count:
                report.nodes_migrated[table] = report.nodes_migrated.get(table, 0) + count

        for table, info in legacy_schema.rel_tables.items():
            if info.from_table not in known_node_tables or info.to_table not in known_node_tables:
                report.edge_tables_skipped_unknown.add(table)
                continue
            try:
                classify_edge(table)
            except ValueError:
                report.edge_tables_skipped_unknown.add(table)
                continue
            today_rel_cols = REL_COLUMNS.get(table, {})
            usable_cols = [c for c in info.columns if c in today_rel_cols]
            dropped = set(info.columns) - set(usable_cols)
            if dropped:
                report.dropped_columns.setdefault(table, set()).update(dropped)

            select_cols = ", ".join([f"a.{info.from_pk}", f"b.{info.to_pk}"] + [f"r.{c}" for c in usable_cols])
            rows = conn.execute(
                f"MATCH (a:{info.from_table})-[r:{table}]->(b:{info.to_table}) RETURN {select_cols}"
            )
            count = 0
            while rows.has_next():
                values = rows.get_next()
                from_pk_val, to_pk_val = values[0], values[1]
                props = dict(zip(usable_cols, values[2:]))
                if from_pk_val is None or to_pk_val is None:
                    report.edge_rows_skipped[table] = report.edge_rows_skipped.get(table, 0) + 1
                    continue
                try:
                    from campy.brain.hippocampus.graph.vector_store import mint_uri
                    src = mint_uri(info.from_table, from_pk_val)
                    dst = mint_uri(info.to_table, to_pk_val)
                    target.write_edge(table, src, dst, props or None)
                    count += 1
                except Exception:
                    report.edge_rows_skipped[table] = report.edge_rows_skipped.get(table, 0) + 1
            if count:
                report.edges_migrated[table] = report.edges_migrated.get(table, 0) + count

        return report
    finally:
        conn.close()
