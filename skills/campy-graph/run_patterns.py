#!/usr/bin/env python3
"""B516: run the campy-graph SKILL's SPARQL patterns against a COPY of a Campy store.

    python skills/campy-graph/run_patterns.py <copy_of_store_dir> [--subject Andrew]

Opens the store READ-ONLY (same call as scripts/graph_structure_report.py::open_store).
Never point it at ~/.campy or a store a daemon is using: copy the directory first
(`cp -R <store> <scratch>/copy`). Nothing is written.

Each pattern prints its row count and the first rows, so a pattern that returns
nothing because the capture edge is missing shows up as `rows: 0`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyoxigraph as ox

PREFIXES = "PREFIX campy: <https://campy.dev/ns#>\nPREFIX cid: <https://campy.dev/id/>\n"

# A Concept's id is a literal (campy:concept_id), and Observation.subject_id holds that literal.
SUBJECT = "?c a campy:Concept ; campy:text_raw ?subject ; campy:concept_id ?sid ."
LIVE = ("FILTER NOT EXISTS { ?o campy:archived true } "
        "FILTER NOT EXISTS { ?o campy:DEPRECATED_BY ?newer }")

PATTERNS = [
    ("1 count per subject (anchored on the subject)",
     f"""SELECT (COUNT(DISTINCT ?obj) AS ?n) WHERE {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:predicate "owns" ; campy:object_text ?obj .
          {LIVE} }}"""),
    ("2 list the objects of a relation for a subject, with their source turn",
     f"""SELECT ?obj ?quote ?msg ?when WHERE {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:predicate "owns" ;
             campy:object_text ?obj ; campy:evidence_text ?quote ; campy:EVIDENCED_BY ?m .
          ?m campy:message_id ?msg ; campy:occurred_at ?when .
          {LIVE} }} ORDER BY ?when"""),
    ("3 latest value of a functional attribute (Jon / occupation; the older value is DEPRECATED_BY the newer)",
     f"""SELECT ?val ?at WHERE {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:HAS_PROPERTY ?p ;
             campy:attr_value ?val ; campy:observed_at ?at .
          ?p campy:text_raw "occupation" .
          {LIVE} }} ORDER BY DESC(?at) LIMIT 1""", "Jon"),
    ("3b a count that IS captured, as a typed attribute (Audrey / number of pets), newest first",
     f"""SELECT ?val ?at WHERE {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:HAS_PROPERTY ?p ;
             campy:attr_value ?val ; campy:observed_at ?at .
          ?p campy:text_raw "number of pets" .
          {LIVE} }} ORDER BY DESC(?at) LIMIT 3""", "Audrey"),
    ("4a kind closure, NO subject (the B505 shape: counts every instance in the store)",
     """SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {
          ?root a campy:Concept ; campy:text_raw "pet" .
          ?k campy:BROADER* ?root .
          ?x campy:INSTANCE_OF ?k . }"""),
    ("4b kind closure anchored on the subject (Observations about the subject that mention an instance of the kind)",
     """SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {
          ?c a campy:Concept ; campy:text_raw ?subject ; campy:concept_id ?sid .
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:OBSERVATION_ABOUT ?x .
          ?root a campy:Concept ; campy:text_raw "pet" .
          ?k campy:BROADER* ?root .
          ?x campy:INSTANCE_OF ?k . FILTER(?x != ?c) }"""),
    ("5 every answer row linked back to its source turn (Observation -> EVIDENCED_BY -> Message)",
     f"""SELECT (COUNT(*) AS ?n) (COUNT(?m) AS ?with_message) WHERE {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:predicate "owns" .
          OPTIONAL {{ ?o campy:EVIDENCED_BY ?m . ?m campy:text_raw ?turn }} {LIVE} }}"""),
    ("6 abstain: no edge, no answer (ASK for a typed residence value)",
     f"""ASK {{
          {SUBJECT}
          ?o a campy:Observation ; campy:subject_id ?sid ; campy:HAS_PROPERTY ?p ; campy:attr_value ?v .
          ?p campy:text_raw "residence" . {LIVE} }}"""),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("store")
    ap.add_argument("--subject", default="Andrew")
    a = ap.parse_args()
    p = Path(a.store).expanduser()
    db = p / "brain.db" if (p / "brain.db").exists() else p
    store = ox.Store.read_only(str(db))
    for title, body, *own in PATTERNS:
        subject = own[0] if own else a.subject      # a pattern may pin its own subject
        res = store.query(PREFIXES + body.replace("?subject", f'"{subject}"'))
        print(f"## {title}  [subject={subject}]")
        if isinstance(res, ox.QueryBoolean):
            print(f"   ASK -> {bool(res)}")
            continue
        rows = [tuple(str(getattr(v, 'value', v))[:60] for v in r) for r in res]
        for r in rows[:6]:
            print("   ", r)
        print(f"   rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
