"""
mcp_engine/tabular_ingest.py — Tabular Data (CSV/XLSX/TSV) Ingestion Pipeline

Ingests spreadsheets and CSV files:
1. Parse with pandas (multi-sheet XLSX → one Dataset per sheet)
2. Change detection (SHA256 hash)
3. Schema extraction + metadata
4. Classification with gist/schema.org
5. LLM summary generation
6. Key fact extraction → graph
7. Storage: SQLite (full data) + Kuzu (metadata + facts)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from campy.brain.llm.provider import create_llm_client_for_step
from campy.brain.sensory_cortex.tabular_store import create_table_from_dataframe

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


async def ingest_tabular(
    db: KuzuClient,
    file_path: str,
    config: dict,
    loop_queue=None,
    quest_id: str = ""
) -> dict:
    """
    Ingest a tabular file (CSV, XLSX, TSV) into the system.
    
    Returns:
        {
            "dataset_ids": [list of created Dataset IDs],
            "storage_uris": [list of SQLite paths],
            "row_counts": [list of row counts per dataset],
            "column_counts": [list of column counts],
            "summaries": [list of descriptions],
            "facts_extracted": [list of extracted fact counts],
            "already_current": false/true,
            "sheets_processed": number of sheets (for XLSX)
        }
    """
    try:
        import pandas as pd
    except ImportError:
        return {
            "error": "pandas not installed; cannot ingest tabular data",
            "file_path": file_path
        }

    resolved = Path(file_path)
    if not resolved.exists():
        return {"error": f"File not found: {file_path}", "file_path": file_path}

    extension = resolved.suffix.lower()
    now = datetime.now(timezone.utc).isoformat()
    
    # Step 1: Parse file
    results = {
        "dataset_ids": [],
        "storage_uris": [],
        "row_counts": [],
        "column_counts": [],
        "summaries": [],
        "facts_extracted": [],
        "file_path": str(resolved),
        "sheets_processed": 0,
    }

    try:
        if extension == ".csv":
            dfs = {"sheet_1": pd.read_csv(resolved)}
        elif extension == ".tsv":
            dfs = {"sheet_1": pd.read_csv(resolved, sep="\t")}
        elif extension == ".json":
            dfs = {"sheet_1": pd.read_json(resolved)}
        elif extension in {".xlsx", ".xls"}:
            # Read all sheets; config can override to first-sheet-only
            multi_sheet_strategy = config.get("tabular", {}).get("multi_sheet_strategy", "per_sheet")
            xls = pd.ExcelFile(resolved)
            if multi_sheet_strategy == "first_only":
                dfs = {xls.sheet_names[0]: pd.read_excel(resolved, sheet_name=0)}
            else:
                dfs = {sheet: pd.read_excel(resolved, sheet_name=sheet) for sheet in xls.sheet_names}
        else:
            return {"error": f"Unsupported file extension: {extension}", "file_path": file_path}
    except Exception as e:
        return {"error": f"Failed to parse file: {str(e)}", "file_path": file_path}

    # Step 2: Process each sheet/dataframe
    file_hash = hashlib.sha256(Path(resolved).read_bytes()).hexdigest()

    already_current_flags = []
    for sheet_name, df in dfs.items():
        try:
            dataset_result = await _ingest_single_dataset(
                db, resolved, sheet_name, df, file_hash, config, loop_queue, quest_id, now
            )
            if "error" not in dataset_result:
                results["dataset_ids"].append(dataset_result.get("dataset_id"))
                results["storage_uris"].append(dataset_result.get("storage_uri"))
                results["row_counts"].append(dataset_result.get("row_count"))
                results["column_counts"].append(dataset_result.get("column_count"))
                results["summaries"].append(dataset_result.get("summary"))
                results["facts_extracted"].append(dataset_result.get("facts_extracted", 0))
                already_current_flags.append(dataset_result.get("already_current", False))
        except Exception as e:
            return {"error": f"Failed to ingest sheet {sheet_name}: {str(e)}", "file_path": file_path}

    results["sheets_processed"] = len(dfs)
    # Whole-file already_current is true only if every sheet was unchanged -
    # a multi-sheet XLSX where even one sheet changed still did real work.
    results["already_current"] = bool(already_current_flags) and all(already_current_flags)
    return results


def _infer_content_extension(content: str) -> str:
    """Infer a file extension for raw tabular-shaped content.

    Mirrors the structural checks in memory_router._looks_tabular (JSON
    array, then delimiter consistency), but returns a suffix rather than a
    bool since ingest_tabular() dispatches its parser purely off the file
    extension.
    """
    stripped = content.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            json.loads(stripped)
            return ".json"
        except (json.JSONDecodeError, ValueError):
            pass

    non_empty_lines = [line for line in stripped.split("\n")[:10] if line.strip()]
    if non_empty_lines:
        tab_counts = [line.count("\t") for line in non_empty_lines]
        if tab_counts[0] > 0 and len(set(tab_counts)) <= 2:
            return ".tsv"

    return ".csv"


async def ingest_tabular_from_content(
    db: KuzuClient,
    content: str,
    config: dict,
    loop_queue=None,
    quest_id: str = "",
) -> dict:
    """Ingest raw tabular-shaped text (pasted content, no source file).

    B251: classify_input() can recommend the tabular path for pasted
    content, but ingest_tabular() only ever accepted a file path - so
    tabular-shaped content pasted directly (not uploaded as a file) had no
    way into the tabular pipeline. This writes the content to a throwaway
    temp file with an extension inferred from its structure, delegates to
    ingest_tabular(), and always removes the temp file afterward -
    Dataset.storage_uri points at the independently created SQLite table,
    not the source file, so nothing depends on the temp file surviving
    past this call.
    """
    extension = _infer_content_extension(content)
    fd, tmp_path = tempfile.mkstemp(suffix=extension)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return await ingest_tabular(db, tmp_path, config, loop_queue, quest_id)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _stable_dataset_source_key(file_path: Path, sheet_name: str) -> str:
    """Deterministic identity for a (source path, sheet) pair, mirroring
    ingest.py's _stable_doc_id for Document nodes - this is what lets a
    re-upload of the same file find its prior Dataset. Content-based
    ingestion (ingest_tabular_from_content) always writes to a fresh
    random temp path, so pasted content naturally never collides with a
    prior dataset here - only re-running against the same real file path
    triggers dedup/archiving.
    """
    return hashlib.sha256(f"{file_path}::{sheet_name}".encode()).hexdigest()[:32]


def _find_active_dataset(db: KuzuClient, source_key: str) -> Optional[dict]:
    """Return the most recent non-archived Dataset for this source_key, or
    None if none exists - including on any query error, treated the same
    as "not found" (matches ingest.py's _get_existing_hash convention)."""
    try:
        result = db.execute(
            "MATCH (d:Dataset {source_key: $sk}) WHERE d.archived = false "
            "RETURN d.dataset_id, d.content_hash, d.storage_uri, d.row_count, "
            "       d.column_count, d.description "
            "ORDER BY d.created_at DESC LIMIT 1",
            {"sk": source_key},
        )
        if result.has_next():
            row = result.get_next()
            return {
                "dataset_id": row[0],
                "content_hash": row[1],
                "storage_uri": row[2],
                "row_count": row[3],
                "column_count": row[4],
                "description": row[5],
            }
    except Exception:
        pass
    return None


async def _archive_dataset(db: KuzuClient, dataset_id: str) -> None:
    """Soft-delete a superseded Dataset node - the SQLite table and any
    fact Concepts it produced are left alone (same "archive, don't
    destroy" convention as ingest.py's _archive_old_extracts)."""
    try:
        await db.execute_write(
            "MATCH (d:Dataset {dataset_id: $did}) SET d.archived = true",
            {"did": dataset_id},
        )
    except Exception:
        _logger.debug("Failed to archive superseded Dataset %s", dataset_id)


async def _generate_description(
    df, sheet_name: str, file_path: Path, config: dict, row_count: int, col_count: int
) -> str:
    """Best-effort LLM summary of a dataset. Falls back to a template
    description on any failure or missing LLM client - same graceful-
    degradation convention as loop/step7_5_lesson.py's extract_lessons.
    """
    fallback = f"Dataset from {file_path.name} sheet '{sheet_name}' with {row_count} rows and {col_count} columns"
    try:
        client = create_llm_client_for_step(config, "tabular_ingest")
        if client is None:
            return fallback

        columns_desc = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
        sample = df.head(3).to_dict(orient="records")
        prompt = (
            "Summarize this dataset in 1-2 sentences, mentioning what it appears to represent.\n"
            f"Columns: {columns_desc}\n"
            f"Row count: {row_count}\n"
            f"Sample rows: {sample}\n"
        )
        response = await client.achat([{"role": "user", "content": prompt}])
        summary = (response or "").strip()
        return summary if summary else fallback
    except Exception:
        _logger.debug("LLM summary generation failed for %s sheet %s", file_path, sheet_name)
        return fallback


async def _extract_and_link_key_facts(db: KuzuClient, df, dataset_id: str, config: dict, now: str) -> int:
    """Best-effort LLM key-fact extraction. Each fact becomes a minimal
    Concept node linked to the Dataset via DESCRIBED_BY_DATASET - the same
    "minimal node, real embedding" shape as
    loop/orchestrator.py::_ensure_concept_exists, so these facts are
    structurally indistinguishable from any other retrievable Concept.
    Returns the count of facts successfully created - 0 on any failure,
    malformed response, or missing LLM client.
    """
    try:
        client = create_llm_client_for_step(config, "tabular_ingest")
        if client is None:
            return 0

        columns_desc = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
        sample = df.head(5).to_dict(orient="records")
        prompt = (
            "Extract the 3-5 most important facts from this dataset - totals, "
            "constraints, notable outliers or patterns.\n"
            f"Columns: {columns_desc}\n"
            f"Row count: {len(df)}\n"
            f"Sample rows: {sample}\n\n"
            'Return a JSON list of objects: [{"text": "..."}]\n'
            "If nothing notable, return []"
        )
        response = await client.achat([{"role": "user", "content": prompt}])
        match = re.search(r"\[.*\]", response or "", re.DOTALL)
        facts = json.loads(match.group(0)) if match else []
        if not isinstance(facts, list):
            facts = []
    except Exception:
        _logger.debug("Key fact extraction failed for dataset %s", dataset_id)
        return 0

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    created = 0
    for fact in facts:
        text = str(fact.get("text", "")).strip() if isinstance(fact, dict) else ""
        if not text:
            continue
        try:
            from campy.brain.hippocampus.graph import embeddings as emb
            vector = emb.embed(text, model_name=embedding_model)
            concept_id = str(uuid.uuid4())
            await db.execute_write(
                """
                CREATE (c:Concept {
                    concept_id:       $concept_id,
                    text_raw:         $text_raw,
                    embedding:        $embedding,
                    embedding_model:  $embedding_model,
                    embedding_dim:    $embedding_dim,
                    gist_class:       '',
                    schema_org_type:  '',
                    confidence:       0.75,
                    confidence_low:   false,
                    pathway_strength: 0.55,
                    archived:         false,
                    created_at:       timestamp($now),
                    last_accessed_at: timestamp($now)
                })
                """,
                {
                    "concept_id": concept_id,
                    "text_raw": text,
                    "embedding": vector,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(vector),
                    "now": now,
                },
            )
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $cid}), (d:Dataset {dataset_id: $did}) "
                "CREATE (c)-[:DESCRIBED_BY_DATASET {extraction_method: 'llm', created_at: timestamp($now)}]->(d)",
                {"cid": concept_id, "did": dataset_id, "now": now},
            )
            created += 1
        except Exception:
            _logger.debug("Failed to create fact concept for dataset %s", dataset_id)
            continue
    return created


async def _ingest_single_dataset(
    db: KuzuClient,
    file_path: Path,
    sheet_name: str,
    df,
    file_hash: str,
    config: dict,
    loop_queue,
    quest_id: str,
    now: str
) -> dict:
    """Process a single DataFrame as a Dataset node."""

    source_key = _stable_dataset_source_key(file_path, sheet_name)
    name = sheet_name if sheet_name != "sheet_1" else file_path.stem

    # Change detection: skip all re-processing (no SQLite write, no LLM
    # calls) when an active Dataset for this source already has this exact
    # content hash.
    existing = _find_active_dataset(db, source_key)
    if existing and existing["content_hash"] == file_hash:
        return {
            "dataset_id": existing["dataset_id"],
            "name": name,
            "storage_uri": existing["storage_uri"],
            "row_count": existing["row_count"],
            "column_count": existing["column_count"],
            "summary": existing["description"],
            "facts_extracted": 0,
            "already_current": True,
        }

    # Changed re-upload: archive the superseded Dataset node before
    # creating its replacement (its SQLite table and any fact Concepts
    # already linked to it are left in place, per _archive_dataset).
    if existing:
        await _archive_dataset(db, existing["dataset_id"])

    dataset_id = str(uuid.uuid4())

    # Step 3: Schema extraction
    schema_json = json.dumps({
        "columns": [
            {
                "name": col,
                "type": str(df[col].dtype),
                "null_count": int(df[col].isna().sum()),
                "sample_values": df[col].dropna().head(3).tolist() if len(df) > 0 else []
            }
            for col in df.columns
        ],
        "shape": [len(df), len(df.columns)],
    })

    row_count = len(df)
    col_count = len(df.columns)

    # Step 7: Storage - Create SQLite table
    storage_uri_path = create_table_from_dataframe(dataset_id, df, schema_json)
    storage_uri = str(storage_uri_path)

    # Step 8: Create Dataset node in Kuzu
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    description = await _generate_description(df, sheet_name, file_path, config, row_count, col_count)

    # Create embedding for dataset (from schema summary)
    try:
        from campy.brain.hippocampus.graph import embeddings as emb
        col_names_text = "Columns: " + ", ".join(df.columns)
        embedding = emb.embed(col_names_text, model_name=embedding_model)
    except Exception:
        embedding = None

    # Create Dataset node
    dataset_dict = {
        "dataset_id": dataset_id,
        "name": name,
        "description": description,
        "embedding": embedding,
        "embedding_model": embedding_model,
        "embedding_dim": 384,
        "storage_uri": storage_uri,
        "schema_json": schema_json,
        "row_count": row_count,
        "column_count": col_count,
        "source_format": file_path.suffix.lower(),
        "content_hash": file_hash,
        "source_key": source_key,
        "confidence": 0.95,
        "confidence_low": False,
        "pathway_strength": 0.5,
        "archived": False,
        "created_at": now,
        "last_accessed_at": now,
    }

    # Prepare Cypher for Dataset node creation.
    # created_at/last_accessed_at are TIMESTAMP columns; Kuzu does not
    # implicitly cast a STRING parameter to TIMESTAMP, so those two
    # properties must be wrapped in timestamp(), matching the pattern
    # already used in ingest.py's Document node creation (B250 bugfix).
    _timestamp_props = {"created_at", "last_accessed_at"}
    properties = ", ".join(
        f"{k}: timestamp(${k})" if k in _timestamp_props else f"{k}: ${k}"
        for k in dataset_dict.keys()
    )
    cypher = f"CREATE (d:Dataset {{{properties}}})"

    try:
        db.execute(cypher, dataset_dict)
    except Exception as e:
        return {"error": f"Failed to create Dataset node: {str(e)}"}

    # Create DATASET_DERIVED_FROM edge to Document (if document tracked)
    # Create DATASET_BELONGS_TO_QUEST edge if quest_id provided
    if quest_id:
        db.execute(
            "MATCH (d:Dataset {dataset_id: $did}) "
            "MATCH (q:MainQuest {quest_id: $qid}) "
            "CREATE (d)-[:DATASET_BELONGS_TO_QUEST]->(q)",
            {"did": dataset_id, "qid": quest_id}
        )

    facts_extracted = await _extract_and_link_key_facts(db, df, dataset_id, config, now)

    return {
        "dataset_id": dataset_id,
        "name": dataset_dict["name"],
        "storage_uri": storage_uri,
        "row_count": row_count,
        "column_count": col_count,
        "summary": description,
        "facts_extracted": facts_extracted,
        "already_current": False,
    }
