"""B578: window mode is the default (review session ruling, 2026-11-19, after jobs 1011 and 1012).

The default config turns the reranker on in window mode; without a model path the section is unchanged and the
missing-path warning is logged once per process, not once per question.
"""
import logging

import pytest

from campy.brain.brainstem.config import load_config
from campy.brain.thalamus import turn_rerank as tr

QUERY_EMB = [0.0] * 4


def _row(n):
    return {"node_id": f"urn:campy:msg/m{n}", "text": f"Ann: t{n}", "created_at": f"2023-01-0{n}"}


def test_default_config_resolves_to_window_mode(tmp_path, monkeypatch):
    for k in ("CAMPY_TURN_RERANK", "CAMPY_TURN_RERANK_MODE", "CAMPY_TURN_RERANK_PATH", "CAMPY_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "ollama"\n')
    cfg = load_config(path)
    assert tr.turn_rerank_enabled(cfg) is True
    assert tr.turn_rerank_mode(cfg) == "window"
    assert tr.turn_rerank_enabled({}) is True and tr.turn_rerank_mode({}) == "window"


def test_env_still_turns_it_off(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "ollama"\n')
    monkeypatch.setenv("CAMPY_TURN_RERANK", "0")
    assert tr.turn_rerank_enabled(load_config(path)) is False


@pytest.mark.asyncio
async def test_missing_path_is_a_no_op_with_one_warning_per_process(caplog):
    tr._scorers.clear(); tr._warned.clear()
    cfg = {"retrieval": {"turn_rerank_path": ""}}  # defaults: on, window mode
    rows = [_row(1), _row(2)]
    with caplog.at_level(logging.WARNING, logger=tr.__name__):
        for _ in range(25):  # one per question
            assert await tr.rerank_conversation(None, rows, "q", QUERY_EMB, cfg) is rows
    assert sum("turn_rerank_path" in r.getMessage() for r in caplog.records) == 1
    tr._scorers.clear(); tr._warned.clear()
