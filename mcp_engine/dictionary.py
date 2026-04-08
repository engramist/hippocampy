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
