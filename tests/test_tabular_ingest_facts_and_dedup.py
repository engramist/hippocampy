"""
tests/test_tabular_ingest_facts_and_dedup.py — Real-Kuzu regression tests for B250.

The 2026-08-03 audit found four of this card's checked-off acceptance
criteria were never actually implemented: LLM summary generation, key-fact
extraction into Concept nodes, change-detection (already_current), and
archive-on-change for re-uploads. These tests exercise the real fix
against a real Kuzu DB - no db.execute mocking - since tests/test_tabular_
ingest.py's 100% mock-based suite is exactly what let the gap go
undetected in the first place.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.sensory_cortex import tabular_ingest
from campy.paths import tables_dir

pytest.importorskip("pandas")

CONFIG = {
    "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
    "tabular": {"multi_sheet_strategy": "per_sheet"},
}

_DATASET_DDL = """
    dataset_id STRING,
    name STRING,
    description STRING,
    embedding FLOAT[384],
    embedding_model STRING,
    embedding_dim INT32,
    storage_uri STRING,
    schema_json STRING,
    row_count INT64,
    column_count INT32,
    source_format STRING,
    content_hash STRING,
    source_key STRING,
    confidence DOUBLE,
    confidence_low BOOLEAN,
    pathway_strength DOUBLE,
    archived BOOLEAN,
    created_at TIMESTAMP,
    last_accessed_at TIMESTAMP,
    PRIMARY KEY (dataset_id)
"""

_CONCEPT_DDL = """
    concept_id STRING,
    text_raw STRING,
    embedding FLOAT[384],
    embedding_model STRING,
    embedding_dim INT64,
    gist_class STRING,
    schema_org_type STRING,
    confidence DOUBLE,
    confidence_low BOOLEAN,
    pathway_strength DOUBLE,
    archived BOOLEAN,
    created_at TIMESTAMP,
    last_accessed_at TIMESTAMP,
    PRIMARY KEY (concept_id)
"""


@pytest.fixture()
def real_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="tabular_facts_dedup_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(f"CREATE NODE TABLE Dataset({_DATASET_DDL})")
    db.execute(f"CREATE NODE TABLE Concept({_CONCEPT_DDL})")
    db.execute(
        "CREATE REL TABLE DESCRIBED_BY_DATASET(FROM Concept TO Dataset, "
        "extraction_method STRING, created_at TIMESTAMP)"
    )
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed",
        lambda text, model_name=None: [0.1] * 384,
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def cleanup_sqlite():
    before = set(tables_dir().glob("*.sqlite")) if tables_dir().exists() else set()
    yield
    after = set(tables_dir().glob("*.sqlite")) if tables_dir().exists() else set()
    for path in after - before:
        path.unlink(missing_ok=True)


class _FakeLLMClient:
    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    async def achat(self, messages):
        self.prompts.append(messages[0]["content"])
        return self._response


def _write_csv(tmp_path, name="budget.csv"):
    path = tmp_path / name
    path.write_text("category,amount\nRent,2000\nFood,600\nUtilities,150\n")
    return path


class TestLLMSummary:
    async def test_uses_llm_response_as_description(self, real_db, tmp_path, monkeypatch):
        fake_client = _FakeLLMClient("A monthly household budget across three categories.")
        monkeypatch.setattr(
            tabular_ingest, "create_llm_client_for_step", lambda config, step: fake_client
        )
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert "error" not in result
        assert result["summaries"][0] == "A monthly household budget across three categories."
        assert "amount" in fake_client.prompts[0]

    async def test_falls_back_to_template_when_llm_unavailable(self, real_db, tmp_path, monkeypatch):
        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: None)
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert "error" not in result
        assert "budget.csv" in result["summaries"][0]
        assert "3 rows" in result["summaries"][0]

    async def test_falls_back_to_template_on_llm_exception(self, real_db, tmp_path, monkeypatch):
        class _Boom:
            async def achat(self, messages):
                raise RuntimeError("provider unreachable")

        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: _Boom())
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert "error" not in result
        assert "budget.csv" in result["summaries"][0]


class TestKeyFactExtraction:
    async def test_extracted_facts_become_linked_concept_nodes(self, real_db, tmp_path, monkeypatch):
        fake_client = _FakeLLMClient(
            '[{"text": "Total monthly spend is 2750"}, {"text": "Rent is the largest expense category"}]'
        )
        monkeypatch.setattr(
            tabular_ingest, "create_llm_client_for_step", lambda config, step: fake_client
        )
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert "error" not in result
        assert result["facts_extracted"] == [2]
        dataset_id = result["dataset_ids"][0]

        rows = real_db.execute(
            "MATCH (c:Concept)-[r:DESCRIBED_BY_DATASET]->(d:Dataset {dataset_id: $did}) "
            "RETURN c.text_raw, r.extraction_method",
            {"did": dataset_id},
        )
        facts = []
        while rows.has_next():
            facts.append(rows.get_next())
        texts = {f[0] for f in facts}
        assert texts == {"Total monthly spend is 2750", "Rent is the largest expense category"}
        assert all(f[1] == "llm" for f in facts)

    async def test_fact_concepts_are_structurally_retrievable(self, real_db, tmp_path, monkeypatch):
        """AC: extracted Concepts participate in normal current_truth
        retrieval - proven by satisfying the same structural query shape
        current_truth/bundle_compiler issue (embedding present, archived
        = false, real Concept label)."""
        fake_client = _FakeLLMClient('[{"text": "Total monthly spend is 2750"}]')
        monkeypatch.setattr(
            tabular_ingest, "create_llm_client_for_step", lambda config, step: fake_client
        )
        csv_path = _write_csv(tmp_path)

        await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        rows = real_db.execute(
            "MATCH (c:Concept) "
            "WHERE (1 - array_cosine_similarity(c.embedding, $q)) < 0.30 AND c.archived = false "
            "RETURN c.text_raw",
            {"q": [0.1] * 384},
        )
        texts = []
        while rows.has_next():
            texts.append(rows.get_next()[0])
        assert "Total monthly spend is 2750" in texts

    async def test_no_llm_client_extracts_zero_facts(self, real_db, tmp_path, monkeypatch):
        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: None)
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert result["facts_extracted"] == [0]
        rows = real_db.execute("MATCH (c:Concept) RETURN count(c)")
        assert rows.get_next()[0] == 0

    async def test_malformed_llm_response_extracts_zero_facts_without_crashing(
        self, real_db, tmp_path, monkeypatch
    ):
        fake_client = _FakeLLMClient("not valid json at all")
        monkeypatch.setattr(
            tabular_ingest, "create_llm_client_for_step", lambda config, step: fake_client
        )
        csv_path = _write_csv(tmp_path)

        result = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert "error" not in result
        assert result["facts_extracted"] == [0]


class TestChangeDetectionAndArchiving:
    async def test_reuploading_unchanged_file_returns_already_current(self, real_db, tmp_path, monkeypatch):
        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: None)
        csv_path = _write_csv(tmp_path)

        first = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)
        second = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        assert first["already_current"] is False
        assert second["already_current"] is True
        assert second["dataset_ids"] == first["dataset_ids"]

        rows = real_db.execute("MATCH (d:Dataset) RETURN count(d)")
        assert rows.get_next()[0] == 1

    async def test_reuploading_changed_file_archives_old_and_creates_new(self, real_db, tmp_path, monkeypatch):
        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: None)
        csv_path = _write_csv(tmp_path)

        first = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)
        old_dataset_id = first["dataset_ids"][0]

        csv_path.write_text("category,amount\nRent,2200\nFood,650\nUtilities,160\nInternet,80\n")
        second = await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)
        new_dataset_id = second["dataset_ids"][0]

        assert second["already_current"] is False
        assert new_dataset_id != old_dataset_id
        assert second["row_counts"] == [4]

        rows = real_db.execute(
            "MATCH (d:Dataset {dataset_id: $did}) RETURN d.archived", {"did": old_dataset_id}
        )
        assert rows.get_next()[0] is True

        rows = real_db.execute(
            "MATCH (d:Dataset {dataset_id: $did}) RETURN d.archived", {"did": new_dataset_id}
        )
        assert rows.get_next()[0] is False

        rows = real_db.execute("MATCH (d:Dataset) RETURN count(d)")
        assert rows.get_next()[0] == 2

    async def test_old_fact_concepts_survive_archiving(self, real_db, tmp_path, monkeypatch):
        fake_client = _FakeLLMClient('[{"text": "Original total spend fact"}]')
        monkeypatch.setattr(
            tabular_ingest, "create_llm_client_for_step", lambda config, step: fake_client
        )
        csv_path = _write_csv(tmp_path)
        await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        csv_path.write_text("category,amount\nRent,2200\nFood,650\nUtilities,160\nInternet,80\n")
        fake_client._response = '[{"text": "Updated total spend fact"}]'
        await tabular_ingest.ingest_tabular(real_db, str(csv_path), CONFIG)

        rows = real_db.execute("MATCH (c:Concept) RETURN c.text_raw ORDER BY c.text_raw")
        texts = []
        while rows.has_next():
            texts.append(rows.get_next()[0])
        assert texts == ["Original total spend fact", "Updated total spend fact"]

    async def test_different_files_do_not_collide_on_change_detection(self, real_db, tmp_path, monkeypatch):
        """Two distinct source files must never be treated as re-uploads of
        each other, even if ingested in the same run."""
        monkeypatch.setattr(tabular_ingest, "create_llm_client_for_step", lambda config, step: None)
        csv_a = _write_csv(tmp_path, "a.csv")
        csv_b = _write_csv(tmp_path, "b.csv")

        result_a = await tabular_ingest.ingest_tabular(real_db, str(csv_a), CONFIG)
        result_b = await tabular_ingest.ingest_tabular(real_db, str(csv_b), CONFIG)

        assert result_a["already_current"] is False
        assert result_b["already_current"] is False
        assert result_a["dataset_ids"] != result_b["dataset_ids"]

        rows = real_db.execute("MATCH (d:Dataset) RETURN count(d)")
        assert rows.get_next()[0] == 2
