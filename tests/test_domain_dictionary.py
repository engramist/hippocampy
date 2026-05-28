from __future__ import annotations
import json
import textwrap
from pathlib import Path
import pytest

from campy.brain.temporal_lobe.dictionary import find_dictionary, load_dictionary, ingest_dictionary


def test_load_dictionary_valid(tmp_path):
    sample = textwrap.dedent("""
    version: 1
    entities:
      - term: "Foo"
        alt_labels: ["F", "foo"]
        gist_class: "PhysicalThing"
    """)
    p = tmp_path / "domain_dictionary.yaml"
    p.write_text(sample)

    found = find_dictionary(tmp_path)
    assert found == p

    loaded = load_dictionary(found)
    assert isinstance(loaded, list)
    assert len(loaded) == 1
    ent = loaded[0]
    assert ent["term"] == "Foo"
    assert "F" in ent["alt_labels"]


class FakeDB:
    def __init__(self):
        # map lower-term -> concept_id
        self.concepts = {}
        # map concept_id -> set of alt label texts (lower)
        self.alt_labels = {}
        self.calls = []

    def execute(self, query: str, params: dict | None = None):
        self.calls.append((query, params))
        params = params or {}
        q = query.strip()
        # existence check for concept
        if q.startswith("MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t)"):
            t = params.get("t", "")
            cid = self.concepts.get(t.lower())
            if cid:
                # mimic a list-like row where row["c.concept_id"] exists
                return [{"c.concept_id": cid}]
            return []

        # creation of concept
        if q.startswith("CREATE (c:Concept"):
            cid = params.get("cid")
            txt = params.get("text")
            if cid and txt:
                self.concepts[txt.lower()] = cid
                self.alt_labels[cid] = set()
            return None

        # create label
        if q.startswith("CREATE (l:Label"):
            lid = params.get("lid")
            txt = params.get("txt")
            # return a fake
            return None

        # link pref label
        if q.startswith("MATCH (c:Concept {concept_id: $cid})") and "HAS_PREF_LABEL" in q:
            return None

        # check existing alt label
        if q.startswith("MATCH (c:Concept {concept_id: $cid})-[:HAS_ALT_LABEL]"):
            cid = params.get("cid")
            txt = params.get("txt", "").lower()
            if cid in self.alt_labels and txt in self.alt_labels[cid]:
                return [{"l.label_id": "exists"}]
            return []

        # create alt label
        if q.startswith("CREATE (l:Label"):
            return None

        # link alt label
        if q.startswith("MATCH (c:Concept {concept_id: $cid}), (l:Label {label_id: $lid})"):
            cid = params.get("cid")
            txt = None
            # best-effort: try to extract last create call
            # we can't reliably know alt text here, so skip
            return None

        return None


@pytest.mark.asyncio
async def test_ingest_dictionary_idempotent(monkeypatch, tmp_path):
    sample = textwrap.dedent("""
    version: 1
    entities:
      - term: "Foo"
        alt_labels: ["F"]
    """)
    p = tmp_path / "domain_dictionary.yaml"
    p.write_text(sample)

    loaded = load_dictionary(p)
    assert len(loaded) == 1

    # patch embed to deterministic vector
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda x, model_name=None: [0.0])

    db = FakeDB()

    # First ingest: should create concept and alt label
    result1 = await ingest_dictionary(loaded, db, "2026-04-04T00:00:00Z")
    assert result1["concepts_created"] == 1
    assert result1["concepts_skipped"] == 0
    assert result1["alt_labels_added"] == 1

    # Second ingest: should find existing concept and skip create, and skip alt label
    result2 = await ingest_dictionary(loaded, db, "2026-04-04T00:00:01Z")
    assert result2["concepts_created"] == 0
    # It should count as skipped because existing concept was found
    assert result2["concepts_skipped"] == 1
