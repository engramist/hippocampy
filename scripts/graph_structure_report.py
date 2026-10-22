#!/usr/bin/env python3
"""B507: graph structure report -- the structure measure tracked next to the benchmark score.

    python scripts/graph_structure_report.py <store_dir>... [-v] [--json]

Each <store_dir> is a Campy home (it holds brain.db) or a brain.db directory.
Stores are opened READ-ONLY; nothing is written. Point it at a copy of any
store a daemon or benchmark is still using.

Per store and pooled, it reports:
  * SHACL conformance per node type (Observation, Message, Concept) against
    campy/brain/hippocampus/shapes/campy_shapes.ttl, with the top failing shapes;
  * % of Observations linked to a Concept (OBSERVATION_ABOUT);
  * % of user Messages that MENTION a Concept (0 until B503 adds the edge);
  * Concept count, the share that are fragments (stopword-only or 1-2 chars), and
    the redundant-duplicate rate (labels equal after normalisation); both read the
    SKOS prefLabel (B508: campy:text_raw is its stored form, see shapes/campy_vocab.ttl);
  * B508, the kind vocabulary: number of kinds (in campy:KindScheme, or used as a kind
    by INSTANCE_OF / skos:broader / the legacy IS_A), the share of kinds with at least
    one altLabel, the duplicate-kind rate (kinds that share a normalised prefLabel or
    altLabel with another kind: what consolidation should drive to 0), and the share
    of entities (gist_class "Entity") that have an instance-of kind;
  * % of has_attribute Observations whose object parses as "name: value", and the
    count whose object is a stringified dict/list (B506).

Conformance counts only sh:Violation results; sh:Warning results are listed apart.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NS = "https://campy.dev/ns#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
NODE_TYPES = ("Observation", "Message", "Concept")
SKOS = "http://www.w3.org/2004/02/skos/core#"
NAME_VALUE_RE = re.compile(r"^[^:{}\[\]]+:\s*\S")      # mirrors AttributeObjectIsNameValue in the shapes
STRUCTURED_RE = re.compile(r"^\s*[\{\[]")              # mirrors "object_text not a structure"
_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")


def normalise_label(label: str | None) -> str:
    """Case-folded, punctuation-free, whitespace-collapsed, leading article dropped."""
    text = re.sub(r"[\W_]+", " ", (label or "").casefold()).strip()
    return _ARTICLE_RE.sub("", text)


def open_store(path: str | Path):
    import pyoxigraph as ox

    p = Path(path).expanduser()
    db = p / "brain.db" if (p / "brain.db").exists() else p
    if not db.exists():
        raise FileNotFoundError(f"no brain.db under {p}")
    return ox.Store.read_only(str(db))


def _rows(store, query: str) -> list[tuple]:
    return [tuple(v.value if hasattr(v, "value") else str(v) for v in row) for row in store.query(query)]


def _count(store, query: str) -> int:
    rows = _rows(store, query)
    return int(rows[0][0]) if rows else 0


def to_rdflib(store):
    """The slice of the store the shapes need: every rdf:type triple, plus all triples of
    Observation / Message / Concept / Label / Session nodes (reified/quoted triples skipped)."""
    import pyoxigraph as ox
    from rdflib import BNode, Graph, Literal, URIRef

    g = Graph()
    keep = {NS + t for t in NODE_TYPES + ("Label", "Session")}

    def conv(term):
        if isinstance(term, ox.NamedNode):
            return URIRef(term.value)
        if isinstance(term, ox.Literal):
            if term.language:
                return Literal(term.value, lang=term.language)
            if term.datatype is None or term.datatype.value == XSD_STRING:
                return Literal(term.value)
            return Literal(term.value, datatype=URIRef(term.datatype.value))
        return None

    subjects = []
    for q in store.quads_for_pattern(None, ox.NamedNode(RDF_TYPE), None, None):
        if isinstance(q.subject, ox.NamedNode) and isinstance(q.object, ox.NamedNode):
            g.add((URIRef(q.subject.value), URIRef(RDF_TYPE), URIRef(q.object.value)))
            if q.object.value in keep:
                subjects.append(q.subject)
    for s in subjects:
        for q in store.quads_for_pattern(s, None, None, None):
            o = conv(q.object)
            if o is not None:
                g.add((URIRef(q.subject.value), URIRef(q.predicate.value), o))
    return g


def kind_metrics(g) -> dict:
    """B508 kind-vocabulary numerators/denominators from a SKOS-projected rdflib graph."""
    from rdflib import Namespace, URIRef
    from rdflib.namespace import RDF

    from campy.brain.hippocampus.concept_links import norm_key

    campy, skos = Namespace(NS), Namespace(SKOS)
    kinds = set(g.subjects(skos.inScheme, campy.KindScheme))
    kinds |= set(g.objects(None, campy.INSTANCE_OF)) | set(g.objects(None, campy.IS_A))
    kinds |= set(g.subjects(skos.broader, None)) | set(g.objects(None, skos.broader))
    kinds = {k for k in kinds if (k, RDF.type, campy.Concept) in g}
    # duplicate kinds: union kinds that share a normalised pref/alt label
    parent = {k: k for k in kinds}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[str, URIRef] = {}
    with_alt = 0
    for k in kinds:
        labels = [str(t) for t in g.objects(k, skos.prefLabel)]
        alts = [str(t) for t in g.objects(k, skos.altLabel)]
        with_alt += bool(alts)
        for key in {norm_key(x) for x in labels + alts} - {""}:
            if key in owner:
                parent[find(k)] = find(owner[key])
            else:
                owner[key] = k
    components = len({find(k) for k in kinds})
    entities = [c for c in g.subjects(RDF.type, campy.Concept)
                if str(g.value(c, campy.gist_class) or "") == "Entity" and c not in kinds]
    with_kind = sum(1 for c in entities
                    if (c, campy.INSTANCE_OF, None) in g or (c, campy.IS_A, None) in g)
    return {"kinds": len(kinds), "kinds_with_alt": with_alt, "kinds_duplicate": len(kinds) - components,
            "entities": len(entities), "entities_with_kind": with_kind}


def measure(path: str | Path, *, shacl: bool = True) -> dict:
    """All metrics for one store, as raw numerators/denominators (poolable)."""
    from campy.brain.hippocampus.shapes import validator

    store = open_store(path)
    q = lambda body: _count(store, f"PREFIX campy: <{NS}> SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {{ {body} }}")
    m: dict = {"store": str(path)}
    m["observations"] = q("?x a campy:Observation")
    m["obs_linked"] = q("?x a campy:Observation ; campy:OBSERVATION_ABOUT ?c")
    m["user_messages"] = q('?x a campy:Message ; campy:role "user"')
    m["user_msgs_mention"] = q('?x a campy:Message ; campy:role "user" ; campy:MENTIONS ?c')

    g = validator.skos_project(to_rdflib(store))       # the SKOS view: prefLabel, altLabel, broader, inScheme
    from rdflib import Namespace
    labels = [str(t) for t in g.objects(None, Namespace(SKOS).prefLabel)]
    m["concepts"] = q("?x a campy:Concept")
    m["concept_fragments"] = sum(1 for lab in labels if validator.is_fragment(lab))
    norm = Counter(normalise_label(lab) for lab in labels)
    m["concept_redundant"] = sum(n - 1 for n in norm.values() if n > 1)

    objs = [r[0] for r in _rows(store, f'PREFIX campy: <{NS}> SELECT ?o WHERE {{ ?x a campy:Observation ; campy:predicate "has_attribute" ; campy:object_text ?o }}')]
    m["has_attribute"] = len(objs)
    m["attr_name_value"] = sum(1 for o in objs if NAME_VALUE_RE.match(o))
    m["attr_structured"] = sum(1 for o in objs if STRUCTURED_RE.match(o))

    m.update(kind_metrics(g))

    m["shacl"] = {}
    if shacl:
        report, _ = validator.validate_graph(g)
        from rdflib import URIRef
        type_of = {}
        for t in NODE_TYPES:
            for s in g.subjects(URIRef(RDF_TYPE), URIRef(NS + t)):
                type_of[str(s)] = t
        bad: dict[str, set] = defaultdict(set)
        warn: dict[str, set] = defaultdict(set)
        fails: dict[str, Counter] = defaultdict(Counter)
        for f in report.failures:
            t = type_of.get(f.focus or "")
            if t is None:
                continue
            if f.severity == "Violation":
                bad[t].add(f.focus)
                fails[t][f.key] += 1
            else:
                warn[t].add(f.focus)
        for t in NODE_TYPES:
            total = sum(1 for v in type_of.values() if v == t)
            m["shacl"][t] = {"total": total, "nonconforming": len(bad[t]), "warned": len(warn[t]),
                             "top": dict(fails[t].most_common())}
    return m


def pool(results: list[dict]) -> dict:
    out: dict = {"stores": len(results), "shacl": {t: {"total": 0, "nonconforming": 0, "warned": 0, "top": Counter()} for t in NODE_TYPES}}
    for key in ("observations", "obs_linked", "user_messages", "user_msgs_mention", "concepts", "concept_fragments",
                "concept_redundant", "has_attribute", "attr_name_value", "attr_structured",
                "kinds", "kinds_with_alt", "kinds_duplicate", "entities", "entities_with_kind"):
        out[key] = sum(r[key] for r in results)
    for r in results:
        for t, d in r["shacl"].items():
            p = out["shacl"][t]
            p["total"] += d["total"]
            p["nonconforming"] += d["nonconforming"]
            p["warned"] += d["warned"]
            p["top"].update(d["top"])
    return out


def pct(n: int, d: int) -> str:
    return "n/a" if not d else f"{100.0 * n / d:.1f}%"


def conformance(d: dict) -> str:
    return "n/a" if not d["total"] else f"{100.0 * (d['total'] - d['nonconforming']) / d['total']:.1f}%"


def render_row(name: str, r: dict) -> list[str]:
    sh = r["shacl"]
    return [
        name,
        *(conformance(sh[t]) if sh else "-" for t in NODE_TYPES),
        pct(r["obs_linked"], r["observations"]),
        pct(r["user_msgs_mention"], r["user_messages"]),
        str(r["concepts"]),
        pct(r["concept_fragments"], r["concepts"]),
        pct(r["concept_redundant"], r["concepts"]),
        pct(r["attr_name_value"], r["has_attribute"]),
        str(r["kinds"]),
        pct(r["kinds_with_alt"], r["kinds"]),
        pct(r["kinds_duplicate"], r["kinds"]),
        pct(r["entities_with_kind"], r["entities"]),
    ]


HEADER = ["store", "SHACL Obs", "SHACL Msg", "SHACL Concept", "Obs->Concept", "UserMsg MENTIONS",
          "Concepts", "fragment", "dup", "attr name:value",
          "kinds", "kinds w/ altLabel", "dup kinds", "entities w/ kind"]


def table(rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(HEADER) + " |", "|" + "|".join("---" for _ in HEADER) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def top_failures(p: dict, limit: int = 5) -> list[str]:
    lines = []
    for t in NODE_TYPES:
        d = p["shacl"][t]
        top = d["top"].most_common(limit) if isinstance(d["top"], Counter) else list(d["top"].items())[:limit]
        if top:
            lines.append(f"  {t} ({d['nonconforming']}/{d['total']} nonconforming): " +
                         ", ".join(f"{k} x{n}" for k, n in top))
        if d["warned"]:
            lines.append(f"  {t} warnings: {d['warned']} node(s)")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stores", nargs="+", help="store directories (Campy homes or brain.db dirs)")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-store top failing shapes")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of tables")
    ap.add_argument("--no-shacl", action="store_true", help="skip SHACL validation (faster; the count metrics are still computed)")
    args = ap.parse_args(argv)

    results, skipped = [], []
    for s in args.stores:
        try:
            results.append(measure(s, shacl=not args.no_shacl))
        except Exception as exc:   # an unreadable store must not hide the others
            skipped.append((s, f"{type(exc).__name__}: {exc}"))
    if not results:
        for s, why in skipped:
            print(f"skipped {s}: {why}", file=sys.stderr)
        return 1
    pooled = pool(results)
    if args.json:
        pooled["shacl"] = {t: {**d, "top": dict(d["top"])} for t, d in pooled["shacl"].items()}
        print(json.dumps({"stores": results, "pooled": pooled, "skipped": skipped}, indent=2, default=str))
        return 0

    rows = [render_row(Path(r["store"]).name, r) for r in results]
    if len(results) > 1:
        rows.append(render_row(f"POOLED ({len(results)} stores)", pooled))
    print(table(rows))
    print(f"\nObservations {pooled['observations']}, has_attribute {pooled['has_attribute']} "
          f"(stringified dict/list objects: {pooled['attr_structured']}), Messages(user) {pooled['user_messages']}")
    print("Top failing shapes (pooled):")
    print("\n".join(top_failures(pooled)) or "  none")
    if args.verbose:
        for r in results:
            print(f"\n{Path(r['store']).name}:")
            print("\n".join(top_failures(pool([r]))) or "  none")
    for s, why in skipped:
        print(f"skipped {s}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
