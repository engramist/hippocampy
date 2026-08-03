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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from campy.brain.sensory_cortex.tabular_store import create_table_from_dataframe

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient


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
        except Exception as e:
            return {"error": f"Failed to ingest sheet {sheet_name}: {str(e)}", "file_path": file_path}
    
    results["sheets_processed"] = len(dfs)
    results["already_current"] = False
    return results


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
    
    # Generate dataset_id
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
    
    # Generate a description (simplified - LLM generation would require async LLM call)
    description = f"Dataset from {file_path.name} sheet '{sheet_name}' with {row_count} rows and {col_count} columns"

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
        "name": sheet_name if sheet_name != "sheet_1" else file_path.stem,
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

    return {
        "dataset_id": dataset_id,
        "name": dataset_dict["name"],
        "storage_uri": storage_uri,
        "row_count": row_count,
        "column_count": col_count,
        "summary": description,
        "facts_extracted": 0,  # Could extract facts from data summary
    }
