"""B458 — save-gate labeled set and baseline harness."""
from collections import Counter

import pytest

from benchmarks.save_gate import run_baseline as rb
from campy.brain.temporal_lobe.category_spec import CATEGORIES
from campy.brain.temporal_lobe.loop.step4_pattern import (
    NOISE_FLOOR, apply_salience_rescue, classify_artifact,
)


def test_gold_labels_are_spec_categories_and_ids_unique():
    items = rb.load_gold()
    assert {it["label"] for it in items} <= set(CATEGORIES)
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids))
    counts = Counter(it["label"] for it in items)
    assert all(counts[c] >= 20 for c in CATEGORIES)


def test_keyword_type_matches_classify_artifact():
    # When a signal fires, classify_artifact's type must equal the harness's
    # keyword type for any gist class: the harness claims exactness here.
    for text in ["We decided to use Postgres.", "Never commit secrets.",
                 "The importer needs to handle UTF-16.", "Next step: add retries."]:
        ktype, hits = rb.keyword_type(text)
        assert hits > 0
        for gist in ("Restriction", "PlannedEvent", "Agent", "Category"):
            assert classify_artifact(text, gist, None)["artifact_type"] == ktype


def test_signals_mode_runs_and_reports():
    m = rb.score_signals(rb.load_gold())
    assert m["n"] == len(rb.load_gold())
    assert 0.0 <= m["coverage"] <= 1.0
    assert "signals mode" in rb.format_signals(m)


def _entity(text, gist="Restriction"):
    return {"text": text, "gist_class": gist, "schema_org_type": "Demand"}


def test_decide_message_picks_reified_over_tentative():
    text = "We decided we must never log prompt bodies."
    result = rb.decide_message(text, [_entity("prompt bodies"), _entity("we", gist=None)])
    assert result["outcome"] == "reified"
    assert result["artifact_type"] == "constraint"


def test_decide_message_no_entities_is_noise():
    assert rb.decide_message("Thanks!", [])["outcome"] == "noise"


def test_score_full_counts_false_saves_and_misses():
    items = [{"id": "a", "label": "decision", "probe": "clear", "text": ""},
             {"id": "b", "label": "none", "probe": "hedged", "text": ""},
             {"id": "c", "label": "constraint", "probe": "clear", "text": ""}]
    results = [{"outcome": "reified", "artifact_type": "decision", "confidence": 0.95},
               {"outcome": "reified", "artifact_type": "requirement", "confidence": 0.92},
               {"outcome": "noise", "artifact_type": "none", "confidence": 0.0}]
    m = rb.score_full(items, results)
    assert m["reified_accuracy"] == pytest.approx(1 / 3)
    assert m["false_save_rate"] == 1.0
    assert m["missed_save_rate"] == 0.5
    top_bin = m["reliability"][-1]
    assert top_bin["n"] == 2 and top_bin["accuracy"] == 0.5
    assert "full mode" in rb.format_full(m)


# apply_salience_rescue: extracted from run_loop, behavior must match the old inline block.

def test_salience_rescue_lifts_dead_zone_with_emotion():
    below = {"artifact_type": "constraint", "confidence": 0.50,
             "confidence_low": True, "should_proceed": False}
    text = "I told you, stop doing that! This is broken, ugh."
    result, salience, rescued = apply_salience_rescue(below, text)
    assert rescued and salience >= 1.3
    assert result["should_proceed"] and result["confidence"] == pytest.approx(NOISE_FLOOR + 0.02)
    assert result["artifact_type"] == "constraint"


def test_salience_rescue_ignores_calm_text_and_deep_noise():
    below = {"artifact_type": "constraint", "confidence": 0.50,
             "confidence_low": True, "should_proceed": False}
    assert apply_salience_rescue(below, "ok sounds fine")[2] is False
    deep = dict(below, confidence=0.30)
    assert apply_salience_rescue(deep, "I told you, stop doing that! ugh")[2] is False


def test_salience_rescue_leaves_passing_results_alone():
    ok = {"artifact_type": "decision", "confidence": 0.92,
          "confidence_low": False, "should_proceed": True}
    result, _s, rescued = apply_salience_rescue(ok, "I told you, stop doing that! ugh")
    assert result is ok and not rescued
