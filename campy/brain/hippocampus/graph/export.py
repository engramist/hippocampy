"""Streamed graph export/import helpers for Kuzu portability."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
except ImportError:
    KuzuClient = Any  # type: ignore

import pyoxigraph as ox

from campy.brain.hippocampus.graph.oxigraph_client import (
    CAMPY_NS,
    NODE_COLUMNS,
    NODE_PRIMARY_KEYS,
    REL_COLUMNS,
    OxigraphClient,
    _term_to_python,
    classify_edge,
    mint_uri,
    parse_uri,
)
from campy.brain.hippocampus.schema import NODE_TABLES, PROVENANCE_TABLES, REL_TABLES
from campy.brain.hippocampus.table_registry import get_registry, pk_for

def _is_oxigraph(db: Any) -> bool:
    return type(db).__name__ == "OxigraphClient" or (hasattr(db, "store") and not hasattr(db, "conn"))

_FORMAT_VERSION = 1
_ENGINE = "kuzu-0.11.3"
_EMBEDDING_DIM = 384
_BATCH_SIZE = 500
_INTERNAL_NODE_KEYS = {"_id", "_label"}
_INTERNAL_REL_KEYS = {"_id", "_label", "_src", "_dst"}
_REL_NAME_RE = re.compile(r"CREATE REL TABLE(?: IF NOT EXISTS)?\s+(\w+)", re.IGNORECASE)
_REL_PAIR_RE = re.compile(r"FROM\s+(\w+)\s+TO\s+(\w+)", re.IGNORECASE)
_COLUMN_RE = re.compile(r"^([A-Za-z_]\w*)\s+(.+)$")

# B317: FactEntity/FACT_* rows are ALWAYS `authority='projected'` — they
# are a deliberately separate subgraph from PROVENANCE_TABLES (see
# docs/ARCHITECTURE.md's B317 section and schema.py's FactEntity
# comment), so they never appear in PROVENANCE_TABLES and the
# `authority IS NULL OR <> 'projected'` filter below (written for tables
# where NULL means "earned") would incorrectly keep every FactEntity row
# regardless of `include_projected`. Since every row here is projected
# unconditionally, `include_projected=False` excludes the whole table
# rather than running a per-row authority check.
_ALWAYS_PROJECTED_NODE_TABLES = frozenset({"FactEntity"})
_ALWAYS_PROJECTED_REL_PREFIX = "FACT_"


@dataclass(frozen=True)
class RelationshipEndpoint:
    from_table: str
    to_table: str


def _split_clauses(ddl: str) -> list[str]:
    # REL_TABLES entries are full statements: "CREATE REL TABLE X (FROM A TO B, ...)".
    # NODE_TABLES values are bare column bodies whose only parens belong to
    # "PRIMARY KEY (col)" — stripping to the first/last paren there would
    # discard every column definition.
    if ddl.lstrip().upper().startswith("CREATE"):
        body = ddl[ddl.find("(") + 1 : ddl.rfind(")")]
    else:
        body = ddl
    return [part.strip() for part in body.split(",") if part.strip()]


def _parse_column_types(ddl: str) -> dict[str, str]:
    columns: dict[str, str] = {}
    for clause in _split_clauses(ddl):
        if clause.upper().startswith("FROM "):
            continue
        if clause.upper().startswith("PRIMARY KEY"):
            continue
        match = _COLUMN_RE.match(clause)
        if match:
            columns[match.group(1)] = match.group(2).strip()
    return columns


def _parse_timestamp_fields(ddl: str) -> set[str]:
    return {
        column
        for column, col_type in _parse_column_types(ddl).items()
        if col_type.upper().startswith("TIMESTAMP")
    }


def _parse_relationship_name(ddl: str) -> str:
    match = _REL_NAME_RE.search(ddl)
    if not match:
        raise ValueError(f"Unable to parse relationship table name from DDL: {ddl!r}")
    return match.group(1)


def _parse_relationship_endpoints(ddl: str) -> list[RelationshipEndpoint]:
    return [
        RelationshipEndpoint(from_table=match.group(1), to_table=match.group(2))
        for match in _REL_PAIR_RE.finditer(ddl)
    ]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported export value type: {type(value)!r}")


def _clean_node_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _INTERNAL_NODE_KEYS}


def _clean_rel_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _INTERNAL_REL_KEYS}


def _serialize_row(handle, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, default=_json_default, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _parse_datetime(value: Any) -> Any:
    if isinstance(value, datetime) or value is None:
        return value
    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(text)
    return value


def _coerce_types(row: dict[str, Any], timestamp_fields: set[str]) -> dict[str, Any]:
    coerced = dict(row)
    for field in timestamp_fields:
        if field in coerced:
            coerced[field] = _parse_datetime(coerced[field])
    return coerced


def _ensure_graph_schema(db: KuzuClient) -> None:
    for table_name, ddl in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table_name} ({ddl})")
    for ddl in REL_TABLES:
        db.execute(ddl)


def _try_execute(db: KuzuClient, query: str):
    try:
        return db.execute(query)
    except Exception:
        return None


def _create_vector_indexes(db: KuzuClient) -> None:
    registry = get_registry()
    for table_name, table in registry.items():
        if table.has_embedding and table.vector_index:
            try:
                db.create_vector_index(table_name, "embedding", table.vector_index)
            except Exception as exc:  # pragma: no cover - idempotent path
                if "already exists" not in str(exc).lower():
                    raise

    try:
        db.create_vector_index("GistClass", "centroid", "gistclass_centroid_idx")
    except Exception as exc:  # pragma: no cover - idempotent path
        if "already exists" not in str(exc).lower():
            raise


def _chunked(items: Iterable[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _create_nodes(db: KuzuClient, table_name: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    assignments = ", ".join(f"{column}: ${column}" for column in columns)
    query = f"CREATE (n:{table_name} {{{assignments}}})"
    for row in rows:
        db.execute(query, row)


def _create_relationships(
    db: KuzuClient,
    rel_table: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    row = rows[0]
    from_table = row["_from_table"]
    to_table = row["_to_table"]
    from_pk = pk_for(from_table)
    to_pk = pk_for(to_table)
    if not from_pk or not to_pk:
        raise ValueError(f"Missing primary key metadata for {from_table!r} or {to_table!r}")

    rel_props = [
        key for key in row.keys()
        if key not in {"_from_table", "_from_pk", "_to_table", "_to_pk"}
    ]
    rel_assignment = ", ".join(f"{key}: ${key}" for key in rel_props)
    query = (
        f"MATCH (a:{from_table} {{{from_pk}: $_from_pk}}), "
        f"(b:{to_table} {{{to_pk}: $_to_pk}}) "
        f"CREATE (a)-[r:{rel_table} {{{rel_assignment}}}]->(b)"
        if rel_assignment
        else (
            f"MATCH (a:{from_table} {{{from_pk}: $_from_pk}}), "
            f"(b:{to_table} {{{to_pk}: $_to_pk}}) "
            f"CREATE (a)-[r:{rel_table}]->(b)"
        )
    )
    for row in rows:
        params = {key: value for key, value in row.items() if key in rel_props or key in {"_from_pk", "_to_pk"}}
        db.execute(query, params)


def export_graph_dump(
    db: Any,
    out_dir: str | Path,
    *,
    include_projected: bool = False,
    vector_store: Any | None = None,
) -> dict[str, Any]:
    """Stream the full graph to JSONL files plus a manifest.

    B313: `include_projected` controls whether rows carrying
    `authority = 'projected'` (see schema.AUTHORITY_VALUES) are included.
    Default is False — a disaster-recovery export exists to protect
    **earned** memory (the only copy of a fact Campy holds); a projected
    fact is by definition a rebuildable mirror of something an external
    system already owns, so omitting it makes the default export smaller
    with no loss of anything actually irreplaceable. Pass
    `include_projected=True` for a full mirror (e.g. cloning a dev DB).
    Only PROVENANCE_TABLES tables carry the `authority` column at all;
    every other table is exported in full regardless of this flag.
    """
    out_path = Path(out_dir)
    nodes_dir = out_path / "nodes"
    rels_dir = out_path / "rels"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    rels_dir.mkdir(parents=True, exist_ok=True)

    if _is_oxigraph(db):
        vs = vector_store or getattr(db, "vector_store", None)
        if vs is None and getattr(db, "db_path", None):
            try:
                from campy.brain.hippocampus.graph.vector_store import VectorStore
                vs = VectorStore(Path(db.db_path).parent / "vectors.db")
            except Exception:
                vs = None

        manifest: dict[str, Any] = {
            "format_version": _FORMAT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "engine": "oxigraph-0.5.11",
            "embedding_dim": _EMBEDDING_DIM,
            "include_projected": include_projected,
            "node_tables": {},
            "rel_tables": {},
        }

        rdf_type = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

        for table_name in NODE_TABLES:
            pk_name = pk_for(table_name)
            if not pk_name:
                raise ValueError(f"Missing primary key metadata for node table {table_name!r}")
            cols = NODE_COLUMNS.get(table_name, {})
            emb_cols = [c for c, t in cols.items() if t == "FLOAT[384]"]
            row_count = 0
            with (nodes_dir / f"{table_name}.jsonl").open("w", encoding="utf-8") as handle:
                if not include_projected and table_name in _ALWAYS_PROJECTED_NODE_TABLES:
                    pass
                else:
                    type_node = ox.NamedNode(f"{CAMPY_NS}{table_name}")
                    subjects = [q.subject for q in db.store.quads_for_pattern(None, rdf_type, type_node, None)]
                    rows_to_export = []
                    for subj in subjects:
                        node_props = {col: None for col in cols}
                        if pk_name:
                            _, pk_val = parse_uri(subj.value)
                            node_props[pk_name] = pk_val
                        for q in db.store.quads_for_pattern(subj, None, None, None):
                            pred_val = q.predicate.value
                            if pred_val.startswith(CAMPY_NS):
                                col = pred_val[len(CAMPY_NS):]
                                if col in cols:
                                    val = _term_to_python(q.object)
                                    if cols[col] == "STRING[]":
                                        if node_props[col] is None:
                                            node_props[col] = []
                                        node_props[col].append(val)
                                    else:
                                        node_props[col] = val
                        for ec in emb_cols:
                            if vs and node_props.get(ec) is None:
                                v_uri = subj.value if ec == "embedding" else f"{subj.value}#{ec}"
                                node_props[ec] = vs.get_vector(v_uri)
                        if not include_projected and table_name in PROVENANCE_TABLES:
                            if node_props.get("authority") == "projected":
                                continue
                        rows_to_export.append(node_props)
                    rows_to_export.sort(key=lambda x: str(x.get(pk_name, "")))
                    for r in rows_to_export:
                        _serialize_row(handle, r)
                        row_count += 1
            manifest["node_tables"][table_name] = {"pk": pk_name, "rows": row_count}

        for ddl in REL_TABLES:
            rel_table = _parse_relationship_name(ddl)
            row_count = 0
            with (rels_dir / f"{rel_table}.jsonl").open("w", encoding="utf-8") as handle:
                if not include_projected and rel_table.startswith(_ALWAYS_PROJECTED_REL_PREFIX):
                    pass
                else:
                    try:
                        reification = classify_edge(rel_table)
                    except ValueError:
                        pred = ox.NamedNode(f"{CAMPY_NS}{rel_table}")
                        quads = list(db.store.quads_for_pattern(None, pred, None, None))
                        if quads:
                            raise
                        reification = None
                    rel_cols = REL_COLUMNS.get(rel_table, {})
                    payloads = []
                    if reification == "plain":
                        pred = ox.NamedNode(f"{CAMPY_NS}{rel_table}")
                        for q in db.store.quads_for_pattern(None, pred, None, None):
                            from_t, from_p = parse_uri(q.subject.value)
                            to_t, to_p = parse_uri(q.object.value)
                            payloads.append({
                                "_from_table": from_t,
                                "_from_pk": from_p,
                                "_to_table": to_t,
                                "_to_pk": to_p,
                            })
                    elif reification == "star":
                        sparql = f"""
                            PREFIX campy: <{CAMPY_NS}>
                            SELECT ?s ?o ?p ?v WHERE {{
                                ?s campy:{rel_table} ?o .
                                OPTIONAL {{
                                    << ?s campy:{rel_table} ?o >> ?p ?v .
                                }}
                            }}
                        """
                        by_edge = {}
                        for row in db.store.query(sparql):
                            s_val, o_val = row["s"].value, row["o"].value
                            key = (s_val, o_val)
                            if key not in by_edge:
                                by_edge[key] = {c: None for c in rel_cols}
                            p_term = row["p"]
                            if p_term is not None and str(p_term.value).startswith(CAMPY_NS):
                                col = p_term.value[len(CAMPY_NS):]
                                if col in rel_cols:
                                    by_edge[key][col] = _term_to_python(row["v"])
                        for (s_val, o_val), props in by_edge.items():
                            from_t, from_p = parse_uri(s_val)
                            to_t, to_p = parse_uri(o_val)
                            payload = {
                                "_from_table": from_t,
                                "_from_pk": from_p,
                                "_to_table": to_t,
                                "_to_pk": to_p,
                            }
                            payload.update(props)
                            payloads.append(payload)
                    elif reification == "occurrence":
                        sparql = f"""
                            PREFIX campy: <{CAMPY_NS}>
                            SELECT ?s ?o ?occ ?p ?v WHERE {{
                                ?s campy:{rel_table} ?o .
                                OPTIONAL {{
                                    << ?s campy:{rel_table} ?o >> campy:occurrence ?occ .
                                    OPTIONAL {{ ?occ ?p ?v }}
                                }}
                            }}
                        """
                        by_occ = {}
                        for row in db.store.query(sparql):
                            s_val, o_val = row["s"].value, row["o"].value
                            occ_term = row["occ"]
                            occ_val = occ_term.value if occ_term is not None else None
                            key = (s_val, o_val, occ_val)
                            if key not in by_occ:
                                by_occ[key] = {c: None for c in rel_cols}
                            p_term = row["p"]
                            if p_term is not None and str(p_term.value).startswith(CAMPY_NS):
                                col = p_term.value[len(CAMPY_NS):]
                                if col in rel_cols:
                                    by_occ[key][col] = _term_to_python(row["v"])
                        for (s_val, o_val, _), props in by_occ.items():
                            from_t, from_p = parse_uri(s_val)
                            to_t, to_p = parse_uri(o_val)
                            payload = {
                                "_from_table": from_t,
                                "_from_pk": from_p,
                                "_to_table": to_t,
                                "_to_pk": to_p,
                            }
                            payload.update(props)
                            payloads.append(payload)
                    payloads.sort(key=lambda x: (x["_from_table"], str(x["_from_pk"]), x["_to_table"], str(x["_to_pk"]), json.dumps(x, sort_keys=True, default=str)))
                    for p in payloads:
                        _serialize_row(handle, p)
                        row_count += 1
            manifest["rel_tables"][rel_table] = {"rows": row_count}

        with (out_path / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")

        return manifest

    manifest = {
        "format_version": _FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "engine": _ENGINE,
        "embedding_dim": _EMBEDDING_DIM,
        "include_projected": include_projected,
        "node_tables": {},
        "rel_tables": {},
    }

    for table_name in NODE_TABLES:
        pk_name = pk_for(table_name)
        if not pk_name:
            raise ValueError(f"Missing primary key metadata for node table {table_name!r}")
        row_count = 0
        with (nodes_dir / f"{table_name}.jsonl").open("w", encoding="utf-8") as handle:
            if not include_projected and table_name in _ALWAYS_PROJECTED_NODE_TABLES:
                # Every row is unconditionally 'projected' — nothing to export.
                query = None
            elif not include_projected and table_name in PROVENANCE_TABLES:
                # NULL authority reads as 'earned' (see authority_of()) and
                # must still be exported, so exclude only the explicit
                # 'projected' rows rather than requiring authority = 'earned'.
                query = (
                    f"MATCH (n:{table_name}) "
                    f"WHERE n.authority IS NULL OR n.authority <> 'projected' "
                    f"RETURN n ORDER BY n.{pk_name}"
                )
            else:
                query = f"MATCH (n:{table_name}) RETURN n ORDER BY n.{pk_name}"
            result = _try_execute(db, query) if query is not None else None
            if result is not None:
                while result.has_next():
                    node = _clean_node_row(result.get_next()[0])
                    _serialize_row(handle, node)
                    row_count += 1
        manifest["node_tables"][table_name] = {"pk": pk_name, "rows": row_count}

    for ddl in REL_TABLES:
        rel_table = _parse_relationship_name(ddl)
        row_count = 0
        with (rels_dir / f"{rel_table}.jsonl").open("w", encoding="utf-8") as handle:
            if not include_projected and rel_table.startswith(_ALWAYS_PROJECTED_REL_PREFIX):
                # FACT_* edges are unconditionally 'projected' (B317) —
                # nothing to export; see _ALWAYS_PROJECTED_NODE_TABLES above.
                pass
            else:
                endpoints = _parse_relationship_endpoints(ddl)
                for ep in endpoints:
                    source_label = ep.from_table
                    target_label = ep.to_table
                    source_pk = pk_for(source_label)
                    target_pk = pk_for(target_label)
                    if not source_pk or not target_pk:
                        raise ValueError(
                            f"Missing primary key metadata for relationship {rel_table!r}: "
                            f"{source_label!r} -> {target_label!r}"
                        )
                    query = f"MATCH (a:{source_label})-[r:{rel_table}]->(b:{target_label}) RETURN a, r, b"
                    result = _try_execute(db, query)
                    if result is not None:
                        while result.has_next():
                            source, rel, target = result.get_next()
                            payload = _clean_rel_row(rel)
                            payload.update({
                                "_from_table": source_label,
                                "_from_pk": source[source_pk],
                                "_to_table": target_label,
                                "_to_pk": target[target_pk],
                            })
                            _serialize_row(handle, payload)
                            row_count += 1
        manifest["rel_tables"][rel_table] = {"rows": row_count}

    with (out_path / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")

    return manifest


def import_graph_dump(
    db: Any,
    dump_dir: str | Path,
    vector_store: Any | None = None,
) -> dict[str, Any]:
    """Restore a graph dump into an empty database.

    B313: tolerates a dump produced with `include_projected=False`. A
    PROVENANCE_TABLES jsonl file simply has fewer (possibly zero) rows in
    that case, not a missing file, so the per-table `.exists()` check and
    row loop below need no special-casing. Any relationship whose endpoint
    was a projected row omitted from the dump fails pattern lookup during
    `_create_relationships()` and is silently skipped (standard Cypher
    semantics: zero matched rows means the paired edge insert never fires) rather
    than raising — the missing node is expected, not corrupt data.
    """
    dump_path = Path(dump_dir)
    manifest = json.loads((dump_path / "manifest.json").read_text(encoding="utf-8"))
    if int(manifest.get("format_version", 0)) != _FORMAT_VERSION:
        raise ValueError(f"Unsupported export format version: {manifest.get('format_version')!r}")

    if _is_oxigraph(db):
        vs = vector_store or getattr(db, "vector_store", None)
        if vs is None and getattr(db, "db_path", None):
            try:
                from campy.brain.hippocampus.graph.vector_store import VectorStore
                vs = VectorStore(Path(db.db_path).parent / "vectors.db")
            except Exception:
                vs = None

        node_rows_loaded = 0
        for table_name in NODE_TABLES:
            node_file = dump_path / "nodes" / f"{table_name}.jsonl"
            if not node_file.exists():
                continue
            cols = NODE_COLUMNS.get(table_name, {})
            pk_col = NODE_PRIMARY_KEYS.get(table_name)
            emb_cols = [c for c, t in cols.items() if t == "FLOAT[384]"]
            timestamp_fields = _parse_timestamp_fields(NODE_TABLES[table_name])
            for raw_row in _read_jsonl(node_file):
                coerced = _coerce_types(raw_row, timestamp_fields)
                if vs is not None:
                    uri = mint_uri(table_name, coerced[pk_col])
                    for ec in emb_cols:
                        if coerced.get(ec) is not None:
                            v_uri = uri if ec == "embedding" else f"{uri}#{ec}"
                            vs.upsert_vector(v_uri, coerced[ec])
                db.write_node(table_name, coerced)
                node_rows_loaded += 1

        rel_rows_loaded = 0
        for ddl in REL_TABLES:
            rel_table = _parse_relationship_name(ddl)
            rel_file = dump_path / "rels" / f"{rel_table}.jsonl"
            if not rel_file.exists():
                continue
            timestamp_fields = _parse_timestamp_fields(ddl)
            for raw_row in _read_jsonl(rel_file):
                coerced = _coerce_types(raw_row, timestamp_fields)
                from_table = coerced["_from_table"]
                from_pk = coerced["_from_pk"]
                to_table = coerced["_to_table"]
                to_pk = coerced["_to_pk"]
                s_uri = mint_uri(from_table, from_pk)
                o_uri = mint_uri(to_table, to_pk)
                props = {k: v for k, v in coerced.items() if not k.startswith("_") and v is not None}
                db.write_edge(rel_table, s_uri, o_uri, props or None)
                rel_rows_loaded += 1

        return {
            "ok": True,
            "manifest": manifest,
            "node_rows_loaded": node_rows_loaded,
            "rel_rows_loaded": rel_rows_loaded,
        }

    _ensure_graph_schema(db)

    node_rows_loaded = 0
    for table_name in NODE_TABLES:
        node_file = dump_path / "nodes" / f"{table_name}.jsonl"
        if not node_file.exists():
            continue
        timestamp_fields = _parse_timestamp_fields(NODE_TABLES[table_name])
        chunk: list[dict[str, Any]] = []
        for raw_row in _read_jsonl(node_file):
            chunk.append(_coerce_types(raw_row, timestamp_fields))
            if len(chunk) >= _BATCH_SIZE:
                _create_nodes(db, table_name, chunk)
                node_rows_loaded += len(chunk)
                chunk = []
        if chunk:
            _create_nodes(db, table_name, chunk)
            node_rows_loaded += len(chunk)

    rel_rows_loaded = 0
    for ddl in REL_TABLES:
        rel_table = _parse_relationship_name(ddl)
        rel_file = dump_path / "rels" / f"{rel_table}.jsonl"
        if not rel_file.exists():
            continue
        timestamp_fields = _parse_timestamp_fields(ddl)
        chunk: list[dict[str, Any]] = []
        for raw_row in _read_jsonl(rel_file):
            coerced = _coerce_types(raw_row, timestamp_fields)
            chunk.append(coerced)
            if len(chunk) >= _BATCH_SIZE:
                _create_relationships(db, rel_table, chunk)
                rel_rows_loaded += len(chunk)
                chunk = []
        if chunk:
            _create_relationships(db, rel_table, chunk)
            rel_rows_loaded += len(chunk)

    _create_vector_indexes(db)

    return {
        "ok": True,
        "manifest": manifest,
        "node_rows_loaded": node_rows_loaded,
        "rel_rows_loaded": rel_rows_loaded,
    }


def export_graph(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    warn_if_live: bool = True,
    include_projected: bool = False,
) -> dict[str, Any]:
    """Convenience wrapper that opens the database read-only and exports it.

    `include_projected` is forwarded to `export_graph_dump()` — see that
    function's docstring. Default (False) exports earned memory only, the
    scope that actually matters for disaster recovery.
    """
    path_obj = Path(db_path)
    if (path_obj.is_dir() and (path_obj / "CURRENT").exists()) or not hasattr(KuzuClient, "execute"):
        db = OxigraphClient(str(db_path), read_only=True)
        try:
            return export_graph_dump(db, out_dir, include_projected=include_projected)
        finally:
            db.close()
    else:
        db = KuzuClient(str(db_path), read_only=True)
        try:
            return export_graph_dump(db, out_dir, include_projected=include_projected)
        finally:
            db.close()


def import_graph(db_path: str | Path, dump_dir: str | Path) -> dict[str, Any]:
    """Convenience wrapper that opens a database and restores a dump."""
    path_obj = Path(db_path)
    if str(db_path).endswith(".oxdb") or not hasattr(KuzuClient, "execute"):
        db = OxigraphClient(str(db_path))
        try:
            return import_graph_dump(db, dump_dir)
        finally:
            db.close()
    else:
        db = KuzuClient(str(db_path))
        try:
            return import_graph_dump(db, dump_dir)
        finally:
            db.close()
