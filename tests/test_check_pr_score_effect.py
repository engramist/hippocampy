"""Tests for .github/scripts/check_pr_score_effect.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"))

from check_pr_score_effect import RELEVANT_PATHS, check, graph_design_ok, prediction_ok

RELEVANT = ["campy/brain/thalamus/ask.py", "README.md"]
IRRELEVANT = ["README.md", "docs/x.md", "tests/test_a.py"]
TEMPLATE_ONLY = (
    "## Description\nx\n\n## Score effect\n\n"
    "<!-- Gate table (suite | main | branch | gained | lost), or \"None — <reason>\". -->\n\n"
    "## Test Plan\nfoo\n"
)


def test_no_relevant_paths_passes_without_section():
    assert check("no sections here", IRRELEVANT)[0]


GD = "\n## Graph design\nNone — CI tooling\n"


def test_relevant_with_filled_section_passes():
    body = GD + "## Score effect\n\n| suite | main | branch | gained | lost |\n|---|---|---|---|---|\n| LoCoMo | 60 | 62 | 3 | 1 |\nTargets in gate: 12\nPrediction: LoCoMo +2 to +4\n\n## Test Plan\n"
    assert check(body, RELEVANT)[0]


def test_relevant_with_none_reason_passes():
    assert check(GD + "## Score effect\nNone — docs only\nPrediction: none — docs only\n", RELEVANT)[0]


def test_relevant_missing_section_fails():
    ok, msg = check("## Description\nstuff\n", RELEVANT)
    assert not ok and "Score effect" in msg and "thalamus" in msg


def test_relevant_template_comment_only_fails():
    assert not check(TEMPLATE_ONLY, RELEVANT)[0]


def test_empty_body_fails_and_none_body_ok():
    assert not check(None, RELEVANT)[0]
    assert check(None, IRRELEVANT)[0]


def test_drift_report_paths_in_sync():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import drift_report
    assert drift_report.RELEVANT_PATHS == RELEVANT_PATHS


SCORE = "## Score effect\nNone — docs only\n"


def test_capture_paths_are_relevant():
    for path in ("campy/brain/temporal_lobe/dictionary.py", "campy/brain/hippocampus/facts.py"):
        assert not check(SCORE, [path])[0]


def test_graph_design_missing_fails_with_pointer():
    ok, msg = check(SCORE, RELEVANT)
    assert not ok and "Graph design" in msg and "Design-review checklist" in msg


def test_graph_design_template_comment_only_fails():
    body = SCORE + "\n## Graph design\n\n<!-- edges and query -->\n\n## Test Plan\n"
    assert not check(body, RELEVANT)[0]


def test_graph_design_accepts_sparql_namedquery_or_none():
    assert graph_design_ok("Reads campy:OWNS via SELECT ?o WHERE { ?s campy:OWNS ?o }")
    assert graph_design_ok("Writes campy:OWNS; read by `observations.count_owned`")
    assert graph_design_ok("None — CI tooling")
    assert graph_design_ok("**None - docs**")


def test_graph_design_rejects_prose_without_query():
    assert not graph_design_ok("I changed some stuff about edges")
    assert not graph_design_ok("")
    assert not graph_design_ok(None)


def test_graph_design_not_required_off_path():
    assert check(None, IRRELEVANT)[0]


GATE = "| suite | main | branch | gained | lost |\n|---|---|---|---|---|\n| LoCoMo | 60 | 62 | 3 | 1 |\n"


def _se(extra):
    return GD + "## Score effect\n\n" + GATE + extra + "Prediction: LoCoMo +1 to +3\n\n## Test Plan\n"


def test_gate_table_without_targets_line_fails():
    ok, msg = check(_se(""), RELEVANT)
    assert not ok and "Targets in gate" in msg and "gate_slice.py" in msg


def test_gate_table_targets_variants():
    assert check(_se("Targets in gate: 12\n"), RELEVANT)[0]
    assert check(_se("Targets in gate: all\n"), RELEVANT)[0]
    assert check(_se("Targets in gate: none — change is not question-specific\n"), RELEVANT)[0]


def test_gate_table_too_few_targets_fails():
    ok, msg = check(_se("Targets in gate: 4\n"), RELEVANT)
    assert not ok and "below 10" in msg
    assert not check(_se("Targets in gate: none\n"), RELEVANT)[0]


def test_none_reason_section_needs_no_targets_line():
    assert check(GD + "## Score effect\nNone — evaluation tooling only\nPrediction: none — tooling\n", RELEVANT)[0]


# --- step 0e: a prediction before the result -----------------------------------------------------

PRED_BODY = GD + "## Score effect\nNone — refactor\n{line}\n## Test Plan\n"


def test_prediction_missing_fails_with_pointer():
    ok, msg = check(PRED_BODY.format(line=""), RELEVANT)
    assert not ok and "Prediction:" in msg and "0e" in msg


def test_prediction_variants():
    assert check(PRED_BODY.format(line="Prediction: query hits +20 to +40 of 809"), RELEVANT)[0]
    assert check(PRED_BODY.format(line="**Prediction:** none — no code path reads it"), RELEVANT)[0]
    ok, msg = check(PRED_BODY.format(line="Prediction: none"), RELEVANT)
    assert not ok and "needs a reason" in msg
    assert not check(PRED_BODY.format(line="Prediction:"), RELEVANT)[0]
    assert not check(PRED_BODY.format(line="**Prediction:** none"), RELEVANT)[0]
    assert not check(PRED_BODY.format(line="**Prediction:**"), RELEVANT)[0]


def test_prediction_must_be_in_score_effect_section():
    body = GD + "## Score effect\nNone — refactor\n\n## Test Plan\nPrediction: +5\n"
    assert not check(body, RELEVANT)[0]


def test_prediction_not_required_off_path():
    assert check("## Score effect\nNone — docs\n", IRRELEVANT)[0]
    assert prediction_ok("Prediction: LoCoMo flat")[0] and not prediction_ok("")[0]
