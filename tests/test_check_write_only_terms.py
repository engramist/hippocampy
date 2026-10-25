"""Tests for .github/scripts/check_write_only_terms.py."""
import os
import sys
from types import SimpleNamespace as Q

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"))

import check_write_only_terms as c

NODES = {"Thing": "thing_id STRING,\n  weight DOUBLE,\n  embedding FLOAT[384],\n  PRIMARY KEY (thing_id)"}
RELS = ["CREATE REL TABLE IF NOT EXISTS OWNS (FROM Thing TO Thing, since TIMESTAMP)"]


def test_declared_terms_edges_and_props():
    t = c.declared_terms(NODES, RELS)
    assert t == {"prop:thing_id", "prop:weight", "prop:embedding", "edge:OWNS", "prop:since"}


def test_reads_from_non_mutating_and_where_of_mutating():
    qs = [
        Q(sparql="SELECT ?o WHERE { ?s campy:OWNS ?o }", mutating=False),
        Q(sparql="INSERT { ?s campy:weight 1 } WHERE { ?s campy:since ?x }", mutating=True),
    ]
    assert c.read_names_from_queries(qs) == {"OWNS", "since"}


def test_write_only_is_declared_minus_read():
    wo = c.write_only_terms(c.declared_terms(NODES, RELS), {"OWNS", "weight"})
    assert wo == {"prop:thing_id", "prop:embedding", "prop:since"}


def test_compare_new_and_now_read():
    new, now_read = c.compare({"edge:A", "prop:b"}, {"prop:b", "edge:C"})
    assert new == ["edge:A"] and now_read == ["edge:C"]


def test_python_read_strings(tmp_path):
    d = tmp_path / "campy" / "x"
    d.mkdir(parents=True)
    (d / "m.py").write_text('Q = "SELECT ?o WHERE { ?s campy:OWNS ?o }"\nW = "INSERT { ?s campy:weight 1 }"\n')
    assert c.read_names_from_files(tmp_path) == {"OWNS"}


def test_repo_matches_baseline():
    """The committed baseline is exactly today's write-only set."""
    assert c.main([]) == 0


def test_baseline_roundtrip(tmp_path):
    p = tmp_path / "b.txt"
    c.write_baseline({"edge:B", "prop:a"}, p)
    assert c.load_baseline(p) == {"edge:B", "prop:a"}


def test_fstring_iri_loop_literal_and_path_constant(tmp_path):
    d = tmp_path / "campy" / "x"
    d.mkdir(parents=True)
    (d / "m.py").write_text(
        'ns = "<https://campy.dev/ns#"\\n'
        'UP = "campy:IS_A|campy:BROADER"\\n'
        'def reads():\\n'
        '    for e in ("MENTIONS",):\\n'
        '        q = f"SELECT ?i WHERE {{ ?i {ns}{e}> ?c . ?c {ns}INSTANCE_OF> ?k }}"\\n'
        'def writes():\\n'
        '    return "INSERT DATA { <a> <https://campy.dev/ns#SECRET> 1 }"\\n'
    )
    got = c.read_names_from_files(tmp_path)
    assert {"MENTIONS", "INSTANCE_OF", "IS_A", "BROADER"} <= got
    assert "SECRET" not in got
