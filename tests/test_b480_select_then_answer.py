"""B480 — optional two-step "select then answer" mode for ask (M4.3).

Fake LLM only; no network, no DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from campy.brain.thalamus import ask as ask_mod
from campy.brain.thalamus.ask import (
    _ABSTAIN_ANSWER,
    _ASK_SYSTEM_PROMPT,
    _SELECT_INSTRUCTION,
    _SELECT_SYSTEM_PROMPT,
    _answer_mode,
    _bundle_to_prompt,
    _parse_selection,
    run_ask,
)
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle


def _bundle() -> ContextBundle:
    conv = BundleSection(
        section_type="conversation",
        content=[
            {"text": "[2024-01-02] Alice: I adopted a cat named Miso."},
            {"text": "[2024-01-03] Alice: My neighbour has a dog named Rex."},
        ],
        token_estimate=20,
        source_node_ids=[],
    )
    sem = BundleSection(
        section_type="semantic",
        content=[{"text": "Alice lives in Lisbon."}],
        token_estimate=5,
        source_node_ids=[],
    )
    return ContextBundle(
        query="What is Alice's cat called?",
        sections=[conv, sem],
        total_token_estimate=25,
        token_budget=32000,
        truncated=False,
    )


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def achat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.replies.pop(0)


async def _ask(llm, config, bundle=None, meta=None):
    with patch(
        "campy.brain.thalamus.ask.compile_bundle",
        new_callable=AsyncMock,
        return_value=bundle or _bundle(),
    ), patch("campy.brain.thalamus.ask._get_llm", return_value=llm), patch(
        "campy.brain.thalamus.ask._capture_turn", new_callable=AsyncMock
    ):
        return await run_ask(
            query="What is Alice's cat called?",
            session_id="s",
            db=MagicMock(),
            config=config,
            meta=meta,
        )


# --- direct mode unchanged ---------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"ask": {}}, {"ask": {"answer_mode": "direct"}}])
async def test_direct_mode_is_one_call_with_identical_prompt(config):
    llm = FakeLLM(["Miso"])
    meta: dict = {}
    assert await _ask(llm, config, meta=meta) == "Miso"
    assert len(llm.calls) == 1
    assert llm.calls[0] == [
        {"role": "system", "content": _ASK_SYSTEM_PROMPT},
        {"role": "user", "content": _bundle_to_prompt(_bundle(), "What is Alice's cat called?", config)},
    ]
    assert meta["answer_mode"] == "direct"
    assert "selected_lines" not in meta


def test_unknown_mode_falls_back_to_direct():
    assert _answer_mode({"ask": {"answer_mode": "bogus"}}) == "direct"
    assert _answer_mode({"ask": {"answer_mode": " SELECT "}}) == "select"


# --- select mode --------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_mode_second_prompt_has_only_selected_lines():
    llm = FakeLLM(["1", "Miso"])
    meta: dict = {}
    out = await _ask(llm, {"ask": {"answer_mode": "select"}}, meta=meta)
    assert out == "Miso"
    assert len(llm.calls) == 2

    sel = llm.calls[0]
    assert sel[0] == {"role": "system", "content": _SELECT_SYSTEM_PROMPT}
    assert "[1] " in sel[1]["content"] and "[3] " in sel[1]["content"]
    assert sel[1]["content"].rstrip().endswith(_SELECT_INSTRUCTION)

    ans = llm.calls[1]
    assert ans[0] == {"role": "system", "content": _ASK_SYSTEM_PROMPT}
    p = ans[1]["content"]
    assert "Miso" in p
    assert "Rex" not in p and "Lisbon" not in p
    # section header/description kept, no select-step numbering leaked
    assert "[conversation:" in p and "[semantic:" not in p
    assert "[1] " not in p
    assert {k: meta[k] for k in ("answer_mode", "n_lines", "selected_lines", "select_fallback")} == {
        "answer_mode": "select", "n_lines": 3, "selected_lines": [1], "select_fallback": False,
    }


@pytest.mark.asyncio
async def test_select_multiple_lines_across_sections():
    llm = FakeLLM(["1, 3", "Miso, Lisbon"])
    await _ask(llm, {"ask": {"answer_mode": "select"}})
    p = llm.calls[1][1]["content"]
    assert "Miso" in p and "Lisbon" in p and "Rex" not in p


@pytest.mark.asyncio
async def test_none_abstains_without_second_call():
    llm = FakeLLM(["NONE"])
    meta: dict = {}
    out = await _ask(llm, {"ask": {"answer_mode": "select"}}, meta=meta)
    assert out == _ABSTAIN_ANSWER
    assert len(llm.calls) == 1
    assert meta["selected_lines"] == [] and meta["select_fallback"] is False


@pytest.mark.asyncio
async def test_garbage_reply_falls_back_to_direct():
    llm = FakeLLM(["I think the cat one, probably", "Miso"])
    meta: dict = {}
    out = await _ask(llm, {"ask": {"answer_mode": "select"}}, meta=meta)
    assert out == "Miso"
    assert len(llm.calls) == 2
    # second call is the full direct prompt
    assert llm.calls[1][1]["content"] == _bundle_to_prompt(
        _bundle(), "What is Alice's cat called?", {}
    )
    assert meta["select_fallback"] is True and meta["selected_lines"] is None


@pytest.mark.asyncio
async def test_all_out_of_range_falls_back():
    llm = FakeLLM(["7, 9", "Miso"])
    meta: dict = {}
    await _ask(llm, {"ask": {"answer_mode": "select"}}, meta=meta)
    assert meta["select_fallback"] is True


@pytest.mark.asyncio
async def test_empty_bundle_skips_select_step():
    empty = ContextBundle(
        query="q", sections=[], total_token_estimate=0, token_budget=32000, truncated=False,
    )
    llm = FakeLLM(["nothing known"])
    meta: dict = {}
    await _ask(llm, {"ask": {"answer_mode": "select"}}, bundle=empty, meta=meta)
    assert len(llm.calls) == 1
    assert "No relevant context" in llm.calls[0][1]["content"]
    assert meta["n_lines"] == 0 and meta["select_fallback"] is False


def test_parse_selection():
    assert _parse_selection("1, 3", 3) == [1, 3]
    assert _parse_selection("Lines 2 and 3.", 3) == [2, 3]
    assert _parse_selection("[2]", 3) == [2]
    assert _parse_selection("1, 2, 99, 0", 3) == [1, 2]  # out of range ignored
    assert _parse_selection("2-3", 5) == [2, 3]
    assert _parse_selection("none", 3) == []
    assert _parse_selection("NONE.", 3) == []
    assert _parse_selection("<think>maybe 9 or none</think>2", 3) == [2]
    assert _parse_selection("", 3) is None
    assert _parse_selection("dunno", 3) is None
    assert _parse_selection("99", 3) is None


# --- harness variants / compression -------------------------------------------

@pytest.mark.asyncio
async def test_h2_retries_final_answer_only_in_select_mode():
    llm = FakeLLM(["1", "the context is empty", "Miso"])
    meta: dict = {}
    cfg = {"ask": {"answer_mode": "select", "harness_variant": "H2"}}
    out = await _ask(llm, cfg, meta=meta)
    assert out == "Miso"
    assert len(llm.calls) == 3 and meta["retried"] is True
    # retry prompt is built from the selected-lines prompt
    assert "Rex" not in llm.calls[2][1]["content"]


@pytest.mark.asyncio
async def test_h2_not_applied_to_none_abstention():
    llm = FakeLLM(["NONE"])
    meta: dict = {}
    cfg = {"ask": {"answer_mode": "select", "harness_variant": "H2"}}
    assert await _ask(llm, cfg, meta=meta) == _ABSTAIN_ANSWER
    assert "retried" not in meta


@pytest.mark.asyncio
async def test_h1_does_not_reinject_unselected_lines_in_select_mode():
    plans = BundleSection(
        section_type="plans",
        content=[{"goal": "Do B292 thing", "status": "done", "steps": []}],
        token_estimate=5, source_node_ids=[],
    )
    sem = BundleSection(
        section_type="semantic", content=[{"text": "B292 is the tools split."}],
        token_estimate=5, source_node_ids=[],
    )
    b = ContextBundle(query="B292?", sections=[plans, sem], total_token_estimate=10,
                      token_budget=32000, truncated=False)
    llm = FakeLLM(["1", "ok"])
    cfg = {"ask": {"answer_mode": "select", "harness_variant": "H1"}}
    await _ask(llm, cfg, bundle=b)
    assert "DIRECT MATCHES" not in llm.calls[1][1]["content"]
    assert "tools split" not in llm.calls[1][1]["content"]


@pytest.mark.asyncio
async def test_compression_path_unaffected_in_select_mode():
    # Over-budget bundle: compression runs first, select numbers the compressed lines.
    sec = MagicMock()
    sec.section_type = "summary"
    sec.content = [{"text": "orig"}]
    sec.token_estimate = 10_000_000
    bundle = MagicMock()
    bundle.sections = [sec]
    compressed = MagicMock()
    compressed.section_type = "summary"
    compressed.content = [{"text": "compressed line"}]
    compressed.token_estimate = 3
    router = MagicMock()
    router.compress_section.return_value = compressed
    llm = FakeLLM(["1", "done"])
    meta: dict = {}
    with patch("campy.brain.thalamus.compression.build_default_registry",
               return_value=(None, router)):
        await _ask(llm, {"compression": {}, "ask": {"answer_mode": "select"}},
                   bundle=bundle, meta=meta)
    assert meta["compression_bypassed"] is False
    assert "compressed line" in llm.calls[1][1]["content"]
    assert "orig" not in llm.calls[1][1]["content"]
