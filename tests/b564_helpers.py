"""B564 test helpers: a small world (messages, admitted entities), a scripted LLM, and the flag-off signature
used to pin that `[observations] roles` off changes nothing."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

from campy.brain.hippocampus import kinds
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.temporal_lobe.observations import extract as ex

DIM = 384
Q = [1.0] + [0.0] * (DIM - 1)
T0 = datetime(2023, 5, 1, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
BASE = {"observations": {"enabled": True, "llm_enabled": True, "max_turn_chars": 600, "retrieval": False,
                         "entities": False},
        "retrieval": {"conversation_token_budget": 0}}


def cfg(**obs_flags):
    return {**BASE, "observations": {**BASE["observations"], **obs_flags}}


class World:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def message(self, text, *, day=3, speaker="Sam"):
        self.n += 1
        mid = f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        return mid

    async def concept(self, cid, text, *, kind=False):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=Q, gist="Entity", stype="Thing",
                          now=T0)
        if kind:
            await kinds.mark_kind(self.gw, cid)

    async def admit(self, mid, cid, text, label):
        await self.concept(cid, text)
        self.db.store.update(f'INSERT DATA {{ <{mint_uri("Concept", cid)}> {NS}ner_label> "{label}" }}')
        await self.gw.run("concept_links.link_message_concept", mid=mid, cid=cid)

    def session(self, sid, *mids):
        """The messages are SENT_IN one Session."""
        su = mint_uri("Session", sid)
        self.db.store.update(f'INSERT DATA {{ <{su}> a {NS}Session> ; {NS}session_id> "{sid}" }}')
        for mid in mids:
            self.db.store.update(f"INSERT DATA {{ <{mint_uri('Message', mid)}> {NS}SENT_IN> <{su}> }}")

    async def spoken_by(self, mid, cid):
        await self.gw.run("spoken_by.link_spoken_by", mid=mid, cid=cid)

    def edges(self, edge):
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}

    def triples(self):
        rows = self.db._execute_and_collect("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
        return sorted((str(r["s"]), str(r["p"]), str(r["o"])) for r in rows)

    def count(self, cls):
        return int(self.db._execute_and_collect(f"SELECT (COUNT(*) AS ?n) WHERE {{ ?x a {NS}{cls}> }}")[0]["n"])

    def signature(self):
        """Counts of every predicate in the store: ids and timestamps do not matter, structure does."""
        return dict(sorted(Counter(p for _s, p, _o in self.triples()).items()))


class LLM:
    """A scripted client. The extraction call gets `items` as its JSON list; the roles call (form 2: its user
    message starts with "Pick from") gets `roles`: a string, an exception to raise, or a list of answer objects."""

    def __init__(self, *items, roles=None):
        self.reply = json.dumps(list(items))
        self.roles = roles
        self.calls = []

    @property
    def extraction_calls(self):
        return [c for c in self.calls if not self._is_roles(c[0])]

    @property
    def roles_calls(self):
        return [c for c in self.calls if self._is_roles(c[0])]

    @staticmethod
    def _is_roles(messages):
        return messages[-1]["content"].startswith("Pick from")

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if not self._is_roles(messages):
            return self.reply
        if isinstance(self.roles, Exception):
            raise self.roles
        if isinstance(self.roles, str):
            return self.roles
        return json.dumps(self.roles if self.roles is not None else [])


def claim(quote, obj, *, predicate="did", subject="I", **extra):
    return {"subject": subject, "predicate": predicate, "object": obj, "time": None, "polarity": "asserted",
            "quote": quote, "confidence": 0.9, **extra}


async def extract(db, config, world, text, llm, *, admit=(), day=3, speaker="Sam"):
    mid = await world.message(text, day=day, speaker=speaker)
    for cid, name, label in admit:
        await world.admit(mid, cid, name, label)
    stats = ex.ObservationWorkerStats()
    await ex.process_turn(db, config, llm, mid, stats)
    return mid, stats


# the flag-off fixture: turns whose replies also carry the role keys, which must be ignored when the flag is off
ROLE_TURNS = [
    ("Hey Jolene! Last Friday I told Anna the story of my life and they were super kind about it.",
     claim("I told Anna the story of my life", "tell", time="Last Friday", action="told", **{"with": ["Anna"]}),
     [("c-anna", "Anna", "PERSON")]),
    ("Yep, last month I visited my mom`s house which holds a special place in my heart.",
     claim("last month I visited my mom`s house", "visit", time="last month", action="visited",
           place="my mom's house"), []),
    ("We explored nature, roasted marshmallows around the campfire and even went on a hike.",
     claim("even went on a hike", "go on a hike", action="hike"), []),
    ("I mentor a transgender teen just like me.",
     claim("I mentor a transgender teen just like me", "transgender teen", predicate="is_a"), []),
    ("We have a lot of cute photos, I want to share with you.",
     claim("We have a lot of cute photos", "cute photos", predicate="has_attribute", subject="we"), []),
]


def prompt_hashes():
    out = {}
    for entities in (False, True):
        for cardinality in (False, True):
            m = ex.build_messages("I visited Paris last year.", "Sam", "2023-05-03", entities=entities,
                                  cardinality=cardinality)
            out[f"entities={entities},cardinality={cardinality}"] = hashlib.sha256(
                json.dumps(m, sort_keys=True).encode()).hexdigest()
    return out


async def flag_off_signature(db, gw, extra_flags=None):
    world = World(db, gw)
    await world.concept("c-sam", "Sam")
    config = cfg(typed_objects=True, object_roles=True, entities=True, **(extra_flags or {}))
    max_tokens = set()
    for text, c, admit in ROLE_TURNS:
        llm = LLM(c)
        await extract(db, config, world, text, llm, admit=admit)
        max_tokens.update(k.get("max_tokens") for _m, k in llm.extraction_calls)
    return {"signature": world.signature(), "max_tokens": sorted(max_tokens)}
