#!/usr/bin/env python3
"""B454 one-time backfill: index nodes that were created without vector/FTS entries.

Between the SPARQL cutover and B454, `sparql=` node-create queries never added
their node to the sqlite-vec vector store or FTS5 text index (only Lessons did).
The nodes exist in the graph but were unreachable by similarity/lexical search.
This embeds each such node's `text_raw` and indexes it. Idempotent: nodes that
already have a vector / FTS row are skipped.

Run with the daemon STOPPED (RocksDB allows one opener):

    python scripts/backfill_vector_index.py ~/.campy/brain.db --dry-run
    python scripts/backfill_vector_index.py ~/.campy/brain.db

The vector store is `<store dir>/vectors.db`, as OxigraphClient resolves it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pyoxigraph as ox

CAMPY = "https://campy.dev/ns#"
RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
TEXT_RAW = ox.NamedNode(CAMPY + "text_raw")
DEFAULT = ox.DefaultGraph()

TABLES = (
    "Message", "Concept", "Decision", "Constraint", "Requirement", "ActionItem",
    "DocumentExtract", "Lesson", "SideQuest",
)


def backfill(store, vs, embed, tables=TABLES, dry_run: bool = False, batch_log: int = 500) -> dict[str, dict[str, int]]:
    """Index every `tables` node with a `text_raw` that lacks a vector/FTS row.
    `embed(text) -> list[float]`. Returns per-table counts."""
    with vs._lock:
        in_fts = {r[0] for r in vs._conn.execute("select uri from lexical")}
    report: dict[str, dict[str, int]] = {}
    for table in tables:
        seen = need_vec = need_fts = 0
        t0 = time.time()
        for q in store.quads_for_pattern(None, RDF_TYPE, ox.NamedNode(CAMPY + table), DEFAULT):
            uri = q.subject.value
            text = next(
                (str(t.object.value) for t in store.quads_for_pattern(q.subject, TEXT_RAW, None, DEFAULT)),
                None,
            )
            if not text or not text.strip():
                continue
            seen += 1
            has_vec = vs.get_vector(uri) is not None
            has_fts = uri in in_fts
            if has_vec and has_fts:
                continue
            need_vec += 0 if has_vec else 1
            need_fts += 0 if has_fts else 1
            if dry_run:
                continue
            if not has_vec:
                vs.upsert_vector(uri, embed(text))
            if not has_fts:
                vs.index_text(uri, text)
            if (need_vec + need_fts) % batch_log == 0:
                print(f"  {table}: {need_vec} vectors / {need_fts} fts so far ({time.time() - t0:.0f}s)")
        report[table] = {"nodes_with_text": seen, "missing_vector": need_vec, "missing_fts": need_fts}
        print(f"{table:16s} nodes_with_text={seen:>7,} missing_vector={need_vec:>6,} missing_fts={need_fts:>6,}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store_path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    args = ap.parse_args(argv)

    from campy.brain.hippocampus.graph import embeddings as emb
    from campy.brain.hippocampus.graph.vector_store import VectorStore

    store = ox.Store(args.store_path)
    vs = VectorStore(Path(args.store_path).parent / "vectors.db")
    print(f"opened {args.store_path}: {len(store):,} quads")
    backfill(store, vs, lambda text: emb.embed(text, model_name=args.model), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
