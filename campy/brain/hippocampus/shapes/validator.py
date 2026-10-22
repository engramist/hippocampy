"""
campy/brain/hippocampus/shapes/validator.py -- B507: apply the SHACL shapes.

Two uses, one shapes file (`campy_shapes.ttl`):

* `validate_observation_candidate` turns ONE candidate Observation, plus the
  evidence Message it links to, into a tiny RDF graph and validates it. The
  write gate in `observations.record_observation` calls it (flag
  `[observations] shacl_gate` / `CAMPY_SHACL_GATE`, default off).
* `validate_graph` validates any rdflib graph; scripts/graph_structure_report.py
  uses it on whole stores.

The shapes graph is parsed once (`load_shapes`, cached). pyshacl and rdflib are
imported lazily, so a process that never turns the gate on never imports them.

The candidate graph reproduces the RDF datatypes the store writes
(graph/queries/observations.py create_observation): xsd:dateTime for the time
columns, xsd:decimal for confidence, xsd:integer for offsets, xsd:boolean for
flags, plain strings otherwise.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

NS = "https://campy.dev/ns#"
SHAPES_PATH = Path(__file__).with_name("campy_shapes.ttl")
SH = "http://www.w3.org/ns/shacl#"

# Words that carry no concept on their own. A label made only of these (and
# punctuation) is a fragment, not a name. First-person pronouns ARE here: a
# Concept labelled "I" is a fragment; an Observation's *subject* "I" is fine and
# is never checked against this list (only object_text and Concept labels are).
LABEL_STOPWORDS = frozenset("""
a an the and or but nor so if then than as of to in on at for with by from into
over about up down out off again is are was were be been being am do does did
has have had having would could should will can may might must shall
it its it's this that these those there here what which who whom whose
i me my mine myself you your yours he him his she her hers we us our ours they them their theirs
not no yes too very just also some any each other such only own same more most both few all
""".split())


def stopword_only_regex() -> str:
    """Regex matching a string made only of stopwords and non-word characters
    (including the empty string). Used with case-insensitive search."""
    words = "|".join(sorted((re.escape(w) for w in LABEL_STOPWORDS), key=lambda w: (-len(w), w)))
    return rf"^(?:[\W_]*\b(?:{words})\b)*[\W_]*$"


def is_stopword_only(label: str | None) -> bool:
    return re.search(stopword_only_regex(), label or "", re.IGNORECASE) is not None


def is_fragment(label: str | None) -> bool:
    """A Concept label that is stopword-only or 1-2 characters long."""
    text = (label or "").strip()
    return len(text) <= 2 or is_stopword_only(text)


@dataclass(frozen=True)
class ShapeFailure:
    shape: str            # the shape / property name, e.g. "predicate", "QuoteIsSpanOfEvidence"
    component: str        # the constraint component, e.g. "InConstraintComponent"
    path: str | None
    message: str
    severity: str         # "Violation" | "Warning" | "Info"
    focus: str | None = None   # the focus node's IRI

    @property
    def key(self) -> str:
        return f"{self.shape} [{self.component}]"


@dataclass
class ShaclReport:
    conforms: bool
    failures: list[ShapeFailure] = field(default_factory=list)

    def shapes(self) -> list[str]:
        return [f.key for f in self.failures]


_lock = threading.Lock()


@lru_cache(maxsize=1)
def load_shapes() -> Any:
    """The parsed shapes graph (cached for the process)."""
    from rdflib import Graph

    text = SHAPES_PATH.read_text(encoding="utf-8").replace("@@STOPWORD_ONLY@@", _turtle_escape(stopword_only_regex()))
    g = Graph()
    g.parse(data=text, format="turtle")
    return g


def _turtle_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _local(term: Any) -> str:
    s = str(term)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def validate_graph(data_graph: Any, *, allow_warnings: bool = True) -> tuple[ShaclReport, Any]:
    """Validate `data_graph`; returns (report, the raw pyshacl results graph)."""
    from pyshacl import validate
    from rdflib import Namespace, URIRef
    from rdflib.namespace import RDF

    shapes = load_shapes()
    with _lock:   # pyshacl mutates internal caches on the shapes graph
        conforms, results_graph, _ = validate(
            data_graph, shacl_graph=shapes, inference="none", abort_on_first=False,
            allow_warnings=allow_warnings, meta_shacl=False, advanced=True, debug=False,
        )
    sh = Namespace(SH)
    shape_name = {}
    for s, _, n in shapes.triples((None, sh.name, None)):
        shape_name[s] = str(n)
    failures: list[ShapeFailure] = []
    for r in results_graph.subjects(RDF.type, sh.ValidationResult):
        src = results_graph.value(r, sh.sourceShape)
        comp = results_graph.value(r, sh.sourceConstraintComponent)
        path = results_graph.value(r, sh.resultPath)
        msg = results_graph.value(r, sh.resultMessage)
        sev = results_graph.value(r, sh.resultSeverity)
        constraint = results_graph.value(r, sh.sourceConstraint)
        if constraint is not None and (constraint, sh.name, None) in shapes:
            name = str(shapes.value(constraint, sh.name))     # a named SPARQL constraint
        elif src in shape_name:
            name = shape_name[src]
        elif path is not None:
            name = _local(path)
        else:
            name = _local(src) if isinstance(src, URIRef) else "shape"
        failures.append(ShapeFailure(
            shape=name, component=_local(comp) if comp else "", path=_local(path) if path else None,
            message=str(msg) if msg else "", severity=_local(sev) if sev else "Violation",
            focus=str(results_graph.value(r, sh.focusNode)) if results_graph.value(r, sh.focusNode) is not None else None,
        ))
    return ShaclReport(conforms=bool(conforms), failures=failures), results_graph


# --- one candidate Observation ----------------------------------------------------

def _dt(value: Any) -> Any:
    """An xsd:dateTime literal from a datetime or ISO string; None if unusable."""
    from rdflib import Literal
    from rdflib.namespace import XSD

    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return Literal(value, datatype=XSD.dateTime)   # kept as-is so the datatype/shape check reports it
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return Literal(value.isoformat().replace("+00:00", "Z"), datatype=XSD.dateTime)
    return Literal(str(value), datatype=XSD.dateTime)


def candidate_graph(fields: Mapping[str, Any], message: Mapping[str, Any] | None) -> Any:
    """The tiny graph for one Observation (fields = the create_observation
    parameters) and the evidence Message it links to."""
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, XSD

    campy = Namespace(NS)
    g = Graph()
    o = URIRef(f"https://campy.dev/id/Observation/{fields.get('observation_id') or 'candidate'}")
    g.add((o, RDF.type, campy.Observation))

    def s(col: str) -> None:
        v = fields.get(col)
        if v is not None:
            g.add((o, campy[col], Literal(str(v))))

    for col in ("observation_id", "subject_text", "subject_id", "predicate", "object_text",
                "object_id", "event_text", "time_text", "time_precision", "speaker",
                "polarity", "extraction_method", "rule_version", "evidence_text",
                "evidence_ref"):
        s(col)
    conf = fields.get("confidence")
    if conf is not None:
        g.add((o, campy.confidence, Literal(str(Decimal(repr(float(conf)))), datatype=XSD.decimal)))
    for col in ("evidence_start", "evidence_end"):
        if fields.get(col) is not None:
            g.add((o, campy[col], Literal(int(fields[col]), datatype=XSD.integer)))
    for col in ("observed_at", "time_start", "time_end"):
        lit = _dt(fields.get(col))
        if lit is not None:
            g.add((o, campy[col], lit))
    g.add((o, campy.archived, Literal(False, datatype=XSD.boolean)))

    if message is not None:
        mid = message.get("message_id") or fields.get("evidence_ref") or "message"
        m = URIRef(f"https://campy.dev/id/Message/{mid}")
        g.add((m, RDF.type, campy.Message))
        g.add((m, campy.message_id, Literal(str(mid))))
        if message.get("text_raw") is not None:
            g.add((m, campy.text_raw, Literal(str(message["text_raw"]))))
        if message.get("role") is not None:
            g.add((m, campy.role, Literal(str(message["role"]))))
        g.add((m, campy.archived, Literal(bool(message.get("archived") or False), datatype=XSD.boolean)))
        g.add((o, campy.EVIDENCED_BY, m))
    return g


def validate_observation_candidate(fields: Mapping[str, Any], message: Mapping[str, Any] | None) -> ShaclReport:
    """Validate one candidate Observation (and its evidence Message) against the shapes."""
    report, _ = validate_graph(candidate_graph(fields, message))
    return report


def blocking(report: ShaclReport) -> list[ShapeFailure]:
    """The failures that stop a write (Violations; Warnings never block)."""
    return [f for f in report.failures if f.severity == "Violation"]
