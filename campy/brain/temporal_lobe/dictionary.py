from __future__ import annotations

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

from campy.brain.hippocampus.graph.embeddings import embed
from campy.brain.hippocampus.graph.gateway import get_gateway

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
    gw = get_gateway(db)
    created = 0
    labels_added = 0
    skipped = 0

    for entry in entities:
        term = entry["term"]

        # Check for existing concept (exact match, case-insensitive)
        existing = await gw.run("temporal_lobe.dict_find_concept", t=term)

        if existing:
            row = existing[0]
            concept_id = row.get("c.concept_id", row.get("concept_id")) if isinstance(row, dict) else row[0]
            skipped += 1
        else:
            # Create new concept
            concept_id = str(uuid.uuid4())
            embedding = embed(term)

            await gw.run(
                "temporal_lobe.dict_create_concept",
                cid=concept_id,
                text=term,
                emb=embedding,
                gist=entry.get("gist_class"),
                stype=entry.get("schema_org_type"),
                now=now,
            )

            # Create prefLabel
            pref_label_id = str(uuid.uuid4())
            pref_emb = embedding  # Same embedding as concept
            await gw.run(
                "temporal_lobe.dict_create_pref_label",
                lid=pref_label_id,
                txt=term,
                emb=pref_emb,
                now=now,
            )
            await gw.run(
                "temporal_lobe.dict_link_pref_label",
                cid=concept_id,
                lid=pref_label_id,
                now=now,
            )
            created += 1

        # Add altLabels (even for existing concepts — may have new synonyms)
        for alt_text in entry["alt_labels"]:
            # Check if this altLabel already exists for this concept
            existing_label = await gw.run(
                "temporal_lobe.dict_find_alt_label",
                cid=concept_id,
                txt=alt_text,
            )
            if existing_label:
                continue

            alt_label_id = str(uuid.uuid4())
            alt_emb = embed(alt_text)
            await gw.run(
                "temporal_lobe.dict_create_alt_label",
                lid=alt_label_id,
                txt=alt_text,
                emb=alt_emb,
                now=now,
            )
            await gw.run(
                "temporal_lobe.dict_link_alt_label",
                cid=concept_id,
                lid=alt_label_id,
                now=now,
            )
            labels_added += 1

    return {
        "concepts_created": created,
        "concepts_skipped": skipped,
        "alt_labels_added": labels_added,
        "total_entities": len(entities),
    }
