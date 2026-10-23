"""
campy/brain/hippocampus/graph/walk_v2.py -- B510: the precise graph walk.

B503's walk gathered every turn linked to a Concept the question names, newest
first, up to 12. Replayed on the R95 store it added ~10 items (~530 tokens) to
111 of 120 LoCoMo questions, 56% of them reached only through a speaker's name or
a concept linked to a tenth of the conversation, 81% from the last two sessions
(newest first, no relevance), and 1% of them were not already in the bundle's
conversation section. The answer model abstained more. This walk does less:

  1. Anchors. A Concept the question names anchors the walk only when it is
       - a typed ENTITY: it has an outgoing INSTANCE_OF / IS_A to a kind (the entity
         extractor typed it), or
       - a KIND with 2..12 instances (INSTANCE_OF / IS_A into it): the kind itself
         anchors nothing, its instances do (so "my dogs" reaches Toby, Buddy, Scout);
     and never when it is a participant (its text equals a Message `speaker`), or
     is linked to more than `max_share` of the store's messages. Untyped Concepts
     ("dates", "my plan", "this class"), kinds with one instance or with more than 12
     ("activity"), and background concepts never anchor.
  2. Covered anchors drop out. An anchor the conversation section already mentions (a
     shown turn MENTIONS it, or its words occur in a shown turn) adds nothing; when
     every anchor is covered the walk returns [].
  3. Only what is missing. Candidates are user turns MENTIONING an anchor (or evidence for
     an Observation ABOUT it); a turn whose message the bundle already shows (conversation
     turn or semantic evidence_ref) is dropped, de-duplicated by SOURCE MESSAGE, never by
     node id. Archived turns, questions, and echoes of the question are not evidence.
  4. Link strength, not recency. Hop 1 (the anchor's own mentions; an instance's mentions
     for a kind) before hop 2 (siblings of an entity under its kind; instances of narrower
     kinds of a kind); then more anchors hit; then higher cosine to the question; then the
     uri. At most `limit` rows (default 4).

The caller (bundle_compiler) turns the rows into the `linked` section and pays for them
out of the conversation section. This module reads the graph; it writes nothing and
never creates a Concept.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_logger = logging.getLogger(__name__)

NS = "<https://campy.dev/ns#"
TYPE_PATH = f"({NS}INSTANCE_OF>|{NS}IS_A>)"
NARROWER_PATH = f"({NS}BROADER>|{NS}IS_A>)+"

DEFAULT_LIMIT = 4
DEFAULT_MAX_SHARE = 0.10
MIN_KIND_INSTANCES = 2
MAX_KIND_INSTANCES = 12
MIN_STORE_FOR_SHARE = 50          # below this many messages a share means nothing (B470's floor)
MAX_HOP2_ENTITIES = 24

_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)?")


@dataclass
class Anchor:
    uri: str
    text: str
    role: str                                   # "entity" | "kind"
    members: list[str] = field(default_factory=list)   # concept uris that carry the links (entity: itself)


def _local(uri: str) -> str:
    return str(uri).rstrip(">").rsplit("/", 1)[-1]


def _lit(v: Any) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def _stem_words(text: str) -> list[str]:
    out = []
    for w in _WORD_RE.findall((text or "").lower().replace("’", "'")):
        w = re.sub(r"'s$", "", w)
        if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return out


def _label_in(texts_words: list[list[str]], label: str) -> bool:
    """Whether `label`'s words occur, in order and adjacent, in any of the word lists."""
    want = _stem_words(label)
    while len(want) > 1 and want[0] in {"a", "an", "the", "my", "our", "your", "his", "her", "their", "its", "this", "that"}:
        want = want[1:]
    if not want:
        return False
    n = len(want)
    return any(words[i:i + n] == want for words in texts_words for i in range(len(words) - n + 1))


def _values(var: str, uris: Iterable[str]) -> str:
    return f"VALUES {var} {{ {' '.join(f'<{u}>' for u in uris)} }}"


def cosine(vector_store: Any, uri: str, q: list[float] | None) -> float:
    """Cosine between the stored embedding of `uri` and `q`; 0.0 when either is missing."""
    if not q or vector_store is None:
        return 0.0
    v = vector_store.get_vector(uri)
    if not v:
        return 0.0
    dot = sum(a * b for a, b in zip(v, q))
    na, nb = math.sqrt(sum(a * a for a in v)), math.sqrt(sum(b * b for b in q))
    return dot / (na * nb) if na and nb else 0.0


class WalkV2:
    """One walk. `gw` is the GraphGateway (its client, vector store and message hydrator)."""

    def __init__(self, gw: Any, params: dict[str, Any]):
        self.gw = gw
        self.run = gw._client._execute_and_collect
        self.p = params
        self.limit = max(0, int(params.get("limit", DEFAULT_LIMIT)))
        self.max_share = float(params.get("max_share", DEFAULT_MAX_SHARE))
        self.min_sim = float(params.get("min_similarity") or 0.0)
        self.rejected: dict[str, str] = {}     # concept uri -> reason (diagnostics, tests)

    # --- store facts ------------------------------------------------------------------

    def _total_messages(self) -> int:
        """Messages in the store: the lexical index's count (as B470), else the graph's."""
        vs = self.gw._vector_store
        try:
            from campy.brain.hippocampus.graph.oxigraph_client import CID_BASE
            n = int(vs.count_documents((f"{CID_BASE}Message/",))) if vs is not None else 0
            if n:
                return n
        except Exception:  # noqa: BLE001
            # The lexical index is optional (absent in some stores and tests);
            # fall through to counting Messages in the graph itself.
            _logger.debug("walk v2: lexical message count unavailable; counting in the graph")
        rows = self.run(f"SELECT (COUNT(?m) AS ?n) WHERE {{ ?m a {NS}Message> }}")
        return int(rows[0]["n"]) if rows else 0

    def _cap(self) -> int:
        """Most messages an anchor may be linked to. Below B470's floor of messages a share means
        nothing and there is no cap."""
        total = self._total_messages()
        return math.ceil(self.max_share * total) if total >= MIN_STORE_FOR_SHARE else 10 ** 9

    def _speakers(self) -> set[str]:
        return {str(r["s"]).strip().lower() for r in self.run(
            f"SELECT DISTINCT ?s WHERE {{ ?m a {NS}Message> ; {NS}speaker> ?s }}")}

    def _texts(self, uris: list[str]) -> dict[str, str]:
        if not uris:
            return {}
        return {str(r["c"]): str(r["t"]) for r in self.run(f"""
            SELECT ?c ?t WHERE {{ {_values('?c', uris)} ?c {NS}text_raw> ?t .
                FILTER NOT EXISTS {{ ?c {NS}archived> true }} }}""")}

    def _degrees(self, uris: list[str]) -> dict[str, int]:
        if not uris:
            return {}
        return {str(r["c"]): int(r["n"]) for r in self.run(f"""
            SELECT ?c (COUNT(DISTINCT ?m) AS ?n) WHERE {{ {_values('?c', uris)} ?m {NS}MENTIONS> ?c }}
            GROUP BY ?c""")}

    def _typed(self, uris: list[str]) -> set[str]:
        if not uris:
            return set()
        return {str(r["c"]) for r in self.run(f"""
            SELECT DISTINCT ?c WHERE {{ {_values('?c', uris)} ?c {TYPE_PATH} ?k }}""")}

    def _instances(self, kinds: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if not kinds:
            return out
        for r in self.run(f"""
            SELECT DISTINCT ?k ?x WHERE {{ {_values('?k', kinds)} ?x {TYPE_PATH} ?k .
                FILTER NOT EXISTS {{ ?x {NS}archived> true }} }}"""):
            out.setdefault(str(r["k"]), []).append(str(r["x"]))
        return out

    # --- 1. anchors -------------------------------------------------------------------

    def select_anchors(self, concept_uris: list[str]) -> list[Anchor]:
        """The strong anchors among the Concepts the question names (see the module docstring)."""
        uris = list(dict.fromkeys(concept_uris))
        if not uris:
            return []
        cap = self._cap()
        speakers = self._speakers()
        texts = self._texts(uris)
        inst = self._instances(uris)
        typed = self._typed(uris)
        anchors: list[Anchor] = []
        pending: list[tuple[str, str, list[str]]] = []      # (uri, text, instance uris) for kinds
        for u in uris:
            text = texts.get(u)
            if text is None:
                self.rejected[u] = "archived-or-unnamed"
            elif text.strip().lower() in speakers:
                self.rejected[u] = "participant"
            elif MIN_KIND_INSTANCES <= len(inst.get(u, ())) <= MAX_KIND_INSTANCES:
                pending.append((u, text, sorted(set(inst[u]))))
            elif len(inst.get(u, ())) > MAX_KIND_INSTANCES:
                self.rejected[u] = "broad-kind"
            elif u in typed:
                anchors.append(Anchor(u, text, "entity", [u]))
            else:
                self.rejected[u] = "untyped"
        # one degree lookup for every entity and every kind instance
        wanted = list(dict.fromkeys([a.uri for a in anchors] + [m for _, _, ms in pending for m in ms]))
        deg = self._degrees(wanted)
        itexts = self._texts([m for _, _, ms in pending for m in ms])

        def ok(u: str, text: str | None) -> bool:
            return (text is not None and text.strip().lower() not in speakers
                    and 1 <= deg.get(u, 0) <= cap)

        kept = []
        for a in anchors:
            if ok(a.uri, a.text):
                kept.append(a)
            else:
                self.rejected[a.uri] = "participant" if a.text.strip().lower() in speakers else (
                    "no-links" if deg.get(a.uri, 0) < 1 else "too-common")
        for u, text, members in pending:
            good = [m for m in members if ok(m, itexts.get(m))]
            if not good:
                self.rejected[u] = "kind-without-usable-instances"
            elif self._reach([u] + members) > cap:
                # the kind and its instances together fill the store ("my dogs" in a
                # conversation about dogs): a topic that saturates cannot discriminate
                self.rejected[u] = "saturating-kind"
            else:
                kept.append(Anchor(u, text, "kind", good))
        return kept

    def _reach(self, concept_uris: list[str]) -> int:
        """Distinct messages that mention any of the concepts."""
        rows = self.run(f"""
            SELECT (COUNT(DISTINCT ?m) AS ?n) WHERE {{ {_values('?c', concept_uris)} ?m {NS}MENTIONS> ?c }}""")
        return int(rows[0]["n"]) if rows else 0

    # --- 2. covered anchors -----------------------------------------------------------

    def uncovered(self, anchors: list[Anchor]) -> list[Anchor]:
        """Drop the anchors (entities; for a kind, its instances) the conversation already mentions."""
        conv_ids = [self._message_uri(i) for i in (self.p.get("conversation_ids") or [])]
        conv_words = [_stem_words(t) for t in (self.p.get("conversation_texts") or [])]
        members = list(dict.fromkeys(m for a in anchors for m in a.members))
        if not members:
            return []
        linked: set[str] = set()
        if conv_ids:
            linked = {str(r["c"]) for r in self.run(f"""
                SELECT DISTINCT ?c WHERE {{ {_values('?m', conv_ids)} {_values('?c', members)}
                    ?m {NS}MENTIONS> ?c }}""")}
        texts = self._texts(members)
        covered = {m for m in members if m in linked or _label_in(conv_words, texts.get(m, ""))}
        out = []
        for a in anchors:
            rest = [m for m in a.members if m not in covered]
            if rest:
                out.append(Anchor(a.uri, a.text, a.role, rest))
            else:
                self.rejected[a.uri] = "covered"
        return out

    @staticmethod
    def _message_uri(msg_id: str) -> str:
        from campy.brain.hippocampus.graph.oxigraph_client import CID_BASE
        s = str(msg_id)
        return s if s.startswith("http") else f"{CID_BASE}Message/{s}"

    # --- 3/4. candidates --------------------------------------------------------------

    def _hop2_entities(self, anchors: list[Anchor], taken: set[str], cap: int,
                       speakers: set[str]) -> list[str]:
        """Siblings of an entity anchor under its kind(s); instances of kinds narrower than a kind anchor."""
        pool: list[str] = []
        entities = [a.uri for a in anchors if a.role == "entity"]
        if entities:
            parents = sorted({str(r["k"]) for r in self.run(f"""
                SELECT DISTINCT ?k WHERE {{ {_values('?e', entities)} ?e {TYPE_PATH} ?k . }}""")})
            for k, xs in self._instances(parents).items():
                if MIN_KIND_INSTANCES <= len(xs) <= MAX_KIND_INSTANCES:   # a kind that is a small collection
                    pool.extend(xs)
        kinds = [a.uri for a in anchors if a.role == "kind"]
        if kinds:
            for r in self.run(f"""
                SELECT DISTINCT ?x WHERE {{ {_values('?c', kinds)} ?k {NARROWER_PATH} ?c . ?x {TYPE_PATH} ?k .
                    FILTER NOT EXISTS {{ ?x {NS}archived> true }} }} LIMIT 200"""):
                pool.append(str(r["x"]))
        pool = [u for u in dict.fromkeys(pool) if u not in taken][:MAX_HOP2_ENTITIES * 3]
        if not pool:
            return []
        deg, texts = self._degrees(pool), self._texts(pool)
        good = [u for u in pool if texts.get(u) and texts[u].strip().lower() not in speakers
                and 1 <= deg.get(u, 0) <= cap]
        return good[:MAX_HOP2_ENTITIES]

    def _participant_sessions(self, concept_uris: list[str], speakers: set[str]) -> set[str] | None:
        """When the question names a participant (a Concept whose text is a Message `speaker`), the
        sessions that participant took part in; None when it names nobody. A turn from a session the
        named person never spoke in is another conversation's, however well it matches a kind."""
        texts = self._texts(list(dict.fromkeys(concept_uris)))
        named = {t.strip().lower() for t in texts.values() if t.strip().lower() in speakers}
        if not named:
            return None
        rows = self.run(f"""
            SELECT DISTINCT ?sp ?s WHERE {{ ?m {NS}speaker> ?sp ; {NS}SENT_IN> ?s . }}""")
        return {str(r["s"]) for r in rows if str(r["sp"]).strip().lower() in named} or None

    def _mentioning(self, concept_uris: list[str]) -> dict[str, set[str]]:
        """message uri -> the given concepts it MENTIONS, or its Observations are ABOUT."""
        out: dict[str, set[str]] = {}
        if not concept_uris:
            return out
        for r in self.run(f"""
            SELECT ?m ?c WHERE {{ {_values('?c', concept_uris)} ?m {NS}MENTIONS> ?c . }} LIMIT 5000"""):
            out.setdefault(str(r["m"]), set()).add(str(r["c"]))
        for r in self.run(f"""
            SELECT ?m ?c WHERE {{ {_values('?c', concept_uris)} ?o {NS}OBSERVATION_ABOUT> ?c ;
                {NS}EVIDENCED_BY> ?m . FILTER NOT EXISTS {{ ?o {NS}archived> true }} }} LIMIT 5000"""):
            out.setdefault(str(r["m"]), set()).add(str(r["c"]))
        return out

    def _cosine(self, uri: str, q: list[float] | None) -> float:
        return cosine(self.gw._vector_store, uri, q)

    def rows(self, concept_uris: list[str]) -> list[dict[str, Any]]:
        from campy.brain.hippocampus.graph.gateway import is_question_only

        if self.limit <= 0 or not concept_uris:
            return []
        anchors = self.uncovered(self.select_anchors(concept_uris))
        if not anchors:
            return []
        cap = self._cap()
        speakers = self._speakers()
        scope = self._participant_sessions(concept_uris, speakers)
        hop1 = list(dict.fromkeys(m for a in anchors for m in a.members))
        hop2 = self._hop2_entities(anchors, set(hop1), cap, speakers)
        shown = {_local(self._message_uri(i)) for i in
                 list(self.p.get("conversation_ids") or []) + list(self.p.get("semantic_refs") or [])}
        cands: dict[str, dict[str, Any]] = {}
        for hop, group in ((1, hop1), (2, hop2)):
            for m, cs in self._mentioning(group).items():
                if _local(m) in shown:
                    continue
                c = cands.setdefault(m, {"hop": hop, "hits": set()})
                c["hop"] = min(c["hop"], hop)
                c["hits"] |= cs
        if not cands:
            return []
        if scope is not None:
            in_scope = {str(r["m"]) for r in self.run(f"""
                SELECT DISTINCT ?m WHERE {{ {_values('?m', list(cands))} ?m {NS}SENT_IN> ?s .
                    {_values('?s', sorted(scope))} }}""")}
            cands = {m: c for m, c in cands.items() if m in in_scope}
            if not cands:
                return []
        qnorm = " ".join(str(self.p.get("query_text") or "").strip().lower().split())
        q = self.p.get("query_embedding")
        out: list[dict[str, Any]] = []
        seen_src: set[str] = set()
        for row in self.gw._hydrate_messages(list(cands)):
            uri = str(row["s"])
            text = str(row.get("text") or "").strip()
            if (not text or bool(row.get("archived")) or row.get("role") != "user"
                    or is_question_only(text) or " ".join(text.lower().split()) == qnorm):
                continue
            if _local(uri) in seen_src:
                continue
            seen_src.add(_local(uri))
            sim = self._cosine(uri, q)
            if self.min_sim > 0 and sim < self.min_sim:
                continue
            created = row.get("occurred") or row.get("created")
            stamp = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
            out.append({"kind": "Message", "node_id": uri, "text": text, "role": "user",
                        "speaker": row.get("speaker"), "created_at": stamp, "event_time": stamp,
                        "hop": cands[uri]["hop"], "anchors": len(cands[uri]["hits"]),
                        "similarity": round(sim, 4)})
        out.sort(key=lambda r: (r["hop"], -r["anchors"], -r["similarity"], r["node_id"]))
        return out[:self.limit]


def bundle_concept_walk_v2(gw: Any, params: dict[str, Any]) -> list[Any]:
    """`thalamus.bundle_concept_walk_v2`: see the module docstring. Fail-soft: [] on any error."""
    from campy.brain.hippocampus.graph.vector_store import mint_uri
    from campy.brain.hippocampus.graph.gateway import RowDict

    try:
        ids = list(dict.fromkeys(params.get("concept_ids") or []))[:24]
        uris = [mint_uri("Concept", c) for c in ids]
        return [RowDict(r) for r in WalkV2(gw, params).rows(uris)]
    except Exception:
        _logger.warning("bundle_concept_walk_v2 failed", exc_info=True)
        return []
