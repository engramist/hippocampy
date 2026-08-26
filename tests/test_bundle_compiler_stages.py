"""
tests/test_bundle_compiler_stages.py — Real-Kuzu regression tests for
_stage_exact_facts / _stage_semantic_context (B306), _stage_graph_structure,
_stage_tabular_data, and _stage_summaries (B252).

Unlike the mocked tests in test_bundle_compiler.py, these run the stages'
raw Cypher against a real Kuzu database. Mocking db.execute() never
exercises the actual query text, so a Cypher syntax bug in these two
stages was previously invisible: it was thrown, caught by a bare
`except Exception`, and silently turned into "no content" on every call.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid

import pytest

from campy.paths import tables_dir
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.thalamus.bundle_compiler import (
    _stage_exact_facts,
    _stage_graph_structure,
    _stage_semantic_context,
    _stage_summaries,
    _stage_tabular_data,
)

FAKE_DIM = 4
FAKE_EMBEDDING_MODEL = "fake-test-model"
CONFIG = {"embeddings": {"model": FAKE_EMBEDDING_MODEL}}
TIER_CONFIG = {"max_semantic": 10}


def _fake_embed(text: str, model_name: str = FAKE_EMBEDDING_MODEL) -> list[float]:
    """Deterministic stand-in for the real sentence-transformers model."""
    return [1.0, 0.0, 0.0, 0.0] if text == "query" else [0.0, 1.0, 0.0, 0.0]


@pytest.fixture()
def real_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="bundle_stage_")
    db = KuzuClient(f"{tmp}/db")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed", _fake_embed
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


class TestStageExactFacts:
    def _create_tables(self, db: KuzuClient) -> None:
        db.execute(
            "CREATE NODE TABLE GlobalConstraint("
            "id STRING, text_raw STRING, confidence DOUBLE, flagged_for_review BOOLEAN, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
        )
        db.execute(
            "CREATE NODE TABLE GlobalPreference("
            "id STRING, text_raw STRING, confidence DOUBLE, flagged_for_review BOOLEAN, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
        )

    async def test_returns_matching_facts_across_both_labels(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'never delete prod', "
            "confidence: 0.9, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:GlobalPreference {id: 'gp1', text_raw: 'prefers terse replies', "
            "confidence: 0.8, embedding: $emb})",
            {"emb": [0.98, 0.02, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:GlobalPreference {id: 'gp2', text_raw: 'unrelated far fact', "
            "confidence: 0.8, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert section.section_type == "exact_fact"
        texts = {c["text"] for c in section.content}
        types = {c["type"] for c in section.content}
        assert texts == {"never delete prod", "prefers terse replies"}
        assert types == {"GlobalConstraint", "GlobalPreference"}

    async def test_returns_none_when_nothing_matches(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'unrelated', "
            "confidence: 0.9, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is None

    async def test_excludes_nodes_flagged_for_review(self, real_db):
        """B339 follow-up: anomaly_detection.py flags nodes as
        flagged_for_review but nothing previously consulted that flag at
        recall time — a flagged node still matched into the prompt fed to
        an LLM via ask.py. Verify flagged nodes are now excluded."""
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'flagged content', "
            "confidence: 0.9, flagged_for_review: true, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:GlobalPreference {id: 'gp1', text_raw: 'clean content', "
            "confidence: 0.8, flagged_for_review: false, embedding: $emb})",
            {"emb": [0.98, 0.02, 0.0, 0.0]},
        )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        texts = {c["text"] for c in section.content}
        assert texts == {"clean content"}

    async def test_limit_applies_across_both_labels_combined(self, real_db):
        """Regression guard: a naive `UNION ... LIMIT 10` in Kuzu 0.11.3 only
        limits the last branch, not the combined result across both labels."""
        db = real_db
        self._create_tables(db)
        for i in range(8):
            db.execute(
                f"CREATE (n:GlobalConstraint {{id: 'gc{i}', text_raw: 'gc match {i}', "
                "confidence: 0.9, embedding: $emb})",
                {"emb": [0.99, 0.01, 0.0, 0.0]},
            )
        for i in range(8):
            db.execute(
                f"CREATE (n:GlobalPreference {{id: 'gp{i}', text_raw: 'gp match {i}', "
                "confidence: 0.8, embedding: $emb})",
                {"emb": [0.98, 0.02, 0.0, 0.0]},
            )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert len(section.content) == 10


class TestStageSemanticContext:
    def _create_tables(self, db: KuzuClient) -> None:
        for table in ("Concept", "Decision", "Constraint", "Requirement"):
            db.execute(
                f"CREATE NODE TABLE {table}("
                "id STRING, text_raw STRING, confidence DOUBLE, flagged_for_review BOOLEAN, "
                f"pathway_strength DOUBLE, embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
            )

    async def test_returns_matching_content_across_labels(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'concept close', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:Decision {id: 'd1', text_raw: 'decision close', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.97, 0.03, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:Requirement {id: 'r1', text_raw: 'requirement far', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert section.section_type == "semantic"
        texts = {c["text"] for c in section.content}
        assert texts == {"concept close", "decision close"}
        assert "requirement far" not in texts

    async def test_respects_limit_across_unioned_labels(self, real_db):
        """Regression guard: a naive `UNION ... ORDER BY ... LIMIT` in Kuzu 0.11.3
        only orders/limits the last branch, not the globally closest matches
        across all four labels."""
        db = real_db
        self._create_tables(db)
        # Closest match is in the FIRST branch (Concept), not the last
        # (Requirement) - this only passes if the cap is applied globally.
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'closest match', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [1.0, 0.0, 0.0, 0.0]},
        )
        for table in ("Decision", "Constraint", "Requirement"):
            db.execute(
                f"CREATE (n:{table} {{id: '{table.lower()}1', text_raw: '{table} match', "
                "confidence: 0.9, pathway_strength: 0.6, embedding: $emb})",
                {"emb": [0.99, 0.01, 0.0, 0.0]},
            )

        section = await _stage_semantic_context(db, "query", CONFIG, {"max_semantic": 1})

        assert section is not None
        assert len(section.content) == 1
        assert section.content[0]["text"] == "closest match"

    async def test_returns_none_when_nothing_matches(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'unrelated', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is None

    async def test_excludes_nodes_flagged_for_review(self, real_db):
        """VibeGuide round-3 verification, Finding 4: the exact-fact stage
        had this exclusion tested (test_excludes_nodes_flagged_for_review in
        TestStageExactFacts) but semantic and graph stages only had the
        flagged_for_review column added to their fixtures, never a
        flagged=true node actually created -- two of the three exclusions
        were implemented but unproven, the same gap-shape ("the flag
        existed; nothing consulted it") this whole review round was about."""
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'flagged concept', confidence: 0.9, "
            "flagged_for_review: true, pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:Decision {id: 'd1', text_raw: 'clean decision', confidence: 0.9, "
            "flagged_for_review: false, pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.97, 0.03, 0.0, 0.0]},
        )

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        texts = {c["text"] for c in section.content}
        assert texts == {"clean decision"}


class TestStageGraphStructure:
    """B252: _stage_graph_structure was a literal placeholder (`content=[]`
    unconditionally) — never queried the graph at all. These tests exercise
    the real 1-2 hop Concept<->Concept traversal against a real Kuzu DB.

    Concept is the schema's only node type with a rich set of peer-to-peer
    relationships (REQUIRES, ENABLES, etc. are all Concept->Concept) — see
    backlog/B252.md audit findings. The traversal deliberately issues one
    MATCH per anchor node rather than a UNION across differently-typed node
    tables: Kuzu 0.11.3's binder rejects that (see B280's "Binder exception:
    a has data type NODE but NODE was expected").
    """

    def _create_tables(self, db: KuzuClient) -> None:
        # concept_id (not generic "id") to match the real production schema
        # (campy/brain/hippocampus/schema.py) - _stage_graph_structure's
        # Cypher references this column name explicitly.
        db.execute(
            "CREATE NODE TABLE Concept("
            "concept_id STRING, text_raw STRING, flagged_for_review BOOLEAN, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (concept_id))"
        )
        # All rel types in _GRAPH_REL_TYPES must exist as tables - Kuzu's
        # multi-type pattern `[r:TYPE1|TYPE2|...]` requires every listed type
        # to be a real relationship table, even ones with no rows.
        for rel in (
            "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
            "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
        ):
            db.execute(f"CREATE REL TABLE {rel}(FROM Concept TO Concept, confidence DOUBLE)")

    def _concept(self, db: KuzuClient, cid: str, text: str, emb: list[float]) -> None:
        db.execute(
            "CREATE (n:Concept {concept_id: $id, text_raw: $t, embedding: $e})",
            {"id": cid, "t": text, "e": emb},
        )

    def _edge(self, db: KuzuClient, rel: str, a: str, b: str) -> None:
        db.execute(
            f"MATCH (a:Concept {{concept_id: $a}}), (b:Concept {{concept_id: $b}}) "
            f"CREATE (a)-[:{rel} {{confidence: 0.9}}]->(b)",
            {"a": a, "b": b},
        )

    async def test_returns_neighbor_structure_for_matching_anchor(self, real_db):
        db = real_db
        self._create_tables(db)
        self._concept(db, "a", "concept a", [0.99, 0.01, 0.0, 0.0])  # close to "query"
        self._concept(db, "b", "concept b", [0.0, 0.0, 1.0, 0.0])
        self._edge(db, "REQUIRES", "a", "b")

        section = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 1}, [])

        assert section is not None
        assert section.section_type == "graph"
        assert len(section.content) == 1
        edge = section.content[0]
        assert edge["from"] == "concept a"
        assert edge["to"] == "concept b"
        assert edge["relationship"] == "REQUIRES"

    async def test_returns_none_when_no_anchor_matches_query(self, real_db):
        db = real_db
        self._create_tables(db)
        self._concept(db, "a", "unrelated", [0.0, 0.0, 1.0, 0.0])  # far from "query"
        self._concept(db, "b", "also unrelated", [0.0, 1.0, 0.0, 0.0])
        self._edge(db, "REQUIRES", "a", "b")

        section = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 1}, [])

        assert section is None

    async def test_returns_none_when_anchor_is_isolated(self, real_db):
        db = real_db
        self._create_tables(db)
        self._concept(db, "a", "lonely concept", [0.99, 0.01, 0.0, 0.0])

        section = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 1}, [])

        assert section is None

    async def test_two_hop_tier_reaches_second_degree_neighbor(self, real_db):
        db = real_db
        self._create_tables(db)
        self._concept(db, "a", "concept a", [0.99, 0.01, 0.0, 0.0])
        self._concept(db, "b", "concept b", [0.0, 0.0, 1.0, 0.0])
        self._concept(db, "c", "concept c", [0.0, 1.0, 0.0, 0.0])
        self._edge(db, "REQUIRES", "a", "b")
        self._edge(db, "ENABLES", "b", "c")

        one_hop = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 1}, [])
        two_hop = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 2}, [])

        one_hop_targets = {e["to"] for e in one_hop.content}
        two_hop_targets = {e["to"] for e in two_hop.content}
        assert one_hop_targets == {"concept b"}
        assert "concept c" in two_hop_targets

    async def test_excludes_flagged_neighbor_from_one_hop(self, real_db):
        """VibeGuide round-3 verification, Finding 4: same exclusion gap as
        TestStageSemanticContext.test_excludes_nodes_flagged_for_review,
        for the graph-traversal stage specifically -- a flagged one-hop
        neighbor must not be surfaced, matching the `b.flagged_for_review`
        filter bundle_compiler.py's one_hop_cypher actually applies."""
        db = real_db
        self._create_tables(db)
        self._concept(db, "a", "concept a", [0.99, 0.01, 0.0, 0.0])
        self._concept(db, "b", "flagged concept b", [0.0, 0.0, 1.0, 0.0])
        self._concept(db, "c", "clean concept c", [0.0, 1.0, 0.0, 0.0])
        db.execute(
            "MATCH (n:Concept {concept_id: 'b'}) SET n.flagged_for_review = true"
        )
        self._edge(db, "REQUIRES", "a", "b")
        self._edge(db, "ENABLES", "a", "c")

        section = await _stage_graph_structure(db, "query", CONFIG, {"max_graph_hops": 1}, [])

        assert section is not None
        targets = {e["to"] for e in section.content}
        assert targets == {"clean concept c"}


class TestStageTabularData:
    """B252: _stage_tabular_data was a literal placeholder (`content=[]`
    unconditionally) — never checked DESCRIBED_BY_DATASET edges or called
    tabular_store.get_table_summary(). These tests exercise the real
    Concept->Dataset traversal plus a real SQLite-backed dataset.

    B250's audit found nothing currently creates a DESCRIBED_BY_DATASET
    edge in production, so this stage returns None on every real query
    today — these tests create the edge directly to exercise the Cypher
    and SQLite lookup that will start firing once B250 lands.
    """

    def _create_tables(self, db: KuzuClient) -> None:
        db.execute(
            "CREATE NODE TABLE Concept("
            "concept_id STRING, text_raw STRING, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (concept_id))"
        )
        db.execute(
            "CREATE NODE TABLE Dataset("
            "dataset_id STRING, name STRING, description STRING, "
            "archived BOOLEAN, PRIMARY KEY (dataset_id))"
        )
        db.execute("CREATE REL TABLE DESCRIBED_BY_DATASET(FROM Concept TO Dataset)")

    def _concept(self, db: KuzuClient, cid: str, text: str, emb: list[float]) -> None:
        db.execute(
            "CREATE (n:Concept {concept_id: $id, text_raw: $t, embedding: $e})",
            {"id": cid, "t": text, "e": emb},
        )

    def _dataset(self, db: KuzuClient, did: str, name: str, archived: bool = False) -> None:
        db.execute(
            "CREATE (d:Dataset {dataset_id: $id, name: $n, description: $descr, "
            "archived: $archived})",
            {"id": did, "n": name, "descr": f"description for {name}", "archived": archived},
        )

    def _link(self, db: KuzuClient, cid: str, did: str) -> None:
        db.execute(
            "MATCH (c:Concept {concept_id: $c}), (d:Dataset {dataset_id: $d}) "
            "CREATE (c)-[:DESCRIBED_BY_DATASET]->(d)",
            {"c": cid, "d": did},
        )

    @pytest.fixture()
    def pandas(self):
        pytest.importorskip("pandas")
        import pandas as pd
        return pd

    @pytest.fixture(autouse=True)
    def cleanup_sqlite(self):
        yield
        tables_path = tables_dir()
        if tables_path.exists():
            for db_file in tables_path.glob("bundletest_*.sqlite"):
                db_file.unlink(missing_ok=True)

    def _write_sqlite(self, pandas, dataset_id: str, rows: int = 3) -> None:
        from campy.brain.sensory_cortex.tabular_store import create_table_from_dataframe

        df = pandas.DataFrame({"col_a": list(range(rows)), "col_b": [f"v{i}" for i in range(rows)]})
        create_table_from_dataframe(dataset_id, df, '{"columns": ["col_a", "col_b"]}')

    async def test_returns_none_when_no_dataset_linked(self, real_db):
        db = real_db
        self._create_tables(db)
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])

        section = await _stage_tabular_data(db, "query", CONFIG, {"include_raw_tabular": False}, [], 10000)

        assert section is None

    async def test_returns_none_when_anchor_does_not_match_query(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "unrelated", [0.0, 0.0, 1.0, 0.0])
        self._dataset(db, did, "far dataset")
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did)

        section = await _stage_tabular_data(db, "query", CONFIG, {"include_raw_tabular": False}, [], 10000)

        assert section is None

    async def test_returns_none_when_remaining_budget_is_zero(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])
        self._dataset(db, did, "close dataset")
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did)

        section = await _stage_tabular_data(db, "query", CONFIG, {"include_raw_tabular": False}, [], 0)

        assert section is None

    async def test_includes_dataset_summary_for_matching_concept(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])
        self._dataset(db, did, "close dataset")
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did, rows=3)

        section = await _stage_tabular_data(
            db, "query", CONFIG, {"include_raw_tabular": False}, [], 10000
        )

        assert section is not None
        assert section.section_type == "tabular"
        assert len(section.content) == 1
        entry = section.content[0]
        assert entry["dataset_id"] == did
        assert entry["name"] == "close dataset"
        assert entry["row_count"] == 3
        assert {c["name"] for c in entry["columns"]} == {"col_a", "col_b"}
        assert did in section.source_node_ids

    async def test_excludes_sample_rows_when_tier_disallows_raw(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])
        self._dataset(db, did, "close dataset")
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did, rows=3)

        section = await _stage_tabular_data(
            db, "query", CONFIG, {"include_raw_tabular": False}, [], 10000
        )

        assert "sample_rows" not in section.content[0]

    async def test_includes_sample_rows_when_tier_allows_raw(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])
        self._dataset(db, did, "close dataset")
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did, rows=3)

        section = await _stage_tabular_data(
            db,
            "query",
            CONFIG,
            {"include_raw_tabular": True, "max_tabular_rows": 20},
            [],
            10000,
        )

        assert "sample_rows" in section.content[0]
        assert len(section.content[0]["sample_rows"]) == 3

    async def test_excludes_archived_dataset(self, real_db, pandas):
        db = real_db
        self._create_tables(db)
        did = f"bundletest_{uuid.uuid4().hex[:8]}"
        self._concept(db, "c1", "concept close", [0.99, 0.01, 0.0, 0.0])
        self._dataset(db, did, "archived dataset", archived=True)
        self._link(db, "c1", did)
        self._write_sqlite(pandas, did)

        section = await _stage_tabular_data(db, "query", CONFIG, {"include_raw_tabular": False}, [], 10000)

        assert section is None


class TestStageSummaries:
    """B252: _stage_summaries was a literal placeholder (`content=[]`
    unconditionally) — never queried Lesson/Procedure nodes. These are the
    same node types the wiki projection (wiki_projection.py) renders into
    persona pages; querying them live by embedding similarity surfaces the
    same underlying content without depending on the wiki export sweep
    having run (it's disabled by default).
    """

    def _create_tables(self, db: KuzuClient) -> None:
        db.execute(
            "CREATE NODE TABLE Lesson("
            "lesson_id STRING, text_raw STRING, lesson_type STRING, "
            f"archived BOOLEAN, embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (lesson_id))"
        )
        db.execute(
            "CREATE NODE TABLE Procedure("
            "procedure_id STRING, description STRING, "
            f"archived BOOLEAN, embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (procedure_id))"
        )

    def _lesson(self, db, lid, text, emb, lesson_type="synthesis", archived=False):
        db.execute(
            "CREATE (n:Lesson {lesson_id: $id, text_raw: $t, lesson_type: $lt, "
            "archived: $a, embedding: $e})",
            {"id": lid, "t": text, "lt": lesson_type, "a": archived, "e": emb},
        )

    def _procedure(self, db, pid, desc, emb, archived=False):
        db.execute(
            "CREATE (n:Procedure {procedure_id: $id, description: $d, "
            "archived: $a, embedding: $e})",
            {"id": pid, "d": desc, "a": archived, "e": emb},
        )

    async def test_returns_none_when_nothing_matches(self, real_db):
        db = real_db
        self._create_tables(db)
        self._lesson(db, "l1", "unrelated lesson", [0.0, 0.0, 1.0, 0.0])

        section = await _stage_summaries(db, "query", CONFIG, [], 10000)

        assert section is None

    async def test_returns_none_when_remaining_budget_is_zero(self, real_db):
        db = real_db
        self._create_tables(db)
        self._lesson(db, "l1", "close lesson", [0.99, 0.01, 0.0, 0.0])

        section = await _stage_summaries(db, "query", CONFIG, [], 0)

        assert section is None

    async def test_includes_matching_lesson_and_procedure(self, real_db):
        db = real_db
        self._create_tables(db)
        self._lesson(db, "l1", "close lesson", [0.99, 0.01, 0.0, 0.0])
        self._procedure(db, "p1", "close procedure", [0.97, 0.03, 0.0, 0.0])

        section = await _stage_summaries(db, "query", CONFIG, [], 10000)

        assert section is not None
        assert section.section_type == "summary"
        summaries = {c["summary"] for c in section.content}
        assert summaries == {"close lesson", "close procedure"}
        assert {"l1", "p1"} == set(section.source_node_ids)

    async def test_excludes_archived_lesson(self, real_db):
        db = real_db
        self._create_tables(db)
        self._lesson(db, "l1", "archived lesson", [0.99, 0.01, 0.0, 0.0], archived=True)

        section = await _stage_summaries(db, "query", CONFIG, [], 10000)

        assert section is None

    async def test_excludes_non_synthesis_lesson(self, real_db):
        db = real_db
        self._create_tables(db)
        self._lesson(db, "l1", "raw lesson", [0.99, 0.01, 0.0, 0.0], lesson_type="raw")

        section = await _stage_summaries(db, "query", CONFIG, [], 10000)

        assert section is None
