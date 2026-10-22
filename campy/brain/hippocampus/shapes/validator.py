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
VOCAB_PATH = Path(__file__).with_name("campy_vocab.ttl")     # B508: Campy <-> SKOS alignment
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
KIND_SCHEME_VALUE = "kind"                                   # Concept.kind_scheme of a kind
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


@lru_cache(maxsize=1)
def load_vocab() -> Any:
    """The parsed Campy <-> SKOS alignment (campy_vocab.ttl), cached."""
    from rdflib import Graph

    g = Graph()
    g.parse(VOCAB_PATH, format="turtle")
    return g


def skos_project(data_graph: Any) -> Any:
    """Add, in place, the SKOS view of every Campy Concept in `data_graph` and return it.
    Idempotent; only adds triples.

      rdf:type skos:Concept                         every campy:Concept
      skos:prefLabel                                from campy:text_raw
      skos:altLabel                                 from each HAS_ALT_LABEL Label's text
      skos:inScheme campy:KindScheme                when Concept.kind_scheme = 'kind'
      skos:broader / skos:closeMatch                for each stored campy edge declared
                                                    rdfs:subPropertyOf one in campy_vocab.ttl
      skos:narrower, symmetric skos:closeMatch      the inverses SKOS defines
    A graph that already states these in SKOS is left as it is."""
    from rdflib import Namespace, URIRef
    from rdflib.namespace import RDF, RDFS

    campy, skos = Namespace(NS), Namespace(SKOS_NS)
    g = data_graph
    sub_of = [(p, q) for p, q in load_vocab().subject_objects(RDFS.subPropertyOf)
              if str(q).startswith(SKOS_NS)]
    for c in set(g.subjects(RDF.type, campy.Concept)) | set(g.subjects(RDF.type, campy.AttributeProperty)):
        g.add((c, RDF.type, skos.Concept))        # B509: an attribute property is a SKOS concept too
        if (c, RDF.type, campy.AttributeProperty) in g:
            g.add((c, skos.inScheme, campy.PropertyScheme))
        for t in g.objects(c, campy.text_raw):
            g.add((c, skos.prefLabel, t))
        for label in g.objects(c, campy.HAS_ALT_LABEL):
            for t in g.objects(label, campy.text):
                g.add((c, skos.altLabel, t))
        if any(str(v) == KIND_SCHEME_VALUE for v in g.objects(c, campy.kind_scheme)):
            g.add((c, skos.inScheme, campy.KindScheme))
    for p, q in sub_of:
        for s_, o in list(g.subject_objects(p)):
            g.add((s_, q, o))
    for s_, o in list(g.subject_objects(skos.broader)):
        g.add((o, skos.narrower, s_))
    for s_, o in list(g.subject_objects(skos.closeMatch)):
        g.add((o, skos.closeMatch, s_))
    return g


# --- B509: OWL view of attribute properties and their values ----------------------------

PROPERTY_BASE = NS.replace("ns#", "id/AttributeProperty/")
SUBJECT_BASE = NS.replace("ns#", "id/AttributeSubject/")
SLOT_BASE = NS.replace("ns#", "id/FunctionalSlot/")
CONCEPT_BASE = NS.replace("ns#", "id/Concept/")


def _truthy_false(values: Any) -> bool:
    return any(str(v).lower() == "false" for v in values)


def _value_term(g: Any, o: Any) -> Any:
    """The RDF value of one attribute Observation: the Concept it names, else its typed
    literal (xsd:decimal for number/money amounts, xsd:duration for seconds, xsd:date /
    xsd:dateTime for a date), else its text normalised (case and spacing)."""
    from rdflib import Literal, Namespace, URIRef
    from rdflib.namespace import XSD

    campy = Namespace(NS)
    one = lambda p: next(iter(g.objects(o, campy[p])), None)
    ref = one("attr_value_ref")
    if ref is not None:
        return URIRef(CONCEPT_BASE + str(ref))
    num, unit, when, text = one("attr_value_num"), one("attr_value_unit"), one("attr_value_time"), one("attr_value")
    kind = str(one("attr_value_kind") or "")
    if num is not None:
        amount = format(Decimal(repr(float(num))).normalize(), "f")
        if kind == "duration" or (kind == "clock" and str(unit) == "second"):
            return Literal(f"PT{int(float(num))}S", datatype=XSD.duration)
        if kind == "money":
            return Literal(f"{amount} {unit or ''}".strip())
        return Literal(amount, datatype=XSD.decimal)
    if when is not None:
        t = str(when)
        return Literal(t[:10], datatype=XSD.date) if t[11:19] in ("", "00:00:00") else Literal(t, datatype=XSD.dateTime)
    return Literal(" ".join(str(text if text is not None else "").lower().split()))


def owl_project(data_graph: Any) -> Any:
    """Add, in place, the OWL view of attribute properties and return the graph. Idempotent.

      owl:DatatypeProperty / owl:ObjectProperty     each campy:AttributeProperty, by prop_type
      owl:FunctionalProperty                        the axioms campy_vocab.ttl states for its seed
                                                    properties (same IRI), and any property whose
                                                    functional_basis is set (modifier, confirmed)
      <subject> <property> <value>                  each LIVE (not archived, not superseded),
                                                    asserted Observation with a HAS_PROPERTY edge;
                                                    the subject is a campy:AttributeSubject keyed
                                                    like the supersession rule (resolved id, else
                                                    the text with first-person forms by speaker)
      campy:FunctionalSlot                          one per (subject, functional property), with
                                                    campy:slotValue for every live value: SHACL
                                                    maxCount 1 on it is "one live value"
    """
    from hashlib import sha1
    from urllib.parse import quote

    from rdflib import Literal, Namespace, URIRef
    from rdflib.namespace import OWL, RDF

    from campy.brain.hippocampus import observation_keys as ok

    campy = Namespace(NS)
    g = data_graph
    props = set(g.subjects(RDF.type, campy.AttributeProperty))
    if not props:
        return g
    vocab = load_vocab()
    for p in props:
        for t in vocab.objects(p, RDF.type):
            g.add((p, RDF.type, t))
        kind = str(next(iter(g.objects(p, campy.prop_type)), "datatype"))
        g.add((p, RDF.type, OWL.ObjectProperty if kind == "object" else OWL.DatatypeProperty))
        if next(iter(g.objects(p, campy.functional_basis)), None) is not None:
            g.add((p, RDF.type, OWL.FunctionalProperty))
    functional = {p for p in props if (p, RDF.type, OWL.FunctionalProperty) in g}
    for o in set(g.subjects(campy.HAS_PROPERTY, None)):
        if _truthy_false(g.objects(o, campy.archived)) is False or (o, campy.superseded_by, None) in g:
            continue
        if str(next(iter(g.objects(o, campy.polarity)), "")) != "asserted":
            continue
        for p in g.objects(o, campy.HAS_PROPERTY):
            sid = next(iter(g.objects(o, campy.subject_id)), None)
            if sid is not None:
                key = f"id:{sid}"
            else:
                key = ok.subject_text_key(str(next(iter(g.objects(o, campy.subject_text)), "")),
                                          str(next(iter(g.objects(o, campy.speaker)), "")))
            subj = URIRef(SUBJECT_BASE + quote(key, safe=""))
            value = _value_term(g, o)
            g.add((subj, RDF.type, campy.AttributeSubject))
            g.add((subj, p, value))
            if p in functional:
                slot = URIRef(SLOT_BASE + sha1(f"{subj}|{p}".encode()).hexdigest()[:20])
                g.add((slot, RDF.type, campy.FunctionalSlot))
                g.add((slot, campy.slotSubject, subj))
                g.add((slot, campy.slotProperty, p))
                g.add((slot, campy.slotValue, value))
    return g


# --- B509: reasoning checks (report only; nothing here edits the store) ---------------------

@dataclass
class ReasoningReport:
    broader_cycles: list[list[str]] = field(default_factory=list)       # strongly connected groups, any length
    redundant_broader: list[tuple[str, str]] = field(default_factory=list)   # (narrower, broader) implied by a longer path
    inconsistencies: list[str] = field(default_factory=list)            # owlrl: what the axioms forbid


def _broader_edges(g: Any) -> dict[str, set[str]]:
    from rdflib import Namespace

    skos = Namespace(SKOS_NS)
    edges: dict[str, set[str]] = {}
    for a, b in g.subject_objects(skos.broader):
        edges.setdefault(str(a), set()).add(str(b))
        edges.setdefault(str(b), set())
    return edges


def broader_cycles(g: Any) -> list[list[str]]:
    """Every skos:broader cycle, of any length: the strongly connected components with more
    than one node, and any node that is its own broader. Tarjan, iterative, O(nodes + edges)."""
    edges = _broader_edges(g)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in sorted(edges):
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(edges[nxt]))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in edges[node]:
                    out.append(sorted(comp))
    return sorted(out)


def redundant_broader(g: Any) -> list[tuple[str, str]]:
    """Transitive-reduction report: a skos:broader edge A -> C is redundant when A reaches C
    by another path (A -> B -> C). Reported, never removed: B508's walk follows the closure,
    so a redundant edge costs nothing at retrieval, only noise in the vocabulary."""
    edges = _broader_edges(g)
    out = []
    for a in sorted(edges):
        for c in sorted(edges[a]):
            if a == c:
                continue
            seen, todo = set(), [b for b in edges[a] if b != c]
            while todo:
                n = todo.pop()
                if n in seen:
                    continue
                if n == c:
                    out.append((a, c))
                    break
                seen.add(n)
                todo.extend(edges.get(n, ()))
    return out


def owl_inconsistencies(g: Any) -> list[str]:
    """What the OWL 2 RL axioms of campy_vocab.ttl forbid, found by a reasoner (owlrl) over a
    reasoning VIEW of the projected graph (the vocabulary, the Concept/property edges and the
    attribute value triples only, never the Observation text): a pair that is both INSTANCE_OF
    and BROADER (owl:propertyDisjointWith). (Two live values of a functional property are found by
    SHACL, FunctionalSlotShape: OWL RL only derives owl:sameAs from them, it does not object to
    two different literals.) Messages are strings."""
    import owlrl
    from rdflib import Graph, Namespace
    from rdflib.namespace import OWL, RDF

    campy = Namespace(NS)
    view = Graph()
    for t in load_vocab():
        view.add(t)
    edge_preds = [campy.BROADER, campy.INSTANCE_OF, campy.CLOSE_MATCH]
    for p in edge_preds:
        for t in g.triples((None, p, None)):
            view.add(t)
    props = set(g.subjects(RDF.type, campy.AttributeProperty))
    for p in props:
        for t in g.triples((p, RDF.type, None)):
            view.add(t)
    for subj in g.subjects(RDF.type, campy.AttributeSubject):
        for pr, v in g.predicate_objects(subj):
            if pr in props:
                view.add((subj, pr, v))
    closure = owlrl.OWLRL_Semantics(view, False, False, False)
    closure.closure()
    closure.flush_stored_triples()
    return [str(m) for m in closure.error_messages]


def reasoning_report(data_graph: Any, *, owl: bool = True) -> ReasoningReport:
    """The broader-cycle check (any length), the transitive-reduction report and, when `owl`,
    the owlrl consistency check, over the SKOS/OWL projection of `data_graph`."""
    g = owl_project(skos_project(data_graph))
    rep = ReasoningReport(broader_cycles=broader_cycles(g), redundant_broader=redundant_broader(g))
    if owl:
        try:
            rep.inconsistencies = owl_inconsistencies(g)
        except ImportError:
            rep.inconsistencies = []
    return rep


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
    skos_project(data_graph)    # B508: shapes are written in SKOS; add the SKOS view of stored Concepts
    owl_project(data_graph)     # B509: attribute properties as OWL properties, their live values, functional slots
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
