# Plan for B160 — Domain Dictionary Pre-Seed: Cold-Start Thesaurus for Power Users

## Card Metadata

- **Card ID**: B160
- **Priority**: P3
- **Dependencies**: None

## Summary

Allow power users to drop a `domain_dictionary.yaml` file into their workspace, pre-seeding the knowledge graph with canonical entities and their synonyms (altLabels). This gives the entity resolution pipeline a cold-start advantage — common abbreviations and domain terms are recognized from turn 1.

## Technical Approach

### 1. Create `mcp_engine/dictionary.py`

```python
"""
B160: Domain Dictionary Pre-Seed

Loads a YAML domain dictionary and ingests canonical entities + altLabels
into the Kùzu graph. Idempotent — re-running with the same dictionary
does not create duplicates.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

import yaml

from mcp_engine.graph.embeddings import embed

_logger = logging.getLogger(__name__)

DICTIONARY_PATHS = [
    ".sidequests/domain_dictionary.yaml",
    ".sidequests/domain_dictionary.yml",
    "domain_dictionary.yaml",
    "domain_dictionary.yml",
]

VALID_GIST_CLASSES = {
    "Restriction", "PlannedEvent", "PhysicalThing",
    "Magnitude", "Category", "Agent", "Event",
}


def find_dictionary(workspace_root: str | Path) -> Path | None:
    """Find the domain dictionary file in the workspace."""
    root = Path(workspace_root)
    for relpath in DICTIONARY_PATHS:
        candidate = root / relpath
        if candidate.exists():
            return candidate
    return None


def load_dictionary(path: Path) -> list[dict[str, Any]]:
    """Parse and validate the domain dictionary YAML."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "entities" not in data:
        _logger.warning("B160: Invalid dictionary format — expected 'entities' key")
        return []

    version = data.get("version", 1)
    if version != 1:
        _logger.warning("B160: Unknown dictionary version %s", version)

    entities = data.get("entities", [])
    if not isinstance(entities, list):
        _logger.warning("B160: 'entities' must be a list")
        return []

    # Validate
    seen_terms = set()
    valid = []
    for i, entry in enumerate(entities):
        if not isinstance(entry, dict) or "term" not in entry:
            _logger.warning("B160: Entry %d missing 'term' — skipping", i)
            continue

        term = entry["term"].strip()
        if not term:
            continue

        if term.lower() in seen_terms:
            _logger.warning("B160: Duplicate term '%s' — skipping", term)
            continue
        seen_terms.add(term.lower())

        gist_class = entry.get("gist_class")
        if gist_class and gist_class not in VALID_GIST_CLASSES:
            _logger.warning(
                "B160: Unknown gist_class '%s' for '%s' — will use None",
                gist_class, term
            )
            gist_class = None

        alt_labels = entry.get("alt_labels", [])
        if not isinstance(alt_labels, list):
            alt_labels = [str(alt_labels)]

        valid.append({
            "term": term,
            "alt_labels": [str(a).strip() for a in alt_labels if str(a).strip()],
            "gist_class": gist_class,
            "schema_org_type": entry.get("schema_org_type"),
        })

    _logger.info("B160: Loaded %d valid entities from dictionary", len(valid))
    return valid


async def ingest_dictionary(entities: list[dict], db, now) -> dict:
    """Ingest dictionary entities into the graph. Idempotent."""
    created = 0
    labels_added = 0
    skipped = 0

    for entry in entities:
        term = entry["term"]

        # Check for existing concept (exact match, case-insensitive)
        existing = db.execute(
            "MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) "
            "AND c.archived = false "
            "RETURN c.concept_id LIMIT 1",
            {"t": term}
        )

        if existing:
            concept_id = existing[0]["c.concept_id"]
            skipped += 1
        else:
            # Create new concept
            concept_id = str(uuid.uuid4())
            embedding = embed(term)

            db.execute(
                "CREATE (c:Concept {"
                "  concept_id: $cid, text_raw: $text, embedding: $emb,"
                "  embedding_model: 'sentence-transformers/all-MiniLM-L6-v2',"
                "  embedding_dim: 384,"
                "  gist_class: $gist, schema_org_type: $stype,"
                "  confidence: 0.95, confidence_low: false,"
                "  pathway_strength: 0.80, archived: false,"
                "  anomaly_type: null, flagged_for_review: false,"
                "  created_at: $now, last_accessed_at: $now"
                "})",
                {
                    "cid": concept_id, "text": term, "emb": embedding,
                    "gist": entry.get("gist_class"),
                    "stype": entry.get("schema_org_type"),
                    "now": now,
                }
            )

            # Create prefLabel
            pref_label_id = str(uuid.uuid4())
            pref_emb = embedding  # Same embedding as concept
            db.execute(
                "CREATE (l:Label {"
                "  label_id: $lid, text: $txt, embedding: $emb,"
                "  language: 'en', label_type: 'preferred',"
                "  confidence: 0.95, source: 'domain_dictionary',"
                "  created_at: $now"
                "})",
                {"lid": pref_label_id, "txt": term, "emb": pref_emb, "now": now}
            )
            db.execute(
                "MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
                "CREATE (c)-[:HAS_PREF_LABEL {created_at: $now}]->(l)",
                {"cid": concept_id, "lid": pref_label_id, "now": now}
            )
            created += 1

        # Add altLabels (even for existing concepts — may have new synonyms)
        for alt_text in entry["alt_labels"]:
            # Check if this altLabel already exists for this concept
            existing_label = db.execute(
                "MATCH (c:Concept {concept_id: $cid})-[:HAS_ALT_LABEL]->(l:Label) "
                "WHERE toLower(l.text) = toLower($txt) "
                "RETURN l.label_id LIMIT 1",
                {"cid": concept_id, "txt": alt_text}
            )
            if existing_label:
                continue

            alt_label_id = str(uuid.uuid4())
            alt_emb = embed(alt_text)
            db.execute(
                "CREATE (l:Label {"
                "  label_id: $lid, text: $txt, embedding: $emb,"
                "  language: 'en', label_type: 'alternative',"
                "  confidence: 0.90, source: 'domain_dictionary',"
                "  created_at: $now"
                "})",
                {"lid": alt_label_id, "txt": alt_text, "emb": alt_emb, "now": now}
            )
            db.execute(
                "MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid}) "
                "CREATE (c)-[:HAS_ALT_LABEL {created_at: $now}]->(l)",
                {"cid": concept_id, "lid": alt_label_id, "now": now}
            )
            labels_added += 1

    return {
        "concepts_created": created,
        "concepts_skipped": skipped,
        "alt_labels_added": labels_added,
        "total_entities": len(entities),
    }
```

### 2. Call on daemon startup

In the daemon startup path (wherever the Brain initializes):

```python
from mcp_engine.dictionary import find_dictionary, load_dictionary, ingest_dictionary

# After schema is ensured and DB is ready:
dict_path = find_dictionary(workspace_root)
if dict_path:
    entities = load_dictionary(dict_path)
    if entities:
        result = await ingest_dictionary(entities, db, now)
        _logger.info(
            "B160: Domain dictionary ingested: %d created, %d skipped, %d altLabels",
            result["concepts_created"], result["concepts_skipped"],
            result["alt_labels_added"]
        )
```

### 3. `reload_domain_dictionary` MCP tool

```python
async def reload_domain_dictionary(arguments, db, **kwargs):
    """Reload the domain dictionary from disk. Adds new entities and altLabels."""
    workspace_root = arguments.get("workspace_root", ".")
    dict_path = find_dictionary(workspace_root)
    if not dict_path:
        return {"error": "No domain_dictionary.yaml found", "searched": DICTIONARY_PATHS}

    entities = load_dictionary(dict_path)
    if not entities:
        return {"error": "Dictionary is empty or invalid"}

    result = await ingest_dictionary(entities, db, _now())
    return {
        "status": "ok",
        "path": str(dict_path),
        **result,
    }
```

Tool schema:
```python
{
    "name": "reload_domain_dictionary",
    "description": "Reload the domain dictionary from .sidequests/domain_dictionary.yaml. Adds new entities and altLabels without duplicating existing ones.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "workspace_root": {"type": "string", "description": "Workspace root path", "default": "."}
        }
    }
}
```

### 4. Example dictionary file

Create `docs/domain_dictionary_example.yaml` as documentation:

```yaml
# Domain Dictionary for SideQuests Brain
# Place this file at .sidequests/domain_dictionary.yaml in your workspace root.
#
# Each entity gets a high-confidence Concept node with prefLabel and altLabels.
# The Brain Daemon loads this on startup and on `reload_domain_dictionary`.
#
# Fields:
#   term (required): Canonical name for the entity
#   alt_labels (optional): List of synonyms, abbreviations, acronyms
#   gist_class (optional): One of: Restriction, PlannedEvent, PhysicalThing,
#                           Magnitude, Category, Agent, Event
#   schema_org_type (optional): schema.org type for routing

version: 1
entities:
  - term: "PostgreSQL"
    alt_labels: ["Postgres", "PG", "pg"]
    gist_class: "PhysicalThing"
    schema_org_type: "schema:Product"

  - term: "Kubernetes"
    alt_labels: ["k8s", "K8s", "kube"]
    gist_class: "PhysicalThing"

  - term: "React"
    alt_labels: ["ReactJS", "React.js"]
    gist_class: "PhysicalThing"
```

## Concrete File Changes

| File | Change |
|------|--------|
| `mcp_engine/dictionary.py` | NEW: `find_dictionary()`, `load_dictionary()`, `ingest_dictionary()` |
| `mcp_engine/daemon.py` (or startup path) | Call `load_domain_dictionary()` after schema init |
| `mcp_engine/tools/__init__.py` | Add `reload_domain_dictionary` handler |
| `mcp_engine/tool_schemas.py` | Add tool schema |
| `docs/tool-catalog.md` | Document the new tool |
| `docs/domain_dictionary_example.yaml` | NEW: example dictionary with documentation |
| `tests/test_domain_dictionary.py` | NEW: test YAML parsing, validation, ingestion, dedup, altLabel wiring |
| Adapter allow-lists | Propagate new tool |

## API/Schema/Test Updates

- One new MCP tool: `reload_domain_dictionary`
- No schema changes (uses existing Concept + Label nodes)
- Adapter allow-lists must include the new tool
- `docs/tool-catalog.md` must document the tool

## Validation Commands

```bash
python3 -m pytest tests/test_domain_dictionary.py -v
python3 -m pytest tests/test_adapters.py -q
rg -n "TOOL_HANDLERS|TOOLS:" mcp_engine/tool_schemas.py mcp_engine/tools/__init__.py adapters/
```

## Risks / Constraints

- **YAML dependency**: `pyyaml` is likely already a dependency. Verify before adding.
- **Embedding cost on startup**: Each entity + altLabels requires embedding computation. A 100-entity dictionary with 3 altLabels each = 400 embed calls. With all-MiniLM-L6-v2 locally, this takes ~5-10 seconds. Acceptable for startup, but log progress for large dictionaries.
- **Over-seeding**: A very large dictionary (1000+ entities) could flood the graph with concepts that never appear in conversation. These will decay naturally via the background sweep, but initial graph size may affect retrieval performance. Recommend dictionary size of 50-200 entities.
- **No deletion**: Removing an entity from the dictionary does NOT delete it from the graph. The graph is additive. If a user needs to remove a pre-seeded entity, they must archive it via the Memory Control Panel or a future tool.

## Done When

- Dictionary YAML format validated on load
- Entities ingested as high-confidence Concepts with prefLabel + altLabels
- All labels embedded and searchable from turn 1
- Idempotent: re-running doesn't create duplicates
- `reload_domain_dictionary` tool works
- Example dictionary documented
- New tool in adapter allow-lists and tool-catalog.md
- All tests pass
