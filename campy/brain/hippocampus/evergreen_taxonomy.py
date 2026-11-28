"""Evergreen SKOS Taxonomy engine.

Gated behind `[observations] evergreen_taxonomy` (default ``False``,
env ``CAMPY_EVERGREEN_TAXONOMY=1``, in no profile until gated).

Design invariants:
  * Graph first: zero shadow stores. All persistent taxonomy state lives in the
    graph store (`INSTANCE_OF`, `BROADER`, `HAS_ALT_LABEL`, `kind_scheme="kind"`).
    Any `kinds` / `broader_adj` / `c_index` dicts are strictly local
    read-through views constructed per call or per sweep.
  * Rules decide: deterministic singular-lemma normalization, closed-set kind
    resolution via `HAS_PREF_LABEL`/`text_raw` and `HAS_ALT_LABEL`, WordNet
    hypernym walks to a general upper-ontology ceiling, and B541 cycle detection.
  * Generalise, don't memorise: no dataset- or question-specific rules.
  * Reuses Campy's existing `kinds.*`, `steward.*`, `concept_links.*`,
    `temporal_lobe.*`, and `typed_objects.*` NamedQueries through `GraphGateway`.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import re
import time
from typing import Any, Callable
import uuid

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.concept_links import KIND_SCHEME, concept_index, norm_key
from campy.brain.hippocampus.entity_admission import can_be_kind
from campy.brain.hippocampus.graph import embeddings as emb_mod
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.temporal_lobe.lexicon import closed_class
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

_logger = logging.getLogger(__name__)

# Standard general upper-ontology ceiling.
UPPER_CEILING: frozenset[str] = frozenset({
    "hobby", "sport", "pet", "animal", "musical instrument", "instrument",
    "artwork", "art", "book", "food", "drink", "city", "country",
    "vehicle", "clothing", "occupation", "job",
    "music", "game", "plant", "tool", "building", "language", "family", "relative",
    "education", "travel", "nature", "craft", "recreation", "pastime",
})

# General lexical synonym aliases used to enrich HAS_ALT_LABEL when the alias is not
# already a distinct live kind's prefLabel.
SYNONYM_ALIASES: dict[str, tuple[str, ...]] = {
    "hobby": ("pastime", "avocation"),
    "dog": ("canine",),
    "cat": ("feline",),
    "drink": ("beverage",),
    "job": ("occupation",),
    "art": ("artwork",),
    "child": ("kid",),
    "movie": ("film",),
    "photo": ("photograph",),
    "clothing": ("garment", "apparel"),
    "relative": ("relation",),
    "place": ("location",),
}

# Clean intra-ceiling generalization pairs (narrower -> broader) when both are
# present or reachable, supplementing WordNet where senses diverge (e.g., artwork->art).
CEILING_BROADERS: tuple[tuple[str, str], ...] = (
    ("pet", "animal"),
    ("musical instrument", "instrument"),
    ("artwork", "art"),
    ("hobby", "pastime"),
    ("pastime", "recreation"),
)

# Lexicographer files representing abstract temporal/quantity/state nouns that should
# not be auto-promoted to entity kinds from unlabeled noun phrases (unless explicitly
# in UPPER_CEILING or matching an existing kind).
_LOW_LEX = frozenset({
    "noun.time", "noun.quantity", "noun.motive", "noun.relation",
    "noun.feeling", "noun.state", "noun.phenomenon",
})

_PRONOUNS = frozenset({
    "i", "me", "my", "myself", "mine", "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "they", "them", "their", "theirs", "themselves",
    "it", "its", "itself", "this", "that", "these", "those",
    "someone", "something", "anyone", "anything", "everyone", "everything",
    "nobody", "nothing", "who", "what", "which", "whom", "whose",
})

_PARTITIVE_OF_RE = re.compile(r"^(?:type|kind|sort|piece|pair|form|set|group)\s+of\s+(.+)$", re.IGNORECASE)
_OF_SPLIT_RE = re.compile(r"^(.+?)\s+of\s+(.+)$", re.IGNORECASE)
_PLACE_KINDS = (
    ("city.n.01", "city"),
    ("country.n.02", "country"),
    ("state.n.04", "state"),
    ("province.n.01", "province"),
    ("continent.n.01", "continent"),
    ("region.n.03", "region"),
    ("location.n.01", "location"),
)
_MAX_HYPERNYM_DEPTH = 10
_SECONDARY_SENSE_MAX_DEPTH = 2
_WORDNET_SOURCE = wn_mod.SOURCE  # "wordnet"


def evergreen_taxonomy_enabled(config: dict | None) -> bool:
    """`[observations] evergreen_taxonomy` (default false; env `CAMPY_EVERGREEN_TAXONOMY=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("evergreen_taxonomy", False))


@dataclass
class TaxonomyEnrichResult:
    """Result counters for a single inline taxonomy enrichment call."""

    concept_id: str
    kind_id: str | None = None
    kind_label: str | None = None
    instance_of_added: bool = False
    new_kinds_created: int = 0
    new_broader: int = 0
    new_alt_labels: int = 0
    cycles_prevented: int = 0
    elapsed_ms: float = 0.0


@dataclass
class TaxonomySweepStats:
    """Aggregate counters for a store-wide evergreen taxonomy sweep."""

    elapsed_ms: float = 0.0
    entities_scanned: int = 0
    entities_enriched: int = 0
    phrases_scanned: int = 0
    phrases_enriched: int = 0
    kinds_scanned: int = 0
    kinds_enriched: int = 0
    new_instance_of: int = 0
    new_broader: int = 0
    new_alt_labels: int = 0
    new_kinds_created: int = 0
    cycles_prevented: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "elapsed_ms": round(self.elapsed_ms, 2),
            "entities_scanned": self.entities_scanned,
            "entities_enriched": self.entities_enriched,
            "phrases_scanned": self.phrases_scanned,
            "phrases_enriched": self.phrases_enriched,
            "kinds_scanned": self.kinds_scanned,
            "kinds_enriched": self.kinds_enriched,
            "new_instance_of": self.new_instance_of,
            "new_broader": self.new_broader,
            "new_alt_labels": self.new_alt_labels,
            "new_kinds_created": self.new_kinds_created,
            "cycles_prevented": self.cycles_prevented,
            "errors": self.errors,
        }


InlineEnrichResult = TaxonomyEnrichResult
SweepStats = TaxonomySweepStats


# ---------------------------------------------------------------------------
# Fast deterministic normalization & head-noun extraction
# ---------------------------------------------------------------------------

def _fast_singular_word(word: str) -> str:
    """Singularize a single noun via WordNet morphy (<0.05ms) with rule fallback."""
    low = word.lower()
    if len(low) <= 3 or low in kinds_mod._PLURALE_TANTUM:
        return word
    wn = wn_mod._wn()
    if wn is not None:
        try:
            lemma = wn.morphy(low, "n")
            if lemma and lemma != low and "_" not in lemma:
                return lemma.capitalize() if word[:1].isupper() and not word.isupper() else lemma
            if lemma == low:
                return word
        except Exception:
            pass
    return kinds_mod._singular_by_rule(word)


def normalise_label_fast(label: str | None, *, nlp: Any | None = None) -> str | None:
    """Clean singular noun form of `label`. Uses `kinds.normalise_kind_label` when `nlp`
    is provided, else a fast WordNet-morphy + suffix-rule path (<0.1ms)."""
    if nlp is not None:
        return kinds_mod.normalise_kind_label(label, nlp=nlp)
    t = " ".join(str(label or "").replace("\u2019", "'").split())
    t = t.strip(kinds_mod._WORD_STRIP + " ")
    words = t.split(" ") if t else []
    while len(words) > 1 and words[0].lower() in kinds_mod.LABEL_DETERMINERS:
        words = words[1:]
    if not words or not any(ch.isalpha() for ch in " ".join(words)):
        return None
    if words[-1].lower().endswith("'s") and len(words[-1]) > 2:
        words[-1] = words[-1][:-2]
    last = words[-1]
    if last.lower() not in kinds_mod._PLURALE_TANTUM:
        words[-1] = _fast_singular_word(last)
    out = " ".join(words)
    low = out.lower()
    if not out or low in kinds_mod.META_NOUNS or low in _PRONOUNS or closed_class.is_closed_class(out):
        return None
    return out


def _is_valid_noun_head(word: str, known_keys: set[str]) -> bool:
    """True if `word` is an existing kind, in UPPER_CEILING, or a non-abstract WordNet noun."""
    low = word.lower()
    if not low or len(low) < 3 or low in kinds_mod.META_NOUNS or low in _PRONOUNS or closed_class.is_closed_class(low):
        return False
    nk = norm_key(low)
    if nk in known_keys or low in UPPER_CEILING:
        return True
    if not all(ch.isalpha() or ch in (" ", "-") for ch in low):
        return False
    wn = wn_mod._wn()
    if wn is None:
        return True
    try:
        syns = wn.synsets(low.replace(" ", "_"), pos="n")
        if not syns:
            return False
        return syns[0].lexname().lower() not in _LOW_LEX
    except Exception:
        return False


def _wordnet_place_kind(name: str) -> str | None:
    """Resolve GPE/LOC/FAC entities with WordNet instance_hypernyms to city/country/location."""
    wn = wn_mod._wn()
    if wn is None or not name:
        return None
    try:
        syns = wn.synsets(name.strip().replace(" ", "_"), pos="n")
        if not syns:
            return None
        s0 = syns[0]
        if s0.lexname() != "noun.location" or not s0.instance_hypernyms():
            return None
        closure = set(wn_mod.hypernym_closure([s0]))
        for syn_name, label in _PLACE_KINDS:
            if syn_name in closure:
                return label
        return "place"
    except Exception:
        return None


def resolve_target_kind_label(
    label: str,
    proposed_kind: str | None,
    known_keys: set[str],
    *,
    ner_label: str | None = None,
    entity_standing: str | None = None,
    nlp: Any | None = None,
) -> str | None:
    """Determine the normalized singular kind label for a Concept/phrase."""
    if proposed_kind:
        clean = normalise_label_fast(proposed_kind, nlp=nlp)
        if clean and (norm_key(clean) in known_keys or clean.lower() in UPPER_CEILING or _is_valid_noun_head(clean, known_keys)):
            return clean.lower() if clean.isupper() is False and clean[:1].islower() else clean

    if ner_label == "PERSON" and entity_standing != "doubtful":
        return None

    if ner_label in {"GPE", "LOC", "FAC"}:
        place = _wordnet_place_kind(label)
        if place:
            return place

    clean_full = normalise_label_fast(label, nlp=nlp)
    if not clean_full:
        return None

    m_part = _PARTITIVE_OF_RE.match(clean_full)
    if m_part:
        sub = normalise_label_fast(m_part.group(1), nlp=nlp)
        if sub:
            clean_full = sub

    nk_full = norm_key(clean_full)
    if nk_full in known_keys or clean_full.lower() in UPPER_CEILING:
        return clean_full.lower() if clean_full.lower() in UPPER_CEILING else clean_full

    wn = wn_mod._wn()
    if wn is not None and " " in clean_full:
        try:
            if wn.synsets(clean_full.lower().replace(" ", "_"), pos="n"):
                if _is_valid_noun_head(clean_full.lower(), known_keys):
                    return clean_full.lower()
        except Exception:
            pass

    m_of = _OF_SPLIT_RE.match(clean_full)
    head_phrase = m_of.group(1) if m_of else clean_full
    words = head_phrase.split()
    if not words:
        return None
    head = _fast_singular_word(words[-1]).lower()
    if _is_valid_noun_head(head, known_keys):
        return head
    return None


# ---------------------------------------------------------------------------
# Cycle detection (B541) & WordNet hypernym chain walker
# ---------------------------------------------------------------------------

def _reaches(start: str, target: str, adj: dict[str, set[str]]) -> bool:
    """Cycle-safe BFS check whether `start` reaches `target` along `BROADER` edges."""
    if start == target:
        return True
    visited = {start}
    queue = collections.deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, ()):
            if nxt == target:
                return True
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    return False


def _would_create_cycle(child_id: str, parent_id: str, adj: dict[str, set[str]]) -> bool:
    """B541: True iff adding `child_id -> parent_id` would close a `BROADER` cycle."""
    if child_id == parent_id:
        return True
    return _reaches(parent_id, child_id, adj)


def _bfs_ceiling_paths(
    syn: Any,
    known_by_key: dict[str, str],
    *,
    max_depth: int,
    skip_words: set[str],
) -> list[list[tuple[str, str | None]]]:
    """BFS up hypernyms + instance_hypernyms from `syn`.

    Returns paths as lists of `(target_label, existing_kind_id_or_None)` steps
    (excluding the starting word itself), keeping only paths that terminate in
    `UPPER_CEILING` or pass through existing live kinds to `UPPER_CEILING`.
    """
    queue: collections.deque[tuple[Any, list[tuple[str, str | None]], int]] = collections.deque([(syn, [], 0)])
    visited = {syn}
    found: list[list[tuple[str, str | None]]] = []
    seen_targets: set[str] = set()

    while queue:
        cur, trail, depth = queue.popleft()
        if depth > 0:
            lemmas = [l.name().replace("_", " ").lower() for l in cur.lemmas()]
            ceiling_hits = [lm for lm in lemmas if lm in UPPER_CEILING and lm not in skip_words]
            if ceiling_hits:
                # Prefer exact multi-word / primary ceiling lemma
                target = sorted(ceiling_hits, key=lambda x: (-len(x.split()), lemmas.index(x)))[0]
                if target not in seen_targets:
                    seen_targets.add(target)
                    found.append(trail + [(target, known_by_key.get(norm_key(target)))])
                continue  # Stop at ceiling; do not walk above it into entity/abstraction

            # Check if an existing live kind (not _TOO_GENERAL) sits on this synset
            existing_step: tuple[str, str] | None = None
            for lm in lemmas:
                if lm in wn_mod._TOO_GENERAL or lm in skip_words:
                    continue
                nk = norm_key(lm)
                if nk in known_by_key:
                    # Ensure dominant sense matches to avoid spurious homonyms
                    dom = {s.name() for s in wn_mod.noun_synsets(lm.replace(" ", "_"), wn_mod.SENSE_FIRST_ONLY)}
                    if cur.name() in dom:
                        existing_step = (lm, known_by_key[nk])
                        break
            if existing_step is not None:
                trail = trail + [existing_step]

        if depth >= max_depth:
            continue

        for parent_syn in list(cur.hypernyms()) + list(cur.instance_hypernyms()):
            if parent_syn not in visited:
                visited.add(parent_syn)
                queue.append((parent_syn, trail, depth + 1))

    return found


def plan_wordnet_ceiling_paths(
    kind_label: str,
    known_by_key: dict[str, str],
) -> list[list[tuple[str, str | None]]]:
    """Compute WordNet hypernym chains from `kind_label` up to `UPPER_CEILING`."""
    if not wn_mod.available():
        return []
    low = kind_label.lower()
    skip = {low}
    all_paths: list[list[tuple[str, str | None]]] = []

    for word in wn_mod.head_words(kind_label):
        syns = wn_mod.noun_synsets(word, cutoff=wn_mod.SENSE_FIRST_ONLY)
        if not syns:
            continue
        paths = _bfs_ceiling_paths(syns[0], known_by_key, max_depth=_MAX_HYPERNYM_DEPTH, skip_words=skip)
        if not paths:
            # Check immediate secondary sense (dist <= 2, non-person) for cases like
            # pottery.n.02->craft or novel.n.02->book without drifting on rare senses.
            wn = wn_mod._wn()
            all_syns = wn.synsets(word, pos="n") if wn is not None else []
            if len(all_syns) > 1 and all_syns[1].lexname() != "noun.person":
                paths = _bfs_ceiling_paths(
                    all_syns[1], known_by_key, max_depth=_SECONDARY_SENSE_MAX_DEPTH, skip_words=skip
                )
        if paths:
            all_paths.extend(paths)
            break

    # Deduplicate step lists preserving order
    deduped: list[list[tuple[str, str | None]]] = []
    seen_seqs: set[tuple[str, ...]] = set()
    for p in all_paths:
        sig = tuple(lbl for lbl, _ in p)
        if sig and sig not in seen_seqs:
            seen_seqs.add(sig)
            deduped.append(p)
    return deduped


def _wordnet_synonyms(label: str) -> list[str]:
    """Reciprocal first-sense WordNet synset-mates plus declared SYNONYM_ALIASES."""
    low = label.lower().strip()
    out: list[str] = list(SYNONYM_ALIASES.get(low, ()))
    if not wn_mod.available():
        return out
    wn = wn_mod._wn()
    if wn is None:
        return out
    try:
        syns = wn.synsets(low.replace(" ", "_"), pos="n")
        if not syns:
            return out
        s0 = syns[0]
        for lem in s0.lemmas():
            cand = lem.name().replace("_", " ").lower()
            if (
                cand == low
                or len(cand) < 3
                or " " in cand
                or not cand.isalpha()
                or cand in wn_mod._TOO_GENERAL
                or cand in kinds_mod.META_NOUNS
                or closed_class.is_closed_class(cand)
            ):
                continue
            cand_syns = wn.synsets(cand, pos="n")
            if cand_syns and cand_syns[0] == s0 and cand not in out:
                out.append(cand)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Graph helpers (zero shadow stores — read/write through GraphGateway only)
# ---------------------------------------------------------------------------

def _default_embed(text: str) -> list[float]:
    from campy.brain.hippocampus import observations as obs_mod

    try:
        return emb_mod.embed(text, model_name=obs_mod.EMBEDDING_MODEL)
    except Exception:
        _logger.debug("Embedding fallback zero-vector for %r", text, exc_info=True)
        return [0.0] * obs_mod.EMBEDDING_DIM


def _index_kinds(kinds: dict[str, kinds_mod.Kind]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Build local read-through lookup dicts from `kinds`."""
    by_key: dict[str, str] = {}
    broader_adj: dict[str, set[str]] = {}
    for cid in sorted(kinds):
        k = kinds[cid]
        if k.pref_key:
            by_key.setdefault(k.pref_key, cid)
        for alt in k.alts:
            ak = norm_key(alt)
            if ak:
                by_key.setdefault(ak, cid)
        broader_adj[cid] = set(k.broader)
    return by_key, broader_adj


_LEAD_ARTICLE_RE = re.compile(r"^(?:a|an|the|my|her|his|their|our|some|new)\s+", re.I)
_PREP_TAIL_RE = re.compile(r"\s+(?:for|of|in|at|on|to|with|about|around|from|by)\s+.+$", re.I)


def derive_alt_labels(label: str) -> set[str]:
    """Deterministic morphological & lexical `HAS_ALT_LABEL` variants for a Concept label.

    Generates:
      1. Leading-determiner stripped form (`"a transgender conference"` -> `"transgender conference"`).
      2. Prepositional-head form (`"a charity race for mental health"` -> `"charity race"`,
         `"field of study"` -> `"field"`).
      3. Gerund and WordNet verb stems (`"painting"` -> `"paint"`, `"camping trip"` -> `"camping"`, `"camp"`).
      4. WordNet primary-synset single-word noun synonyms (`"occupation"` -> `"career"`).
    """
    alts: set[str] = set()
    s = " ".join((label or "").strip().split())
    low = s.lower()
    if not low or len(low) < 3:
        return alts

    s1 = _LEAD_ARTICLE_RE.sub("", low).strip()
    if s1 and s1 != low and len(s1) >= 3 and not closed_class.is_closed_class(s1):
        alts.add(s1)
    base = s1 or low

    s2 = _PREP_TAIL_RE.sub("", base).strip()
    if s2 and s2 != base and len(s2) >= 3 and not closed_class.is_closed_class(s2):
        alts.add(s2)

    wn = wn_mod._wn()
    words = (s2 or base).split()
    gerund_cands = ([words[0]] if len(words) >= 2 and words[0].endswith("ing") else []) + (
        [base] if len(words) == 1 else []
    )
    for w in gerund_cands:
        if w.endswith("ing") and len(w) >= 5 and w.isalpha():
            if not closed_class.is_closed_class(w):
                alts.add(w)
            if wn is not None:
                try:
                    v = wn.morphy(w, "v")
                except Exception:
                    v = None
                if v and len(v) >= 3 and not closed_class.is_closed_class(v):
                    alts.add(v)

    if wn is not None and len(words) == 1 and len(base) >= 4 and base.isalpha():
        try:
            syns = wn.synsets(base, pos="n")
        except Exception:
            syns = []
        if syns:
            for lm in syns[0].lemmas():
                nm = lm.name().replace("_", " ").lower()
                if nm != base and len(nm) >= 4 and " " not in nm and not closed_class.is_closed_class(nm):
                    alts.add(nm)

    alts.discard(low)
    return alts


async def _attach_derived_alt_labels(
    gw: Any,
    concept_id: str,
    label: str,
    existing_alts: set[str] | None = None,
) -> int:
    """Write deterministic derived `HAS_ALT_LABEL`s for `concept_id`, skipping any already present."""
    derived = derive_alt_labels(label)
    if not derived:
        return 0
    have = {a.casefold() for a in (existing_alts or ())}
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for alt in sorted(derived):
        if alt.casefold() in have:
            continue
        lid = "lbl_" + hashlib.sha256(f"{concept_id}:{alt}".encode("utf-8")).hexdigest()[:16]
        await gw.run("quests.create_alt_label", lid=lid, txt=alt, now=now)
        await gw.run("quests.link_concept_has_alt_label", cid=concept_id, lid=lid)
        have.add(alt.casefold())
        added += 1
    return added


async def _load_concept_alt_labels(gw: Any) -> dict[str, set[str]]:
    """Read-through map `concept_id -> {alt_label_lower}` for live Concepts."""
    client = getattr(gw, "_client", None)
    exec_collect = getattr(client, "_execute_and_collect", None)
    if exec_collect is None:
        return {}
    sparql = """
        PREFIX campy: <https://campy.dev/ns#>
        SELECT DISTINCT ?cid ?txt WHERE {
          ?c a campy:Concept ; campy:concept_id ?cid ; campy:HAS_ALT_LABEL ?l .
          ?l campy:text ?txt .
          FILTER NOT EXISTS { ?c campy:archived true }
        }
    """
    out: dict[str, set[str]] = collections.defaultdict(set)
    try:
        for r in exec_collect(sparql):
            cid = str(r.get("cid") or "")
            txt = str(r.get("txt") or "").strip().casefold()
            if cid and txt:
                out[cid].add(txt)
    except Exception:
        pass
    return out


async def _load_pref_labels(gw: Any, kinds: dict[str, kinds_mod.Kind]) -> None:
    """Also read `HAS_PREF_LABEL -> Label` if present on any kind Concept."""
    client = getattr(gw, "_client", None)
    exec_collect = getattr(client, "_execute_and_collect", None)
    if exec_collect is None or not kinds:
        return
    sparql = """
        PREFIX campy: <https://campy.dev/ns#>
        SELECT ?cid ?pref WHERE {
          ?c a campy:Concept ; campy:concept_id ?cid ; campy:kind_scheme "kind" ;
             campy:archived false ; campy:HAS_PREF_LABEL ?l .
          ?l campy:text ?pref .
        }
    """
    try:
        for r in exec_collect(sparql):
            cid = str(r.get("cid") or "")
            pref = str(r.get("pref") or "").strip()
            k = kinds.get(cid)
            if k is not None and pref and pref.casefold() != k.pref.casefold() and pref not in k.alts:
                k.alts.append(pref)
    except Exception:
        pass


async def _load_concept_texts(gw: Any) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Read-through index of live Concepts: `(norm_key -> [cid], cid -> text_raw)`."""
    idx = await concept_index(gw, alt_labels=True)
    texts: dict[str, str] = {}
    for row in await gw.run("concept_links.live_concepts"):
        cid = str(row.get("concept_id") or "")
        txt = str(row.get("text_raw") or "")
        if cid and txt:
            texts[cid] = txt
    return idx, texts


async def _ensure_kind_concept(
    gw: Any,
    label: str,
    kinds: dict[str, kinds_mod.Kind],
    by_key: dict[str, str],
    broader_adj: dict[str, set[str]],
    c_index: dict[str, list[str]],
    c_texts: dict[str, str] | None = None,
    *,
    surface: str | None = None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> tuple[str | None, bool, int]:
    """Reuse or create a kind Concept for `label`. Returns `(kind_id, created_new, alts_added)`."""
    plan = kinds_mod.plan_kind(label, kinds)
    alts_added = 0
    if plan.exact:
        kid = plan.exact
        if surface and surface.strip().casefold() != kinds[kid].pref.casefold():
            if norm_key(surface) not in {k.pref_key for cid, k in kinds.items() if cid != kid}:
                if await kinds_mod.add_alt_label(gw, kinds[kid], surface):
                    alts_added += 1
                    nk_s = norm_key(surface)
                    if nk_s:
                        by_key.setdefault(nk_s, kid)
        return kid, False, alts_added

    nk = norm_key(label)
    if not nk or closed_class.is_closed_class(label):
        return None, False, 0

    existing_ids = c_index.get(nk, [])
    kid: str | None = None
    for cand_id in sorted(existing_ids):
        # Only promote an existing un-kinded Concept to a kind when its own text_raw
        # matches `label` (avoid promoting "my dog" or "dogs" as the kind "dog").
        if c_texts is not None and c_texts.get(cand_id, "").strip().casefold() != label.strip().casefold():
            continue
        if await can_be_kind(gw, cand_id):
            kid = cand_id
            break

    created = False
    if kid is None:
        vec = (embed_fn or _default_embed)(label)
        kid = str(uuid.uuid4())
        await gw.run(
            "temporal_lobe.dict_create_concept",
            cid=kid,
            text=label,
            emb=vec,
            gist="Concept",
            stype="DefinedTerm",
            now=datetime.now(timezone.utc),
        )
        c_index.setdefault(nk, []).append(kid)
        if c_texts is not None:
            c_texts[kid] = label
        created = True

    if not await kinds_mod.mark_kind(gw, kid):
        return None, False, 0

    k_obj = kinds_mod.Kind(kid, label)
    kinds[kid] = k_obj
    by_key.setdefault(nk, kid)
    broader_adj.setdefault(kid, set())

    if surface and surface.strip().casefold() != label.casefold():
        if norm_key(surface) not in {k.pref_key for cid, k in kinds.items() if cid != kid}:
            if await kinds_mod.add_alt_label(gw, k_obj, surface):
                alts_added += 1
                nk_s = norm_key(surface)
                if nk_s:
                    by_key.setdefault(nk_s, kid)

    return kid, created, alts_added


async def _safe_link_broader(
    gw: Any,
    child_id: str,
    parent_id: str,
    broader_adj: dict[str, set[str]],
    kinds: dict[str, kinds_mod.Kind],
    *,
    source: str = _WORDNET_SOURCE,
) -> tuple[bool, bool]:
    """Write `child_id -BROADER-> parent_id` with B541 cycle detection.

    Returns `(added, cycle_prevented)`.
    """
    if _would_create_cycle(child_id, parent_id, broader_adj):
        return False, True
    if _reaches(child_id, parent_id, broader_adj):
        return False, False
    await kinds_mod.link_broader_sourced(gw, child_id, parent_id, source)
    broader_adj.setdefault(child_id, set()).add(parent_id)
    if child_id in kinds:
        kinds[child_id].broader.add(parent_id)
    return True, False


async def _add_synonyms_for_kind(
    gw: Any,
    kind: kinds_mod.Kind,
    kinds: dict[str, kinds_mod.Kind],
    by_key: dict[str, str],
    broader_adj: dict[str, set[str]],
) -> tuple[int, int, int]:
    """Attach clean WordNet/synonym `HAS_ALT_LABEL`s without colliding with other kinds' prefLabels."""
    alts_added = 0
    broader_added = 0
    cycles_prevented = 0
    pref_keys = {k.pref_key: cid for cid, k in kinds.items() if k.pref_key}

    for syn_word in _wordnet_synonyms(kind.pref):
        sk = norm_key(syn_word)
        if not sk:
            continue
        other_cid = pref_keys.get(sk)
        if other_cid is not None and other_cid != kind.concept_id:
            continue
        if await kinds_mod.add_alt_label(gw, kind, syn_word):
            alts_added += 1
            by_key.setdefault(sk, kind.concept_id)

    return alts_added, broader_added, cycles_prevented


# ---------------------------------------------------------------------------
# Public Entrypoint 1: Fast Inline Enrichment Hook (< 5 ms warm)
# ---------------------------------------------------------------------------

async def enrich_concept_inline(
    gw: Any,
    concept_id: str,
    label: str,
    proposed_kind: str | None = None,
    *,
    config: dict | None = None,
    ner_label: str | None = None,
    entity_standing: str | None = None,
    is_kind: bool = False,
    is_phrase: bool = False,
    nlp: Any | None = None,
    kinds_view: dict[str, kinds_mod.Kind] | None = None,
    by_key: dict[str, str] | None = None,
    broader_adj: dict[str, set[str]] | None = None,
    c_index: dict[str, list[str]] | None = None,
    c_texts: dict[str, str] | None = None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> TaxonomyEnrichResult:
    """Fast deterministic capture-time hook: normalizes `proposed_kind` or head noun
    of `label` to singular lemma, links `Concept -INSTANCE_OF-> Kind`, and walks
    WordNet hypernym chains up to `UPPER_CEILING` with B541 cycle detection.

    When `config` is passed and `[observations] evergreen_taxonomy` is false, this is
    a no-op. Passing `config=None` runs unconditionally (offline sweep / direct use).
    """
    t0 = time.perf_counter()
    res = TaxonomyEnrichResult(concept_id=concept_id)
    if config is not None and not evergreen_taxonomy_enabled(config):
        return res

    gw = get_gateway(gw)
    if kinds_view is None:
        kinds_view = await kinds_mod.load_kinds(gw)
        await _load_pref_labels(gw, kinds_view)
    if by_key is None or broader_adj is None:
        by_key, broader_adj = _index_kinds(kinds_view)
    if c_index is None or c_texts is None:
        loaded_idx, loaded_texts = await _load_concept_texts(gw)
        if c_index is None:
            c_index = loaded_idx
        if c_texts is None:
            c_texts = loaded_texts

    if concept_id in kinds_view:
        is_kind = True

    known_keys = set(by_key.keys())
    if is_kind and proposed_kind is None:
        target_label = normalise_label_fast(label, nlp=nlp)
        if not target_label:
            target_label = label.strip()
        kind_id = concept_id
    else:
        target_label = resolve_target_kind_label(
            label,
            proposed_kind,
            known_keys,
            ner_label=ner_label,
            entity_standing=entity_standing,
            nlp=nlp,
        )
        if not target_label:
            res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return res

        surface = proposed_kind if proposed_kind else None
        kind_id, created, alts = await _ensure_kind_concept(
            gw, target_label, kinds_view, by_key, broader_adj, c_index, c_texts,
            surface=surface, embed_fn=embed_fn,
        )
        res.new_kinds_created += int(created)
        res.new_alt_labels += alts
        if not kind_id:
            res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return res

        if kind_id != concept_id:
            if is_phrase:
                await gw.run("typed_objects.link_phrase_kind", pid=concept_id, kid=kind_id)
                res.instance_of_added = True
            elif is_kind:
                added, cyc = await _safe_link_broader(gw, concept_id, kind_id, broader_adj, kinds_view)
                res.new_broader += int(added)
                res.cycles_prevented += int(cyc)
            else:
                await kinds_mod.link_instance_of(gw, concept_id, kind_id)
                res.instance_of_added = True

    res.kind_id = kind_id
    res.kind_label = kinds_view[kind_id].pref if kind_id in kinds_view else target_label

    # Head-noun suffix BROADER linking (e.g., "video game" -> "game", "oil painting" -> "painting")
    kind_plan = kinds_mod.plan_kind(res.kind_label, kinds_view)
    for parent_id in kind_plan.broader:
        added, cyc = await _safe_link_broader(gw, kind_id, parent_id, broader_adj, kinds_view, source="label_rule")
        res.new_broader += int(added)
        res.cycles_prevented += int(cyc)
    for child_id in kind_plan.narrower:
        added, cyc = await _safe_link_broader(gw, child_id, kind_id, broader_adj, kinds_view, source="label_rule")
        res.new_broader += int(added)
        res.cycles_prevented += int(cyc)

    # Walk WordNet hypernym chains up to UPPER_CEILING with B541 cycle detection
    for chain in plan_wordnet_ceiling_paths(res.kind_label, by_key):
        cur_id = kind_id
        for step_label, step_existing_id in chain:
            if step_existing_id is None:
                step_id, created, alts = await _ensure_kind_concept(
                    gw, step_label, kinds_view, by_key, broader_adj, c_index, c_texts, embed_fn=embed_fn
                )
                res.new_kinds_created += int(created)
                res.new_alt_labels += alts
            else:
                step_id = step_existing_id
            if not step_id:
                continue
            added, cyc = await _safe_link_broader(gw, cur_id, step_id, broader_adj, kinds_view)
            res.new_broader += int(added)
            res.cycles_prevented += int(cyc)
            cur_id = step_id

    # Attach synonym HAS_ALT_LABELs for this kind
    if kind_id in kinds_view:
        alts, br, cyc = await _add_synonyms_for_kind(gw, kinds_view[kind_id], kinds_view, by_key, broader_adj)
        res.new_alt_labels += alts
        res.new_broader += br
        res.cycles_prevented += cyc

    # Attach deterministic derived HAS_ALT_LABELs (article-strip, prep-head, gerund stem, WN synonym)
    if not is_phrase and ner_label != "PERSON":
        res.new_alt_labels += await _attach_derived_alt_labels(gw, concept_id, label)

    res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return res


# ---------------------------------------------------------------------------
# Public Entrypoint 2: Evergreen Background Sweep Hook
# ---------------------------------------------------------------------------

def _query_untyped_entities_and_phrases(gw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read live non-archived entity Concepts and ObjectPhrases lacking an INSTANCE_OF kind."""
    client = getattr(gw, "_client", None)
    exec_collect = getattr(client, "_execute_and_collect", None)
    if exec_collect is None:
        return [], []

    ent_sparql = """
        PREFIX campy: <https://campy.dev/ns#>
        SELECT DISTINCT ?concept_id ?label ?ner_label ?entity_standing WHERE {
          ?c a campy:Concept ; campy:concept_id ?concept_id ; campy:text_raw ?label .
          FILTER NOT EXISTS { ?c campy:archived true }
          FILTER NOT EXISTS { ?c campy:INSTANCE_OF ?k }
          FILTER NOT EXISTS { ?c campy:kind_scheme ?ks }
          OPTIONAL { ?c campy:ner_label ?ner_label }
          OPTIONAL { ?c campy:entity_standing ?entity_standing }
        }
        ORDER BY ?concept_id
    """
    phrase_sparql = """
        PREFIX campy: <https://campy.dev/ns#>
        SELECT DISTINCT ?phrase_id ?label ?kind_candidate WHERE {
          ?p a campy:ObjectPhrase ; campy:phrase_id ?phrase_id ; campy:text_raw ?label .
          FILTER NOT EXISTS { ?p campy:archived true }
          FILTER NOT EXISTS { ?p campy:INSTANCE_OF ?k }
          OPTIONAL { ?p campy:kind_candidate ?kind_candidate }
        }
        ORDER BY ?phrase_id
    """
    entities = exec_collect(ent_sparql)
    phrases = exec_collect(phrase_sparql)
    return entities, phrases


def _has_ceiling_ancestor(
    kind_id: str,
    kinds_view: dict[str, kinds_mod.Kind],
    broader_adj: dict[str, set[str]],
    ceiling_ids: set[str],
) -> bool:
    """Cycle-safe check whether `kind_id` is in `ceiling_ids` or reaches one via `BROADER`."""
    if kind_id in ceiling_ids:
        return True
    visited = {kind_id}
    q = collections.deque([kind_id])
    while q:
        cur = q.popleft()
        for parent in broader_adj.get(cur, ()):
            if parent in ceiling_ids:
                return True
            if parent not in visited:
                visited.add(parent)
                q.append(parent)
    return False


async def sweep_store_taxonomy(
    db: Any,
    *,
    config: dict | None = None,
    include_phrases: bool = True,
    nlp: Any | None = None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> TaxonomySweepStats:
    """Evergreen background sweep hook (for GCL Sweep / Vocab Steward).

    Queries live non-archived entity Concepts lacking `INSTANCE_OF`, ObjectPhrases
    lacking `INSTANCE_OF`, and live kinds lacking a `BROADER` path to `UPPER_CEILING`
    (via `steward.parentless_kinds` + `kinds.load_kinds`), runs `enrich_concept_inline`,
    applies `wordnet.plan_links` across existing kinds with B541 cycle detection, and
    links clean synonym `HAS_ALT_LABEL`s.
    """
    t0 = time.perf_counter()
    stats = TaxonomySweepStats()
    if config is not None and not evergreen_taxonomy_enabled(config):
        return stats

    gw = get_gateway(db)
    kinds_view = await kinds_mod.load_kinds(gw)
    await _load_pref_labels(gw, kinds_view)
    by_key, broader_adj = _index_kinds(kinds_view)
    c_index, c_texts = await _load_concept_texts(gw)

    # 1. Existing steward reads: parentless kinds + owned entities without kind
    parentless_rows = await gw.run("steward.parentless_kinds")
    parentless_ids = {str(r["kind_id"]) for r in parentless_rows}
    owned_rows = await gw.run("steward.owned_without_kind")

    entities, phrases = _query_untyped_entities_and_phrases(gw)
    seen_ent_ids = {str(r["concept_id"]) for r in entities}
    for r in owned_rows:
        eid = str(r["entity_id"])
        if eid not in seen_ent_ids:
            entities.append({"concept_id": eid, "label": r.get("label"), "ner_label": None, "entity_standing": None})
            seen_ent_ids.add(eid)

    # 2. Enrich untyped entity Concepts
    stats.entities_scanned = len(entities)
    for row in entities:
        cid = str(row["concept_id"])
        lbl = str(row.get("label") or "")
        try:
            r = await enrich_concept_inline(
                gw,
                cid,
                lbl,
                ner_label=row.get("ner_label"),
                entity_standing=row.get("entity_standing"),
                nlp=nlp,
                kinds_view=kinds_view,
                by_key=by_key,
                broader_adj=broader_adj,
                c_index=c_index,
                c_texts=c_texts,
                embed_fn=embed_fn,
            )
            if r.instance_of_added or r.new_broader or r.new_kinds_created or r.new_alt_labels:
                stats.entities_enriched += 1
            stats.new_instance_of += int(r.instance_of_added)
            stats.new_broader += r.new_broader
            stats.new_alt_labels += r.new_alt_labels
            stats.new_kinds_created += r.new_kinds_created
            stats.cycles_prevented += r.cycles_prevented
        except Exception:
            stats.errors += 1
            _logger.debug("sweep entity enrichment failed for %s (%r)", cid, lbl, exc_info=True)

    # 3. Enrich untyped ObjectPhrases (so HAS_OBJECT -> ObjectPhrase reaches kinds too)
    if include_phrases:
        stats.phrases_scanned = len(phrases)
        for row in phrases:
            pid = str(row["phrase_id"])
            lbl = str(row.get("label") or "")
            kc = row.get("kind_candidate")
            try:
                r = await enrich_concept_inline(
                    gw,
                    pid,
                    lbl,
                    proposed_kind=str(kc) if kc else None,
                    is_phrase=True,
                    nlp=nlp,
                    kinds_view=kinds_view,
                    by_key=by_key,
                    broader_adj=broader_adj,
                    c_index=c_index,
                    c_texts=c_texts,
                    embed_fn=embed_fn,
                )
                if r.instance_of_added or r.new_broader or r.new_kinds_created or r.new_alt_labels:
                    stats.phrases_enriched += 1
                stats.new_instance_of += int(r.instance_of_added)
                stats.new_broader += r.new_broader
                stats.new_alt_labels += r.new_alt_labels
                stats.new_kinds_created += r.new_kinds_created
                stats.cycles_prevented += r.cycles_prevented
            except Exception:
                stats.errors += 1
                _logger.debug("sweep phrase enrichment failed for %s (%r)", pid, lbl, exc_info=True)

    # 4. Enrich non-ceiling parentless kinds and kinds lacking a BROADER path to UPPER_CEILING
    ceiling_ids = {cid for cid, k in kinds_view.items() if k.pref_key in {norm_key(c) for c in UPPER_CEILING}}
    kind_ids_to_check = [
        cid for cid in sorted(kinds_view)
        if cid not in ceiling_ids
        and (cid in parentless_ids or not _has_ceiling_ancestor(cid, kinds_view, broader_adj, ceiling_ids))
    ]
    stats.kinds_scanned = len(kinds_view)
    for kid in kind_ids_to_check:
        k = kinds_view[kid]
        try:
            r = await enrich_concept_inline(
                gw,
                kid,
                k.pref,
                is_kind=True,
                nlp=nlp,
                kinds_view=kinds_view,
                by_key=by_key,
                broader_adj=broader_adj,
                c_index=c_index,
                c_texts=c_texts,
                embed_fn=embed_fn,
            )
            if r.new_broader or r.new_kinds_created or r.new_alt_labels:
                stats.kinds_enriched += 1
            stats.new_broader += r.new_broader
            stats.new_alt_labels += r.new_alt_labels
            stats.new_kinds_created += r.new_kinds_created
            stats.cycles_prevented += r.cycles_prevented
        except Exception:
            stats.errors += 1
            _logger.debug("sweep kind enrichment failed for %s (%r)", kid, k.pref, exc_info=True)

    # 5. Intra-ceiling generalization links when both endpoints exist
    for child_lbl, parent_lbl in CEILING_BROADERS:
        cid = by_key.get(norm_key(child_lbl))
        pid = by_key.get(norm_key(parent_lbl))
        if cid and pid and cid != pid:
            added, cyc = await _safe_link_broader(gw, cid, pid, broader_adj, kinds_view)
            stats.new_broader += int(added)
            stats.cycles_prevented += int(cyc)

    # 6. Existing WordNet closed-set linking across all live kinds (with B541 cycle detection)
    if wn_mod.available():
        for link in wn_mod.plan_links(kinds_view):
            added, cyc = await _safe_link_broader(gw, link.child, link.parent, broader_adj, kinds_view, source=link.source)
            stats.new_broader += int(added)
            stats.cycles_prevented += int(cyc)

    # 7. Synonym HAS_ALT_LABEL pass across all live kinds
    for cid in sorted(kinds_view):
        alts, br, cyc = await _add_synonyms_for_kind(gw, kinds_view[cid], kinds_view, by_key, broader_adj)
        stats.new_alt_labels += alts
        stats.new_broader += br
        stats.cycles_prevented += cyc

    # 8. Deterministic derived HAS_ALT_LABEL pass across all live non-PERSON Concepts (idempotent)
    existing_alts = await _load_concept_alt_labels(gw)
    for row in await gw.run("concept_links.live_concepts"):
        cid = str(row.get("concept_id") or "")
        lbl = str(row.get("text_raw") or "")
        ner = str(row.get("ner_label") or "")
        if not cid or not lbl or ner == "PERSON":
            continue
        try:
            added = await _attach_derived_alt_labels(gw, cid, lbl, existing_alts.get(cid))
            if added:
                stats.new_alt_labels += added
                existing_alts.setdefault(cid, set()).update(a.casefold() for a in derive_alt_labels(lbl))
        except Exception:
            stats.errors += 1
            _logger.debug("sweep derived altLabel failed for %s (%r)", cid, lbl, exc_info=True)

    stats.elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return stats
