"""
campy/brain/hippocampus/concept_links.py -- B503: link turns and claims to the
Concepts they name, by rule.

Why: a question about "model kits" or "camping trips" shares no words with the
turn that says "I picked up a Revell F-15 Eagle", so similarity retrieval misses
it. If that turn is linked to the Concepts it mentions, the question's own
Concepts lead to it through the graph.

What is written (all plain edges, idempotent, graph store only):

  Message      -MENTIONS->          Concept   a user turn names the Concept
  Observation  -OBSERVATION_ABOUT-> Concept   the claim's text names it
  Concept      -IS_A->              Concept   from an `is_a` Observation whose
                                              subject and object both resolved

How a Concept is matched: no model. A span of 1-3 words (starting and ending on
a content word) is compared with every live Concept's text after a light
normalisation (lower case, punctuation, leading article/possessive, plural "s").
`already_resolved` ids (what the Loop or the Observation worker matched) are
added as they are. Nothing here ever creates a Concept: if the extractor never
made a Concept for "Revell F-15 Eagle", there is nothing to link and the turn
stays unlinked (see PR notes: extraction must supply object entities).

Everything is gated by `[retrieval] graph_linking` / `CAMPY_GRAPH_LINKING`
(default off); the callers check it, this module never reads global state.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from campy.brain.hippocampus.graph.gateway import get_gateway

KIND_SCHEME = "kind"                      # value of Concept.kind_scheme (B508)

DEFAULT_WALK_LIMIT = 12
MAX_SPAN_WORDS = 3
MAX_SPANS = 400                # spans considered per text
MAX_CONCEPTS_PER_TEXT = 12     # links one text can add (longest spans first)

_DETERMINERS = frozenset({
    "a", "an", "the", "my", "our", "your", "his", "her", "their", "its",
    "this", "that", "these", "those", "some",
})
_TOKEN_RE = re.compile(r"[^\W_](?:[\w'’./-]*[^\W_])?")
_FIRST_PERSON = frozenset({"i", "me", "my", "myself", "mine", "we", "us", "the user", "user", "users"})


def graph_linking_enabled(config: dict | None) -> bool:
    """`[retrieval] graph_linking` (default false; env `CAMPY_GRAPH_LINKING=1` turns it on)."""
    return bool(((config or {}).get("retrieval") or {}).get("graph_linking", False))


def graph_linking_limit(config: dict | None, default: int = DEFAULT_WALK_LIMIT) -> int:
    """`[retrieval] graph_linking_limit`: most items the retrieval walk returns."""
    try:
        return int(((config or {}).get("retrieval") or {}).get("graph_linking_limit", default))
    except (TypeError, ValueError):
        return default


def graph_walk_v2_enabled(config: dict | None) -> bool:
    """B510: `[retrieval] graph_walk_v2` (default false; env `CAMPY_GRAPH_WALK_V2=1`). When on,
    the precise walk (`walk_v2.py`) replaces B503's walk at retrieval; the link writers are
    unchanged (they follow `graph_linking`)."""
    return bool(((config or {}).get("retrieval") or {}).get("graph_walk_v2", False))


def _retrieval_number(config: dict | None, key: str, default, cast):
    try:
        return cast(((config or {}).get("retrieval") or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def graph_walk_v2_limit(config: dict | None) -> int:
    """`[retrieval] graph_walk_v2_limit`: most items the precise walk adds (default 4)."""
    return max(0, _retrieval_number(config, "graph_walk_v2_limit", 4, int))


def graph_walk_v2_max_share(config: dict | None) -> float:
    """`[retrieval] graph_walk_v2_max_share`: an anchor linked to more than this share of the
    store's messages is background, not a topic (default 0.10)."""
    return min(1.0, max(0.0, _retrieval_number(config, "graph_walk_v2_max_share", 0.10, float)))


def graph_walk_v2_min_similarity(config: dict | None) -> float:
    """`[retrieval] graph_walk_v2_min_similarity`: cosine a linked turn must reach against the
    question (default 0.0 = no floor)."""
    return _retrieval_number(config, "graph_walk_v2_min_similarity", 0.0, float)


def graph_walk_v2_protect(config: dict | None) -> int:
    """`[retrieval] graph_walk_v2_protect`: the best-ranked matched conversation turns the walk
    never displaces (default 3)."""
    return max(0, _retrieval_number(config, "graph_walk_v2_protect", 3, int))


# --- normalisation ------------------------------------------------------------------

def _content_terms(text: str) -> list[str]:
    from campy.brain.hippocampus.graph.vector_store import fts_content_terms
    return fts_content_terms(text)


def norm_key(text: str | None) -> str:
    """One comparable key per surface: lower case, possessive and edge
    punctuation dropped, a leading article/possessive dropped, a plural "s"
    dropped from the last word. "your concert tickets" and "Concert ticket"
    share a key. Empty when nothing content-bearing is left."""
    t = " ".join(str(text or "").lower().replace("’", "'").split())
    t = re.sub(r"'s\b", "", t)
    t = re.sub(r"^[^\w]+|[^\w]+$", "", t)
    words = t.split(" ") if t else []
    while len(words) > 1 and words[0] in _DETERMINERS:
        words = words[1:]
    if not words:
        return ""
    last = words[-1]
    if len(last) > 3:
        if last.endswith("ies"):
            last = last[:-3] + "y"
        elif last.endswith("s") and not last.endswith(("ss", "us", "is")):
            last = last[:-1]
    words[-1] = last
    key = " ".join(words)
    return key if _content_terms(key) and len(key) > 2 else ""


def candidate_spans(text: str | None) -> list[str]:
    """Every 1-3 word span of `text` that starts and ends on a content word,
    longest first (as the question-side lookup in the bundle compiler does)."""
    tokens = _TOKEN_RE.findall(text or "")
    content = [bool(_content_terms(t)) for t in tokens]
    spans: list[str] = []
    seen: set[str] = set()
    for n in range(MAX_SPAN_WORDS, 0, -1):
        for i in range(len(tokens) - n + 1):
            if content[i] and content[i + n - 1]:
                span = " ".join(tokens[i:i + n])
                if span.lower() not in seen:
                    seen.add(span.lower())
                    spans.append(span)
                    if len(spans) >= MAX_SPANS:
                        return spans
    return spans


# --- matching -----------------------------------------------------------------------

async def concept_index(gw: Any, *, alt_labels: bool = False) -> dict[str, list[str]]:
    """norm_key -> Concept ids, built fresh from the graph on each call (a
    read-through view, never kept). `alt_labels` (B508, flag `skos_vocab`) also
    indexes the altLabels of kind Concepts, so a kind is found by any wording it
    has accumulated."""
    index: dict[str, list[str]] = {}
    for row in await gw.run("concept_links.live_concepts"):
        key = norm_key(row.get("text_raw"))
        if key:
            index.setdefault(key, []).append(str(row.get("concept_id")))
    if alt_labels:
        for key, ids in (await alt_label_index(gw)).items():
            for cid in ids:
                if cid not in index.setdefault(key, []):
                    index[key].append(cid)
    return index


async def match_concepts(gw: Any, text: str | None, *, index: dict[str, list[str]] | None = None,
                         limit: int = MAX_CONCEPTS_PER_TEXT, alt_labels: bool = False) -> list[str]:
    """Ids of the live Concepts `text` names, longest span first, at most `limit`."""
    spans = candidate_spans(text)
    if not spans:
        return []
    idx = index if index is not None else await concept_index(gw, alt_labels=alt_labels)
    if not idx:
        return []
    out: list[str] = []
    for span in spans:
        for cid in idx.get(norm_key(span), ()):
            if cid not in out:
                out.append(cid)
                if len(out) >= limit:
                    return out
    return out


def _whole_text_concept(index: dict[str, list[str]], text: str | None, known: str | None = None) -> str | None:
    """The Concept `text` as a whole names (deterministic when several share a key)."""
    if known:
        return known
    if not text or text.strip().lower() in _FIRST_PERSON:
        return None
    ids = index.get(norm_key(text))
    return sorted(ids)[0] if ids else None


# --- writes -------------------------------------------------------------------------

async def link_message_concepts(gw: Any, message_id: str, text: str | None,
                                already_resolved: Iterable[str] = (), *,
                                index: dict[str, list[str]] | None = None,
                                alt_labels: bool = False) -> list[str]:
    """MENTIONS from a user Message to every Concept it names. Returns the ids linked."""
    ids = list(dict.fromkeys([c for c in already_resolved if c]
                             + await match_concepts(gw, text, index=index, alt_labels=alt_labels)))
    for cid in ids:
        await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)
    return ids


async def link_observation_concepts(
    gw: Any, observation_id: str, message_id: str | None, *,
    subject_text: str | None, predicate: str | None, object_text: str | None,
    event_text: str | None = None, subject_id: str | None = None, object_id: str | None = None,
    index: dict[str, list[str]] | None = None, skos: bool = False,
) -> list[str]:
    """OBSERVATION_ABOUT (and MENTIONS from its evidence Message) to the
    Concepts the claim's own words name; IS_A subject -> object for an `is_a`
    claim whose two ends both resolve. Returns the Concept ids linked.

    `skos` (B508, flag `skos_vocab`): the `is_a` claim is split by what the
    subject is. The object becomes a kind; a subject that is itself a kind is
    BROADER-linked to it ("a tank is a vehicle": subtype), any other subject is
    INSTANCE_OF it ("Tiger I is a tank": instance). IS_A is not written."""
    idx = index if index is not None else await concept_index(gw, alt_labels=skos)
    ids = [c for c in (subject_id, object_id) if c]
    # a first-person subject ("I") names nobody; its words are not matched
    for t in (object_text, event_text, subject_text):
        if t and t.strip().lower() not in _FIRST_PERSON:
            ids.extend(await match_concepts(gw, t, index=idx))
    ids = list(dict.fromkeys(ids))
    for cid in ids:
        await gw.run("observations.link_about_concept", oid=observation_id, cid=cid)
        if message_id:
            await gw.run("concept_links.link_message_concept", mid=message_id, cid=cid)
    if (predicate or "") == "is_a":
        child = _whole_text_concept(idx, subject_text, subject_id)
        parent = _whole_text_concept(idx, object_text, object_id)
        if child and parent and child != parent:
            if skos:
                # Direct queries, not campy.brain.hippocampus.kinds: kinds imports
                # this module, so importing it back would be a cycle.
                known = {str(r["concept_id"]) for r in await gw.run("kinds.live_kinds")}
                await gw.run("kinds.mark_kind", cid=parent, scheme=KIND_SCHEME)
                if child in known:
                    await gw.run("kinds.link_broader", cid=child, pid=parent)
                else:
                    await gw.run("kinds.link_instance_of", cid=child, kid=parent)
            else:
                await gw.run("concept_links.link_is_a", cid=child, pid=parent)
    return ids


async def link_existing(db: Any, *, skos: bool = False) -> dict[str, int]:
    """One pass over a store written without linking: MENTIONS for every live
    user Message, OBSERVATION_ABOUT / IS_A for every live Observation, by the same
    rules as the write path. Idempotent. For stores built before B503 and for
    offline replay; the Loop and the Observation worker link new turns as they
    arrive when the flag is on."""
    gw = get_gateway(db)
    idx = await concept_index(gw, alt_labels=skos)
    stats = {"messages": 0, "message_links": 0, "observations": 0, "observation_links": 0}
    if not idx:
        return stats
    for row in await gw.run("concept_links.list_user_messages"):
        ids = await link_message_concepts(gw, row["message_id"], row.get("text_raw"), index=idx, alt_labels=skos)
        stats["messages"] += 1
        stats["message_links"] += len(ids)
    for row in await gw.run("concept_links.list_live_observations"):
        ids = await link_observation_concepts(
            gw, row["observation_id"], row.get("evidence_ref"),
            subject_text=row.get("subject_text"), predicate=row.get("predicate"),
            object_text=row.get("object_text"), event_text=row.get("event_text"),
            subject_id=row.get("subject_id"), object_id=row.get("object_id"), index=idx, skos=skos)
        stats["observations"] += 1
        stats["observation_links"] += len(ids)
    return stats


async def alt_label_index(gw: Any) -> dict[str, list[str]]:
    """norm_key -> kind ids, over the kinds' altLabels (question side: "model-kits" finds "model kit")."""
    index: dict[str, list[str]] = {}
    for r in await gw.run("kinds.kind_alt_labels"):
        key = norm_key(r.get("alt"))
        if key:
            index.setdefault(key, []).append(str(r["concept_id"]))
    return index
