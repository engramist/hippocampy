"""B489 -- "verify" answer style: quote check + YES/NO verifier."""

from __future__ import annotations

import asyncio

import pytest

from campy.brain.brainstem.config import apply_env_overrides
from campy.brain.thalamus.ask import (
    _answer_style, _extract_quotes, _verify_cited_answer)

PROMPT = (
    "Query: What is Jon's favorite dance?\n\nContext from memory:\n"
    "[conversation: turns]\n"
    "[Jon, 2023-01-20 16:04] I love all dances, but contemporary is my top pick\n"
    "[Gina, 2023-01-20 16:05] My team performed Finding Freedom\n"
)
Q = "What is Jon's favorite dance?"


class FakeLLM:
    def __init__(self, reply="YES", exc=None):
        self.reply, self.exc, self.calls = reply, exc, 0

    async def achat(self, messages):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.reply


def _run(answer, llm, meta):
    return asyncio.run(_verify_cited_answer(answer, Q, PROMPT, llm, meta))


GOOD = 'Contemporary. "I love all dances, but contemporary is my top pick"'


def test_already_abstained_no_call():
    llm, meta = FakeLLM(), {}
    ans = "I don't have that information."
    assert _run(ans, llm, meta) == ans
    assert llm.calls == 0 and meta["verify"] == "already_abstained"


def test_no_quote_abstains():
    llm, meta = FakeLLM(), {}
    assert _run("Contemporary.", llm, meta) == "I don't have that information."
    assert llm.calls == 0 and meta["verify"] == "no_quote"


def test_quote_not_in_context_abstains():
    llm, meta = FakeLLM(), {}
    out = _run('Salsa. "He told me salsa is his absolute favourite thing"', llm, meta)
    assert out == "I don't have that information."
    assert llm.calls == 0 and meta["verify"] == "quote_not_in_context"


def test_verifier_yes_keeps():
    llm, meta = FakeLLM("YES."), {}
    assert _run(GOOD, llm, meta) == GOOD
    assert llm.calls == 1 and meta["verify"] == "kept"


def test_verifier_no_abstains():
    llm, meta = FakeLLM("No"), {}
    assert _run(GOOD, llm, meta) == "I don't have that information."
    assert meta["verify"] == "verifier_no"


def test_verifier_exception_keeps():
    llm, meta = FakeLLM(exc=RuntimeError("boom")), {}
    assert _run(GOOD, llm, meta) == GOOD
    assert meta["verify"] == "verifier_error"


def test_quote_formats():
    assert _extract_quotes('A “I love all dances today”') == ["I love all dances today"]
    assert _extract_quotes("A\nQuote: I love all dances today") == ["I love all dances today"]


def test_env_override_and_default():
    assert apply_env_overrides({}, {"CAMPY_ASK_ANSWER_STYLE": "Verify"})["ask"]["answer_style"] == "verify"
    with pytest.raises(ValueError):
        apply_env_overrides({}, {"CAMPY_ASK_ANSWER_STYLE": "bogus"})
    assert _answer_style(None) == "cite"
    assert _answer_style({"ask": {"answer_style": "verify"}}) == "verify"


def test_verifier_yes_with_markdown_keeps():
    import asyncio
    from campy.brain.thalamus import ask as ask_mod

    class _LLM:
        async def achat(self, messages):
            return "**Yes** — it does."

    prompt = "Query: q\n\nContext from memory:\nCaroline: I love all dances, but contemporary is my top pick"
    answer = 'Contemporary. "I love all dances, but contemporary is my top pick"'
    meta = {}
    out = asyncio.run(ask_mod._verify_cited_answer(answer, "q", prompt, _LLM(), meta))
    assert out == answer and meta["verify"] == "kept"
