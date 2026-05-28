"""
mcp_engine/ingest.py — Open Brain Document Ingestion Pipeline

Ingests local text files into the graph as Document + DocumentExtract nodes.
Extracts are embedded and run through the Gated Consolidation Loop.

Security (non-negotiable):
  - All paths canonicalized via os.path.realpath() before any read
  - Only allowlisted extensions accepted
  - No symlink traversal, no .. escapes

Chunking strategy (semantic paragraph chunking):
  - Split at blank-line paragraph boundaries (\\n\\n)
  - Also break at Markdown headings (# / ## / etc.)
  - Merge orphan chunks shorter than MIN_CHUNK_CHARS into adjacent chunks
  - Cap at MAX_CHUNK_CHARS; split oversized chunks at sentence boundary
  - Track byte_start/byte_end and line_start/line_end per chunk

Change detection:
  - SHA256 hash of file bytes stored on Document node
  - Re-ingestion skipped if hash unchanged (idempotent)
  - Hash change → all old DocumentExtract nodes archived, new ones created
"""

from __future__ import annotations
import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

from mcp_engine.graph import embeddings as emb

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".js", ".ts",
    ".json", ".yaml", ".yml", ".toml", ".html", ".css",
    ".csv", ".xlsx", ".tsv", ".xls",  # B250 — tabular data
}

MIME_MAP = {
    ".md":   "text/markdown",
    ".txt":  "text/plain",
    ".rst":  "text/x-rst",
    ".py":   "text/x-python",
    ".js":   "text/javascript",
    ".ts":   "text/typescript",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml":  "application/yaml",
    ".toml": "application/toml",
    ".html": "text/html",
    ".css":  "text/css",
    ".csv": "text/csv",  # B250 — tabular data
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".tsv": "text/tab-separated-values",
    ".xls": "application/vnd.ms-excel",
}

MIN_CHUNK_CHARS = 80    # merge chunks shorter than this with adjacent
MAX_CHUNK_CHARS = 2000  # split chunks larger than this at sentence boundary

# Heading pattern: line starting with 1-6 # chars (Markdown)
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
# Sentence boundary: period/!/? followed by space or end-of-string
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def validate_path(file_path: str, project_root: str | None = None) -> Path:
    """
    Canonicalize and validate a file path for safe ingestion.
    Raises ValueError if path is unsafe or extension not allowed.
    Returns the resolved absolute Path.

    I3 fix: if project_root is provided, the resolved path must be a
    descendant of it — this blocks symlink traversal to files outside the
    allowed directory even after realpath() resolves them.
    """
    resolved = Path(os.path.realpath(file_path))

    # I3 fix: directory confinement check
    if project_root is not None:
        root = Path(os.path.realpath(project_root))
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError(
                f"Path '{resolved}' is outside the allowed directory '{root}'. "
                "Symlink traversal and path escapes are not permitted."
            )

    suffix = resolved.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File extension '{suffix}' is not allowed for ingestion. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    if not resolved.is_file():
        raise ValueError(f"Path is not a regular file: {resolved}")

    return resolved


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_file(path: Path) -> str:
    """SHA256 hex digest of file bytes. Used for change detection."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_document(text: str) -> list[dict]:
    """
    Split document text into semantic chunks suitable for embedding.

    Returns list of:
        {text, byte_start, byte_end, line_start, line_end}

    All offsets are relative to the start of `text` (UTF-8 bytes).

    Algorithm:
      1. Find all split points: blank lines (\\n\\n) and Markdown headings
      2. Split text at those points into raw segments
      3. Merge segments shorter than MIN_CHUNK_CHARS with the next segment
      4. Split segments longer than MAX_CHUNK_CHARS at sentence boundaries
      5. Track byte + line positions throughout
    """
    if not text:
        return []

    # Build split points from paragraph breaks and headings
    split_points = set()
    split_points.add(0)
    split_points.add(len(text))

    # Blank line boundaries
    for m in re.finditer(r"\n\n+", text):
        split_points.add(m.end())

    # Markdown heading boundaries (start of heading line)
    for m in _HEADING_RE.finditer(text):
        split_points.add(m.start())

    ordered = sorted(split_points)

    # Build raw segments
    raw_segments = []
    for i in range(len(ordered) - 1):
        start = ordered[i]
        end   = ordered[i + 1]
        seg   = text[start:end]
        if seg.strip():
            raw_segments.append((start, end, seg))

    # Merge short segments forward
    merged = []
    i = 0
    while i < len(raw_segments):
        start, end, seg = raw_segments[i]
        # Merge forward while combined is still short
        while (len(seg.strip()) < MIN_CHUNK_CHARS
               and i + 1 < len(raw_segments)):
            i += 1
            _, end, next_seg = raw_segments[i]
            seg = seg + next_seg
        merged.append((start, end, seg))
        i += 1

    # Split oversized segments at sentence boundary
    final = []
    for start, end, seg in merged:
        if len(seg) <= MAX_CHUNK_CHARS:
            final.append((start, end, seg))
        else:
            final.extend(_split_oversized(seg, start))

    # Convert to output dicts with byte and line positions
    # Pre-compute cumulative line numbers
    line_starts = _build_line_index(text)

    chunks = []
    for char_start, char_end, seg in final:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue

        # Find stripped byte positions within the segment
        strip_offset = seg.index(seg_stripped[0]) if seg_stripped else 0
        actual_char_start = char_start + strip_offset
        actual_char_end   = actual_char_start + len(seg_stripped)

        byte_start = len(text[:actual_char_start].encode("utf-8"))
        byte_end   = len(text[:actual_char_end].encode("utf-8"))

        line_start = _char_to_line(actual_char_start, line_starts)
        line_end   = _char_to_line(actual_char_end,   line_starts)

        chunks.append({
            "text":       seg_stripped,
            "byte_start": byte_start,
            "byte_end":   byte_end,
            "line_start": line_start,
            "line_end":   line_end,
        })

    return chunks


def _split_oversized(text: str, base_offset: int) -> list[tuple[int, int, str]]:
    """Split a chunk larger than MAX_CHUNK_CHARS at sentence boundaries."""
    result = []
    remaining = text
    offset    = base_offset

    while len(remaining) > MAX_CHUNK_CHARS:
        # Find last sentence end within MAX_CHUNK_CHARS
        window  = remaining[:MAX_CHUNK_CHARS]
        matches = list(_SENTENCE_END_RE.finditer(window))
        if matches:
            cut = matches[-1].end()
        else:
            # I2 fix: rfind returns -1 when no space found; using `or` would
            # evaluate -1 as truthy and slice to second-to-last char, causing
            # an infinite loop if the chunk never shrinks. Explicit -1 check.
            idx = window.rfind(" ", 0, MAX_CHUNK_CHARS)
            cut = idx if idx != -1 else MAX_CHUNK_CHARS

        result.append((offset, offset + cut, remaining[:cut]))
        remaining = remaining[cut:].lstrip()
        offset   += cut

    if remaining.strip():
        result.append((offset, offset + len(remaining), remaining))

    return result


def _build_line_index(text: str) -> list[int]:
    """Return list of character offsets where each line starts."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _char_to_line(char_offset: int, line_starts: list[int]) -> int:
    """Binary search to find 1-based line number for a character offset."""
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= char_offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1  # 1-based


# ---------------------------------------------------------------------------
# Full ingestion pipeline
# ---------------------------------------------------------------------------

async def ingest_document(db, file_path: str, config: dict,
                           loop_queue=None, quest_id: str = "") -> dict:
    """
    Ingest a local file into the graph.

    Returns:
        {document_id, location_uri, chunks_created, already_current,
         skipped_reason?, mime_type}

    Steps:
      1. Validate + canonicalize path
      2. Hash file for change detection
      3. MERGE Document node (idempotent)
      4. If hash unchanged → return already_current=True
      5. Archive old DocumentExtract nodes for this document
      6. Read + chunk file text
      7. For each chunk: embed → CREATE DocumentExtract → DERIVED_FROM
      8. Queue each extract for Gated Consolidation Loop
    """
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    now = datetime.now(timezone.utc).isoformat()

    # Step 1 — Validate path
    try:
        resolved = validate_path(file_path)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e), "location_uri": file_path}

    location_uri = str(resolved)
    mime_type    = MIME_MAP.get(resolved.suffix.lower(), "text/plain")
    title        = resolved.name

    # B250 — Dispatch to tabular ingestion for spreadsheet/CSV files
    TABULAR_EXTENSIONS = {".csv", ".xlsx", ".tsv", ".xls"}
    if resolved.suffix.lower() in TABULAR_EXTENSIONS:
        # Delegate to tabular ingestion pipeline
        from mcp_engine import tabular_ingest
        return await tabular_ingest.ingest_tabular(db, str(resolved), config, loop_queue, quest_id)

    # Step 2 — Hash
    content_hash = hash_file(resolved)

    # Step 3 — MERGE Document node
    document_id = _stable_doc_id(location_uri)
    existing_hash = _get_existing_hash(db, document_id)

    # Step 4 — Skip if unchanged
    if existing_hash == content_hash:
        return {
            "document_id":   document_id,
            "location_uri":  location_uri,
            "chunks_created": 0,
            "already_current": True,
            "mime_type":     mime_type,
        }

    # Create or update Document node
    await _upsert_document(db, document_id, location_uri, title,
                            content_hash, mime_type, now)

    # Step 5 — Archive old extracts if re-ingesting
    if existing_hash is not None:
        await _archive_old_extracts(db, document_id)

    # Step 6 — Read + chunk
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Could not read file: {e}", "document_id": document_id}

    chunks = chunk_document(text)

    if not chunks:
        return {
            "document_id":    document_id,
            "location_uri":   location_uri,
            "chunks_created": 0,
            "already_current": False,
            "mime_type":      mime_type,
        }

    # Step 7 — Embed + store DocumentExtract nodes
    texts   = [c["text"] for c in chunks]
    vectors = emb.embed_batch(texts, model_name=embedding_model)

    chunks_created = 0
    for chunk, vector in zip(chunks, vectors):
        extract_id = str(uuid.uuid4())
        try:
            await db.execute_write(
                """
                CREATE (e:DocumentExtract {
                    extract_id:      $extract_id,
                    text_raw:        $text_raw,
                    embedding:       $embedding,
                    embedding_model: $embedding_model,
                    embedding_dim:   $embedding_dim,
                    byte_start:      $byte_start,
                    byte_end:        $byte_end,
                    line_start:      $line_start,
                    line_end:        $line_end,
                    confidence:      1.0,
                    confidence_low:  false,
                    pathway_strength: 1.0,
                    archived:        false,
                    created_at:      timestamp($created_at)
                })
                """,
                {
                    "extract_id":      extract_id,
                    "text_raw":        chunk["text"],
                    "embedding":       vector,
                    "embedding_model": embedding_model,
                    "embedding_dim":   len(vector),
                    "byte_start":      chunk["byte_start"],
                    "byte_end":        chunk["byte_end"],
                    "line_start":      chunk["line_start"],
                    "line_end":        chunk["line_end"],
                    "created_at":      now,
                }
            )

            # DERIVED_FROM: extract → document
            await db.execute_write(
                """
                MATCH (e:DocumentExtract {extract_id: $eid}),
                      (d:Document {document_id: $did})
                CREATE (e)-[:DERIVED_FROM]->(d)
                """,
                {"eid": extract_id, "did": document_id}
            )
            chunks_created += 1

            # Step 8 — Queue for Gated Consolidation Loop
            if loop_queue is not None:
                # B14: Use 4-tuple (extract_id, text, role, session_id)
                # extracts are always 'user' role; session is 'unknown' as
                # they aren't tied to a specific chat turn.
                await loop_queue.put((extract_id, chunk["text"], "user", "unknown"))

        except Exception:
            continue

    return {
        "document_id":    document_id,
        "location_uri":   location_uri,
        "chunks_created": chunks_created,
        "already_current": False,
        "mime_type":      mime_type,
        "title":          title,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_doc_id(location_uri: str) -> str:
    """Deterministic document_id from location_uri (SHA256, 32 chars)."""
    return hashlib.sha256(location_uri.encode()).hexdigest()[:32]


def _get_existing_hash(db, document_id: str) -> str | None:
    """Return existing content_hash for a Document node, or None if not found."""
    try:
        result = db.execute(
            "MATCH (d:Document {document_id: $did}) RETURN d.content_hash",
            {"did": document_id}
        )
        if result.has_next():
            return result.get_next()[0]
    except Exception:
        pass
    return None


async def _upsert_document(db, document_id: str, location_uri: str, title: str,
                            content_hash: str, mime_type: str, now: str) -> None:
    """Create or update a Document node."""
    try:
        await db.execute_write(
            """
            MERGE (d:Document {document_id: $document_id})
            ON CREATE SET d.location_uri     = $location_uri,
                          d.content_hash     = $content_hash,
                          d.last_modified_at = timestamp($now),
                          d.mime_type        = $mime_type
            ON MATCH SET  d.content_hash     = $content_hash,
                          d.last_modified_at = timestamp($now)
            """,
            {
                "document_id":  document_id,
                "location_uri": location_uri,
                "content_hash": content_hash,
                "now":          now,
                "mime_type":    mime_type,
            }
        )
    except Exception:
        pass


async def _archive_old_extracts(db, document_id: str) -> None:
    """Archive all DocumentExtract nodes for a document before re-ingesting."""
    try:
        await db.execute_write(
            """
            MATCH (e:DocumentExtract)-[:DERIVED_FROM]->(d:Document {document_id: $did})
            SET e.archived = true
            """,
            {"did": document_id}
        )
    except Exception:
        pass
