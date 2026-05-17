# Plan for 250 - Tabular Ingestion Pipeline

## Metadata

- **Card ID**: 250
- **Priority**: P1
- **Dependencies**: 249
- **Risk**: Medium - new ingestion path, LLM dependency for summary/extraction

## Goal

Extend Campy's ingestion to handle spreadsheet/CSV uploads with intelligent two-layer storage: full tabular data in SQLite and extracted knowledge in the Kuzu graph.

## Step 1: Extend ALLOWED_EXTENSIONS in ingest.py

Add to `ALLOWED_EXTENSIONS` set in `mcp_engine/ingest.py`:

```python
".csv", ".xlsx", ".tsv"
```

Add to `MIME_MAP`:

```python
".csv": "text/csv",
".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
".tsv": "text/tab-separated-values",
```

Add dispatch logic in `ingest_document()`: if extension is tabular, delegate to `tabular_ingest.ingest_tabular()`.

## Step 2: Create tabular_ingest.py

New module `mcp_engine/tabular_ingest.py`:

### `async def ingest_tabular(db, file_path, config, loop_queue, quest_id)`

1. **Parse file:**
   - CSV/TSV: `pd.read_csv(file_path, sep=...)` with error handling for malformed files
   - XLSX: `pd.read_excel(file_path, sheet_name=None)` — returns dict of DataFrames if multiple sheets
   - For multi-sheet XLSX: create one Dataset per sheet

2. **Change detection:**
   - SHA256 hash of file bytes
   - If unchanged from existing Dataset.content_hash, return `already_current: true`

3. **Schema extraction:**
   ```python
   schema_json = {
       "columns": [
           {"name": col, "type": str(df[col].dtype), "null_count": int(df[col].isna().sum()),
            "sample_values": df[col].dropna().head(3).tolist()}
           for col in df.columns
       ],
       "shape": [len(df), len(df.columns)],
   }
   ```

4. **Classification (gist/schema.org):**
   - Embed column headers as a single text: `"Columns: name, email, department, salary"`
   - Run through Step 2 (gist classification) to get ontological class
   - Use schema.org routing to determine dataset type (e.g., schema:Dataset, schema:ItemList)

5. **LLM summary generation:**
   - Prompt: "Summarize this dataset in 1-2 sentences. Columns: {columns}. Row count: {row_count}. Sample: {first_3_rows}"
   - Store result as Dataset.description

6. **Key fact extraction:**
   - Prompt: "Extract the 3-5 most important facts from this dataset. Include totals, constraints, notable patterns."
   - Each extracted fact → queue to Gated Consolidation Loop as a synthetic message
   - Loop creates Concepts/Constraints/Decisions linked back to Dataset via `DESCRIBED_BY_DATASET`

7. **Storage:**
   - Call `tabular_store.create_table_from_dataframe(dataset_id, df, schema_json)`
   - Create Dataset node in Kuzu with all metadata
   - Create `DATASET_DERIVED_FROM` edge to Document node (if source file tracked)
   - Create `DATASET_BELONGS_TO_QUEST` edge to current quest

8. **Return:**
   ```json
   {
       "dataset_id": "uuid",
       "name": "Q2_Budget",
       "storage_uri": "~/.campy/tables/{id}.sqlite",
       "row_count": 47,
       "column_count": 5,
       "summary": "Q2 marketing budget with 47 line items...",
       "facts_extracted": 4,
       "already_current": false
   }
   ```

## Step 3: Handle Multi-Sheet XLSX

For XLSX files with multiple sheets:
- Default: create one Dataset per sheet, name includes sheet name
- Config option: `tabular.multi_sheet_strategy = "per_sheet" | "first_only"`
- Each sheet gets its own SQLite file and Dataset node

## Step 4: Tests

Create `tests/test_tabular_ingest.py`:

- Test CSV ingestion end-to-end (parse, classify, store, extract)
- Test XLSX ingestion with single sheet
- Test XLSX ingestion with multiple sheets
- Test TSV ingestion
- Test change detection (re-upload unchanged file)
- Test change detection (re-upload modified file)
- Test malformed CSV handling (graceful error)
- Test key fact extraction creates graph Concepts
- Test Dataset node has correct schema_json

Create `tests/fixtures/`:
- `sample_budget.csv` — simple budget with categories and amounts
- `sample_contacts.xlsx` — multi-sheet workbook
- `sample_data.tsv` — tab-separated values

## Completion Criteria

```bash
.venv/bin/pytest -q tests/test_tabular_ingest.py tests/test_tabular_store.py
.venv/bin/pytest -q
```
