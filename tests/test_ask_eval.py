"""B304 — ask-eval harness tests.

Covers acceptance criteria (a)-(d):
  (a) scoring unit tests
  (b) H1 identifier fast-path unit test
  (c) H2 empty-claim guard unit test
  (d) fixture seeding against a temp DB (real Kuzu)
"""

from __future__ import annotations

import os
import shutil

import pytest
from typer.testing import CliRunner

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.ask import (
    _extract_identifier_tokens,
    _h1_identifier_fastpath,
    _h2_empty_claim_guard,
)
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle
from benchmarks.ask_eval.runner import eval_app, score_question
from benchmarks.ask_eval.fixtures import seed_fixture_graph


# --- (a) scoring -------------------------------------------------------

def test_score_question_covered_scores_one():
    question = {
        "id": "T1",
        "family": "test",
        "question": "irrelevant",
        "must_match": [r"split", r"module"],
        "must_not_match": [r"no information"],
    }
    result = score_question(question, "We split the module into pieces.")
    assert result["score"] == 1.0
    assert result["covered"] is True
    assert result["hallucinated"] is False


def test_score_question_not_covered_scores_zero():
    question = {
        "id": "T2",
        "family": "test",
        "question": "irrelevant",
        "must_match": [r"split", r"module"],
        "must_not_match": [],
    }
    result = score_question(question, "We did some other unrelated work.")
    assert result["score"] == 0
    assert result["covered"] is False
    assert result["hallucinated"] is False


def test_score_question_hallucination_scores_negative_one():
    question = {
        "id": "T3",
        "family": "test",
        "question": "irrelevant",
        "must_match": [r"kubernetes"],
        "must_not_match": [r"kubernetes.*cluster"],
    }
    result = score_question(question, "The kubernetes cluster is deployed on GKE.")
    assert result["score"] == -1.0
    assert result["hallucinated"] is True


# --- (b) H1 identifier fast-path ---------------------------------------

def _bundle_with_b292_plan() -> ContextBundle:
    plan_item = {
        "plan_id": "plan-b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "status": "completed",
        "valence": 0.8,
        "steps": [{"step_number": 1, "description": "Split tools into modules", "valence": 0.8}],
    }
    section = BundleSection(
        section_type="plans",
        content=[plan_item],
        token_estimate=150,
        source_node_ids=["plan-b292"],
    )
    return ContextBundle(
        query="What happened on B292?",
        sections=[section],
        total_token_estimate=150,
        token_budget=32000,
        truncated=False,
    )


def test_extract_identifier_tokens_finds_backlog_ids():
    assert _extract_identifier_tokens("What happened on B292?") == ["B292"]
    assert _extract_identifier_tokens("no ids here") == []


def test_h1_fastpath_prepends_preamble_with_matching_plan_goal():
    bundle = _bundle_with_b292_plan()
    prompt = "Query: What happened on B292?\n\nContext from memory:\n"
    result = _h1_identifier_fastpath(prompt, bundle, bundle.query)
    assert "DIRECT MATCHES for B292" in result
    assert "Implement B292 by splitting tools/__init__.py into focused modules" in result
    # original prompt content preserved
    assert prompt in result


def test_h1_fastpath_is_noop_when_no_identifier_in_query():
    bundle = _bundle_with_b292_plan()
    prompt = "Query: tell me about the plans\n\nContext from memory:\n"
    result = _h1_identifier_fastpath(prompt, bundle, "tell me about the plans")
    assert result == prompt


# --- (c) H2 empty-claim guard -------------------------------------------

class _FakeLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return self._responses.pop(0)


def test_h2_retries_once_when_bundle_nonempty_and_answer_claims_empty():
    bundle = _bundle_with_b292_plan()
    llm = _FakeLLM(["B292 was about splitting the module."])
    meta: dict = {}
    answer = _h2_empty_claim_guard(
        answer="My memory is empty.",
        bundle=bundle,
        prompt="some prompt",
        llm=llm,
        meta=meta,
    )
    assert answer == "B292 was about splitting the module."
    assert llm.calls == 1  # exactly one retry call
    assert meta["retried"] is True


def test_h2_does_not_retry_when_bundle_is_empty():
    empty_bundle = ContextBundle(
        query="anything", sections=[], total_token_estimate=0, token_budget=32000, truncated=False,
    )
    llm = _FakeLLM(["My memory is empty."])
    meta: dict = {}
    answer = _h2_empty_claim_guard(
        answer="My memory is empty.",
        bundle=empty_bundle,
        prompt="some prompt",
        llm=llm,
        meta=meta,
    )
    assert answer == "My memory is empty."
    assert llm.calls == 0
    assert meta["retried"] is False


def test_h2_does_not_retry_when_answer_does_not_claim_empty():
    bundle = _bundle_with_b292_plan()
    llm = _FakeLLM(["B292 was the module split."])
    meta: dict = {}
    answer = _h2_empty_claim_guard(
        answer="B292 was the module split.",
        bundle=bundle,
        prompt="some prompt",
        llm=llm,
        meta=meta,
    )
    assert answer == "B292 was the module split."
    assert llm.calls == 0
    assert meta["retried"] is False


# --- (d) fixture seeding (real Kuzu) ------------------------------------

@pytest.mark.asyncio
async def test_seed_fixture_graph_creates_plans_and_lessons():
    db_path = "./test_ask_eval_fixture.db"
    if os.path.exists(db_path):
        shutil.rmtree(db_path) if os.path.isdir(db_path) else os.remove(db_path)

    db = KuzuClient(db_path)
    try:
        embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
        init_schema(db, "campy/data/GistSeedExamples.md", embedding_model)
        config = {
            "embeddings": {"model": embedding_model},
            "ingestion": {"max_ingest_chars": 4000},
        }

        await seed_fixture_graph(db, config)

        plan_count = db.execute("MATCH (p:Plan) RETURN count(p)").get_next()[0]
        lesson_count = db.execute("MATCH (l:Lesson) RETURN count(l)").get_next()[0]
        message_count = db.execute("MATCH (m:Message) RETURN count(m)").get_next()[0]

        assert plan_count >= 3
        assert lesson_count >= 2
        assert message_count >= 4
    finally:
        db.close()
        if os.path.exists(db_path):
            shutil.rmtree(db_path) if os.path.isdir(db_path) else os.remove(db_path)


# --- CLI wiring -----------------------------------------------------------

def test_eval_ask_cli_is_registered():
    # Deliberately NOT wired into campy.cli.main: docs/ecosystem-rules.md forbids
    # any file under campy/ from importing benchmarks/ (enforced by
    # tests/test_architecture_import_boundaries.py). Exercised standalone here.
    # eval_app has a single command, so Typer collapses it — no "ask" subcommand
    # argument needed (matches `python -m benchmarks.ask_eval.runner --model ...`).
    runner = CliRunner()
    result = runner.invoke(eval_app, ["--help"])
    assert result.exit_code == 0
    assert "--model" in result.output
    assert "--variant" in result.output

    # Confirms invalid extra positional args (e.g. a stray "ask") are rejected —
    # --help short-circuits before arg validation, so this check omits it.
    result = runner.invoke(eval_app, ["ask", "--model", "llama3.1:8b"])
    assert result.exit_code != 0
