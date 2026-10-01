"""B460 — constrained choices with model-derived probabilities; artifact statement text."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

import pytest

from campy.brain.llm.decide import Decision, decide, options_block
from campy.brain.llm.provider import LLMClient
from campy.brain.temporal_lobe.loop import step2_gist
from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

LABELS = ["additive", "contradiction", "uncertain"]


class LogprobClient:
    """Stands in for LLMClient: answers with a letter plus first-token logprobs."""
    def __init__(self, dist: dict[str, float], text: str | None = None):
        self.dist = dist
        self.text = text or max(dist, key=dist.get)
    def chat_choice(self, messages):
        return self.text, [(tok, math.log(p)) for tok, p in self.dist.items()]


class TextClient:
    def __init__(self, text):
        self.text = text
    def chat(self, messages):
        return self.text


# --- decide() -----------------------------------------------------------------

def test_probabilities_from_first_token_logprobs():
    d = decide(LogprobClient({"A": 0.6, " B": 0.3, "C)": 0.05, "the": 0.05}), "p", LABELS)
    assert d.source == "logprobs" and d.choice == "additive"
    # renormalised over valid letters only ("the" dropped)
    assert d.probs["additive"] == pytest.approx(0.6 / 0.95)
    assert sum(d.probs.values()) == pytest.approx(1.0)
    assert d.margin == pytest.approx((0.6 - 0.3) / 0.95)


def test_near_tie():
    tie = decide(LogprobClient({"A": 0.48, "B": 0.44, "C": 0.08}), "p", LABELS)
    assert tie.near_tie()
    clear = decide(LogprobClient({"A": 0.9, "B": 0.05, "C": 0.05}), "p", LABELS)
    assert not clear.near_tie()


def test_text_fallback_has_no_probabilities():
    for text, want in [("B", "contradiction"), ("(C)", "uncertain"), ("A) additive", "additive"),
                       ('{"classification": "additive"}', "additive")]:
        d = decide(TextClient(text), "p", LABELS)
        assert d.choice == want and d.probs is None and d.probability is None
        assert not d.near_tie()
    # two labels mentioned: ambiguous, no guess
    assert decide(TextClient("additive or contradiction"), "p", LABELS).choice is None


def test_decide_never_raises():
    class Broken:
        def chat(self, messages):
            raise RuntimeError("down")
    assert decide(Broken(), "p", LABELS) == Decision(None, None, "none", "")


def test_options_block_letters():
    block = options_block(["x", "y"], {"x": "first"})
    assert "A) x: first" in block and "B) y" in block and "single letter" in block


# --- LLMClient.chat_choice ------------------------------------------------------

def _response(text, tokens):
    content = [NS(token=t, top_logprobs=[NS(token=a, logprob=lp) for a, lp in top])
               for t, top in tokens]
    return NS(choices=[NS(message=NS(content=text), logprobs=NS(content=content))], usage=None)


def test_chat_choice_reads_first_non_whitespace_token():
    resp = _response(" B", [(" ", [(" ", -0.1)]), ("B", [("B", -0.2), ("A", -1.9)])])
    fake = NS(chat=NS(completions=NS(create=lambda **kw: resp)))
    text, top = LLMClient(fake, "m").chat_choice([{"role": "user", "content": "q"}])
    assert text == " B" and top == [("B", -0.2), ("A", -1.9)]


def test_chat_choice_falls_back_when_logprobs_rejected():
    calls = []
    def create(**kw):
        calls.append(kw)
        if "logprobs" in kw:
            raise ValueError("unsupported parameter: logprobs")
        return NS(choices=[NS(message=NS(content="A"))], usage=None)
    fake = NS(chat=NS(completions=NS(create=create)))
    text, top = LLMClient(fake, "m").chat_choice([{"role": "user", "content": "q"}])
    assert (text, top) == ("A", None) and len(calls) == 2


# --- Step 6 ---------------------------------------------------------------------

CANDS = [{"concept_id": "abc", "text_raw": "old", "similarity": 0.82, "pathway_strength": 0.7}]


def test_step6_near_tie_becomes_uncertain():
    llm = LogprobClient({"A": 0.46, "B": 0.44, "C": 0.10})
    result = arbitrate({"text": "new"}, CANDS, "ctx", llm)
    assert result["classification"] == "uncertain"
    assert result["referenced_node_ids"] == ["abc"]
    assert "near tie" in result["rationale"]


def test_step6_clear_choice_kept_with_probs():
    result = arbitrate({"text": "new"}, CANDS, "ctx", LogprobClient({"A": 0.05, "B": 0.9, "C": 0.05}))
    assert result["classification"] == "contradiction"
    assert result["probs"]["contradiction"] == pytest.approx(0.9)


# --- Step 2 ---------------------------------------------------------------------

def test_step2_confidence_is_model_probability():
    letter = "ABCDEFG"[step2_gist.GIST_CLASSES.index("Category")]
    dist = {letter: 0.8, "A" if letter != "A" else "B": 0.2}
    r = step2_gist._classify_with_llm("taxonomy of roles", LogprobClient(dist))
    assert r["gist_class"] == "Category" and r["confidence"] == pytest.approx(0.8)
    assert r["near_tie"] is False


def test_step2_near_tie_flagged():
    r = step2_gist._classify_with_llm("thing", LogprobClient({"A": 0.40, "C": 0.38, "D": 0.22}))
    assert r["near_tie"] is True and r["system"] == "2"


# --- artifact statement text ----------------------------------------------------

EMB = [0.0] * 383 + [1.0]


@pytest.mark.asyncio
async def test_reified_artifact_stores_statement(tmp_path, monkeypatch):
    from campy.brain.hippocampus.graph import embeddings as emb_mod
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
    from campy.brain.temporal_lobe.loop import orchestrator as orch
    from campy.brain.temporal_lobe.loop.step4_pattern import entity_sentence

    embedded = []
    monkeypatch.setattr(emb_mod, "embed",
                        lambda t, model_name=None, **k: embedded.append(t) or EMB)
    db = OxigraphClient(tmp_path / "b460.db")
    text = "Thanks. We decided to use PostgreSQL for the job queue. More later."
    statement = entity_sentence(text, "PostgreSQL")
    assert statement == "We decided to use PostgreSQL for the job queue."

    await orch._reify_concept("c1", "decision", {"text": "PostgreSQL"}, EMB, "m", db,
                              "2026-10-01T00:00:00+00:00", confidence=0.95,
                              statement=statement)

    rows = list(db.store.query(
        'PREFIX campy: <https://campy.dev/ns#> '
        'SELECT ?t WHERE { ?d a campy:Decision ; campy:text_raw ?t }'))
    assert [r["t"].value for r in rows] == [statement]
    assert embedded == [statement]   # embedded from the statement, not the entity
