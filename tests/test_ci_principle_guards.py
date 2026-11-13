"""Tests for the P2 regex ratchet and the P4 benchmark-name guard (CI scripts)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


names = _load("check_benchmark_names")
ratchet = _load("check_answer_regex_ratchet")


def test_benchmark_name_in_a_used_string_is_a_hit():
    assert names.find_hits('if dataset == "locomo":\n    k = 3\n') == [(1, "locomo")]


def test_benchmark_name_in_an_identifier_is_a_hit():
    assert names.find_hits("def tune_for_longmemeval(x):\n    return x\n") == [(1, "longmemeval")]


def test_conversation_id_is_a_hit():
    assert names.find_hits('SKIP = {"conv-26"}\n') == [(1, "conv-26")]


def test_comments_and_docstrings_are_not_hits():
    src = '"""Gate: LoCoMo 28 gained."""\n# DMR 0.62\ndef f():\n    """LongMemEval note."""\n    return 1\n'
    assert names.find_hits(src) == []


def test_unrelated_words_are_not_hits():
    assert names.find_hits('x = "conversation"\ny = "admire"\n') == []


def test_package_is_clean():
    assert names.scan(ROOT) == []


def test_ratchet_counts_call_sites_and_skips_comment_lines(tmp_path):
    d = tmp_path / "campy" / "brain" / "thalamus"
    d.mkdir(parents=True)
    (d / "a.py").write_text("import re\nA = re.compile('x')\n# re.search('y', z)\nb = re.sub('a', 'b', c)\n")
    total, per_file = ratchet.scan(tmp_path)
    assert total == 2 and per_file == {"campy/brain/thalamus/a.py": 2}


def test_ratchet_fails_only_on_increase():
    assert ratchet.check(5, 4)[0] is False
    assert ratchet.check(4, 4)[0] is True
    assert ratchet.check(3, 4)[0] is True


def test_baseline_matches_tree():
    import json
    total, _ = ratchet.scan(ROOT)
    baseline = json.loads((ROOT / "scripts" / "answer_regex_baseline.json").read_text())["regex_call_sites"]
    assert total <= baseline
