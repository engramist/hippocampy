"""Fact sentences (placement A): the rule-rendered sentence on the line after the conversation turn a fact came from.

Made-up store (names invented, no model, no benchmark data) written through the real capture writes
(`observations.record_observation`, the roles queries). Pins: the flag sites; the predicate x polarity table including
the "no sentence" cells; the first-person rewrite; the date forms and the two fallbacks; the single / list / over-cap
grouping done by the query and its deterministic member order; the caps; the shown-turn join; liveness; the
duplicate-Observation flag; flag-off and flag-on-nothing-matching prompts byte-identical; nothing written.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import kinds
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.hippocampus.graph.queries.fact_sentences import FIELD_SEP, FIELDS, LIST_CAP, TOKEN_SEP
from campy.brain.hippocampus.graph.vector_store import mint_uri
from campy.brain.thalamus import fact_sentences as fs
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle
from tests.b564_helpers import NS, Q, T0, World

ROLES_ON = {"observations": {"enabled": True, "object_roles": True}}
ON = {"retrieval": {"fact_sentences": True}}
S = "Nora"


# ------------------------------------------------------------------------------------------------ pure rendering
def mem(text="a pottery class", *, time_text="", ts="", te="", tp="", obs_at="", place="", partners=(), grp="",
        dup="", turn="2023-05-03", iri="https://campy.dev/id/Message/m1", mid="m1", oid="o1"):
    return {"oid": oid, "text": text, "time_text": time_text, "time_start": ts, "time_end": te, "time_precision": tp,
            "observed_at": obs_at, "place": place, "partners": "|".join(partners), "group_subject": grp,
            "as_observation": dup, "key": f"{turn}T12:00:00+00:00|{iri}|{mid}", "turn_date": turn,
            "message_iri": iri, "message_id": mid, "partner_list": sorted(partners)}


# predicate -> (asserted, negated, hypothetical/planned); None is a "no sentence" cell
TABLE = {
    "did": ("Nora did: X.", "Nora did not: X.", "Nora planned: X."),
    "plans": ("Nora planned: X.", "Nora decided against: X.", "Nora planned: X."),
    "has_attribute": ("Nora: X.", "Nora: not X.", "Nora might be: X."),
    "is_a": ("Nora is X.", "Nora is not X.", "Nora might be X."),
    "located_in": ("Nora was in X.", "Nora was not in X.", "Nora planned to be in X."),
    "owns": ("Nora has X.", "Nora does not have X.", "Nora plans to get X."),
    "relates_to": ("Nora is connected with X.", "Nora is not connected with X.", None),
    "prefers": ("Nora likes X.", "Nora does not like X.", None),
    "changed_to": ("Nora changed to X.", None, "Nora plans to change to X."),
}


@pytest.mark.parametrize("predicate", sorted(TABLE))
@pytest.mark.parametrize("polarity,col", [("asserted", 0), ("negated", 1), ("hypothetical", 2), ("planned", 2)])
def test_table(predicate, polarity, col):
    want = TABLE[predicate][col]
    got = fs.render_single(mem("X"), predicate, polarity, S)
    if want is None:
        assert got is None
    else:
        assert got == want.replace("X.", "X (said on 2023-05-03).")


def test_unknown_predicate_and_null_polarity():
    assert fs.render_single(mem("X"), "wishes", "asserted", S) is None
    assert fs.render_single(mem("X"), "did", None, S).startswith("Nora did: X")


def test_no_words_renders_nothing():
    assert fs.render_single(mem(""), "did", "asserted", S) is None


@pytest.mark.parametrize("raw,want", [
    ("my kids", "Nora's kids"), ("My dog", "Nora's dog"), ("I", "Nora"), ("gave me a book", "gave Nora a book"),
    ("I'm tired", "Nora is tired"), ("I've been", "Nora has been"), ("I’d go", "Nora would go"),
    ("mine", "Nora's"), ("myself", "Nora"),
    ("a mighty meal at Weston", "a mighty meal at Weston"),      # word boundaries
    ("the US bus", "the US bus"), ("i say", "i say"), ("ME", "ME"),
])
def test_first_person_plain(raw, want):
    assert fs.rewrite_first_person(raw, S)[0] == want


def test_we_with_partner_group_subject_and_plain():
    assert fs.rewrite_first_person("we went hiking", S, ["Pia"]) == ("Nora and Pia went hiking", True)
    assert fs.rewrite_first_person("We saw us", S, ["Ben", "Pia"]) == ("Nora and Ben and Pia saw Nora and Ben and Pia", True)
    assert fs.rewrite_first_person("we went hiking", S, []) == ("Nora and others went hiking", False)   # group_subject, no partner
    assert fs.rewrite_first_person("our trip", S, ["Pia"])[0] == "Nora and Pia's trip"
    assert fs.rewrite_first_person("our trip", S, [])[0] == "Nora and others' trip"
    assert fs.rewrite_first_person("we're late", S, [])[0] == "Nora and others are late"


def test_partner_not_repeated_after_we_and_labels_never_rewritten():
    m = mem("we made pots", partners=["Pia"], place="my studio")
    out = fs.render_single(m, "did", "asserted", S)
    assert "Nora and Pia made pots" in out and ", with" not in out and ", in my studio" in out
    assert fs.render_single(mem("a class", partners=["Pia", "Ben"]), "did", "asserted", S).count(", with Ben and Pia") == 1


def test_clause_form():
    out = fs.render_single(mem("I took the kids to the beach"), "did", "asserted", S)
    assert out.startswith("Nora took the kids to the beach") and "did:" not in out


@pytest.mark.parametrize("kw,want", [
    (dict(ts="2023-07-14T00:00:00Z", te="2023-07-14T00:00:00Z", tp="day"), ", on 14 July 2023."),
    (dict(ts="2023-07-06T00:00:00Z", te="2023-07-08T00:00:00Z", tp="day"), ", from 6 July 2023 to 8 July 2023."),
    (dict(ts="2023-04-24T00:00:00Z", te="2023-04-30T00:00:00Z", tp="week"), ", in the week of 24 April 2023."),
    (dict(ts="2023-07-01T00:00:00Z", te="2023-07-31T00:00:00Z", tp="month"), ", in July 2023."),
    (dict(ts="2023-01-01T00:00:00Z", te="2023-12-31T00:00:00Z", tp="year"), ", in 2023."),
])
def test_resolved_dates_replace_the_phrase(kw, want):
    out = fs.render_single(mem("a trip", time_text="a while back", **kw), "did", "asserted", S)
    assert out.endswith(want) and "a while back" not in out and "said on" not in out


def test_relative_phrase_resolved_from_the_turn_date():
    out = fs.render_single(mem("a trip", time_text="yesterday", obs_at="2023-05-08T12:00:00+00:00", turn="2023-05-08"),
                           "did", "asserted", S)
    assert out.endswith(", on 7 May 2023.") and "yesterday" not in out


def test_unresolved_phrase_is_kept_and_no_phrase_falls_back():
    out = fs.render_single(mem("a class", time_text="every Saturday"), "did", "asserted", S)
    assert out == "Nora did: a class (every Saturday, said on 2023-05-03)."
    assert fs.render_single(mem("a class"), "did", "asserted", S) == "Nora did: a class (said on 2023-05-03)."


def test_place_partner_date_order():
    out = fs.render_single(mem("a class", place="the studio", partners=["Anna"], ts="2023-07-14T00:00:00Z",
                               tp="day"), "did", "asserted", S)
    assert out == "Nora did: a class, in the studio, with Anna, on 14 July 2023."


def test_list_sentences():
    ms = [mem("a mug", ts="2023-05-14T00:00:00Z", tp="day", oid="a"), mem("a bowl", oid="b"),
          mem("a vase", time_text="every week", oid="c")]
    assert fs.render_list(ms[:2], "did", "asserted", S) == "Nora did: a mug (14 May 2023) and a bowl (said on 2023-05-03)."
    assert fs.render_list(ms, "did", "negated", S) == (
        "Nora did not: a mug (14 May 2023), a bowl (said on 2023-05-03) and a vase (every week, said on 2023-05-03).")
    assert fs.render_list(ms, "prefers", "hypothetical", S) is None            # "no sentence" cell
    assert fs.render_list([mem("I made a mug"), mem("a bowl")], "did", "asserted", S) is None   # clause in a list
    assert fs.render_list([mem("a mug") for _ in range(LIST_CAP + 1)], "did", "asserted", S) is None


def _row(members, predicate="did", polarity="asserted", turn="2023-05-03", iri="https://campy.dev/id/Message/m1",
         mid="m1"):
    toks = TOKEN_SEP.join(FIELD_SEP.join(m[f] if f != "key" else m["key"] for f in FIELDS) for m in members)
    return {"predicate": predicate, "polarity": polarity, "gn": len(members), "members": toks,
            "attach_key": f"{turn}T12:00:00+00:00|{iri}|{mid}"}


def test_caps_per_turn_and_per_prompt_are_deterministic():
    def single(i, turn, iri):
        return _row([mem(f"thing {i}", oid=f"o{i}", turn=turn, iri=iri, mid=iri[-2:])], predicate="owns",
                    turn=turn, iri=iri, mid=iri[-2:])
    # three on one turn: two kept (the first two in the query's order), one dropped
    rows = [single(i, "2023-05-09", "https://campy.dev/id/Message/m9") for i in range(3)]
    kept, counts = fs.sentences_from_rows(rows, S)
    assert [k["fact_ids"] for k in kept] == [["o0"], ["o1"]] and counts == {"dropped_turn_cap": 1, "dropped_prompt_cap": 0}
    # eight turns with one each: the first six (newest first, as the query orders) kept
    rows = [single(i, f"2023-05-{20 - i:02d}", f"https://campy.dev/id/Message/m{i}") for i in range(8)]
    kept, counts = fs.sentences_from_rows(rows, S)
    assert [k["fact_ids"][0] for k in kept] == [f"o{i}" for i in range(6)] and counts["dropped_prompt_cap"] == 2
    assert fs.sentences_from_rows(rows, S) == (kept, counts)


# ------------------------------------------------------------------------------------------------ the store
@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(embeddings_mod, "embed", lambda text, model_name=None: Q)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "fact_sentences.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    """Subject Nora, a kind `hobby`, and helpers to add turns and facts."""

    def __init__(self, db, gw):
        self.db, self.gw, self.w, self.n = db, gw, World(db, gw), 0

    async def start(self):
        await self.w.concept("c-nora", S)
        await self.w.concept("k-hobby", "hobby", kind=True)
        await self.w.concept("k-pet", "pet", kind=True)
        await self.w.concept("c-pia", "Pia")
        await self.w.concept("c-studio", "the studio")
        return self

    async def fact(self, obj, *, day=3, predicate="did", polarity="asserted", kind="k-hobby", time_text=None,
                   time_start=None, time_end=None, time_precision=None, place=None, partner=None, quote=None,
                   object_text=None, mid=None, obj_id=None):
        self.n += 1
        quote = quote or f"I did {obj} number {self.n}"
        if mid is None:
            mid = await self.w.message(quote, day=day, speaker=S)
            await self.w.spoken_by(mid, "c-nora")
        cid = obj_id or f"c-{self.n}-{obj}"
        if not obj_id:
            await self.w.concept(cid, obj)
            if kind:
                await kinds.link_instance_of(self.gw, cid, kind)
        res = await obs.record_observation(self.db, obs.ObservationDraft(
            evidence_ref=mid, evidence_text=quote, subject_text="I", predicate=predicate,
            object_text=object_text or obj, extraction_method="llm", confidence=0.9, subject_id="c-nora",
            object_id=cid, polarity=polarity, time_text=time_text, time_start=time_start, time_end=time_end,
            time_precision=time_precision), config=ROLES_ON)
        assert res.status == "created", res
        if place:
            await self.gw.run("roles.link_place", oid=res.observation_id, cid=place)
        if partner:
            await self.gw.run("roles.link_participant", oid=res.observation_id, cid=partner)
        return res.observation_id, mid

    def iri(self, mid):
        return mint_uri("Message", mid)

    async def rows(self, mids, shown_obs=(), name="fact_sentences.rows"):
        return await self.gw.run(name, sids=["c-nora"], kids=["k-hobby"], shown_messages=[self.iri(m) for m in mids],
                                 shown_observations=list(shown_obs))

    async def record(self, mids, query="What hobby did Nora do?", shown_obs=(), lists="shown"):
        return await fs.fact_sentences_for(self.db, query, [self.iri(m) for m in mids], shown_obs, {}, lists=lists)


@pytest.fixture
async def st(db, gw):
    return await Store(db, gw).start()


async def test_single_fact_end_to_end_with_roles(st):
    oid, mid = await st.fact("pottery", time_text="yesterday", day=8, place="c-studio", partner="c-pia")
    rec = await st.record([mid])
    assert rec["fired"] and rec["subject"] == S and rec["n_matched"] == 1
    (s,) = rec["sentences"]
    assert s["text"] == "Nora did: pottery, in the studio, with Pia, on 7 May 2023."
    assert s["fact_ids"] == [oid] and s["message_id"] == mid and s["message_iri"] == st.iri(mid) and not s["as_observation"]


async def test_nameless_partner_phrase(st):
    oid, mid = await st.fact("pottery")
    await st.gw.run("roles.link_participant_phrase", oid=oid, pid="ph1", text="my kids", rv="t", now=T0)
    (s,) = (await st.record([mid]))["sentences"]
    assert s["text"].startswith("Nora did: pottery, with my kids")   # a label is never rewritten


async def test_object_text_beats_label_and_event_text_is_not_used(st):
    oid, mid = await st.fact("pottery", object_text="a pottery class with my kids")
    (s,) = (await st.record([mid]))["sentences"]
    assert s["text"].startswith("Nora did: a pottery class with Nora's kids")


async def test_list_of_two_to_six_and_over_cap_renders_nothing_not_even_singles(st):
    mids = []
    for i in range(LIST_CAP):
        _o, m = await st.fact(f"craft{i}", day=3 + i)
        mids.append(m)
    rec = await st.record(mids)
    (s,) = rec["sentences"]
    assert s["kind"] == "list" and len(s["fact_ids"]) == LIST_CAP and s["message_id"] == mids[-1]
    assert s["text"].startswith("Nora did: craft0 (said on 2023-05-03), craft1")
    _o, extra = await st.fact("craft6", day=12)
    rec = await st.record(mids + [extra])
    assert rec["sentences"] == [] and rec["n_matched"] == 7 and not rec["fired"]
    assert await st.rows(mids + [extra]) == []                       # no row at all: not even as singles


async def test_lists_group_over_shown_facts_only_and_all_form_for_measurement(st):
    _a, ma = await st.fact("mug", day=3)
    _b, mb = await st.fact("bowl", day=4)
    _c, mc = await st.fact("vase", day=5)
    shown = await st.record([ma, mb])
    (s,) = shown["sentences"]
    assert s["kind"] == "list" and len(s["fact_ids"]) == 2 and "vase" not in s["text"]
    full = await st.record([ma, mb], lists="all")
    (s,) = full["sentences"]
    assert len(s["fact_ids"]) == 3 and s["message_id"] == mb         # attached at the newest SHOWN member's turn
    assert (await st.record([]))["sentences"] == []


async def test_groups_split_by_polarity_predicate_and_kind_and_kindless_is_never_merged(st):
    _a, ma = await st.fact("mug", day=3)
    _a2, ma2 = await st.fact("cup", day=3)                              # same group as mug: a list of 2
    _b, mb = await st.fact("bowl", day=4, polarity="negated")
    _c, mc = await st.fact("vase", day=5, predicate="owns")
    # two facts whose object IS the kind concept: they have no object kind, so each is its own group
    _d, md = await st.fact("hobby", day=6, obj_id="k-hobby")
    _e, me = await st.fact("hobbies", day=7, obj_id="k-hobby", predicate="is_a")
    rows = await st.rows([ma, ma2, mb, mc, md, me])
    assert sorted(r["gn"] for r in rows) == [1, 1, 1, 1, 2]
    two = [r for r in rows if r["gn"] == 2][0]
    assert two["predicate"] == "did" and two["polarity"] == "asserted"
    assert sorted((r["predicate"], r["polarity"]) for r in rows if r["gn"] == 1) == [
        ("did", "asserted"), ("did", "negated"), ("is_a", "asserted"), ("owns", "asserted")]


async def test_source_turn_join_unshown_never_rendered(st):
    _a, ma = await st.fact("mug", day=3)
    _b, mb = await st.fact("bowl", day=4)
    rec = await st.record([mb])
    (s,) = rec["sentences"]
    assert s["fact_ids"] == [_b] and rec["n_matched"] == 2 and "mug" not in s["text"]


async def test_archived_and_deprecated_never_rendered(st):
    a, ma = await st.fact("mug", day=3)
    b, mb = await st.fact("bowl", day=4)
    c, mc = await st.fact("vase", day=5)
    st.db.store.update(f"INSERT DATA {{ <{mint_uri('Observation', a)}> {NS}archived> true }}")
    st.db.store.update(f"INSERT DATA {{ <{mint_uri('Observation', b)}> {NS}DEPRECATED_BY> <{mint_uri('Observation', c)}> }}")
    st.db.store.update(f"DELETE WHERE {{ <{mint_uri('Observation', a)}> {NS}archived> false }}")
    rec = await st.record([ma, mb, mc])
    assert rec["n_matched"] == 1
    assert [s["fact_ids"] for s in rec["sentences"]] == [[c]]


async def test_duplicate_observation_flag_is_exposed_and_sentence_still_added(st):
    a, ma = await st.fact("mug", day=3)
    b, mb = await st.fact("bowl", day=4, kind="k-hobby", predicate="owns")
    rec = await st.record([ma, mb], shown_obs=[a])
    by = {s["fact_ids"][0]: s for s in rec["sentences"]}
    assert by[a]["as_observation"] and not by[b]["as_observation"]
    assert rec["n_dup_observation"] == 1 and rec["n_sentences"] == 2


async def test_group_member_order_is_independent_of_insertion_order(tmp_path):
    orders = []
    for seed in (1, 2, 3):
        d = OxigraphClient(tmp_path / f"o{seed}.db")
        s = await Store(d, GraphGateway(d, REGISTRY)).start()
        days = list(range(3, 9))
        random.Random(seed).shuffle(days)
        mids = {}
        for day in days:
            _o, m = await s.fact(f"craft{day}", day=day)
            mids[day] = m
        rec = await s.record(list(mids.values()))
        orders.append(rec["sentences"][0]["text"])
    assert orders[0] == orders[1] == orders[2]
    assert orders[0].index("craft3") < orders[0].index("craft4") < orders[0].index("craft8")


async def test_fire_rule_unresolved_subject_no_kind_and_broad(st):
    _a, ma = await st.fact("mug", day=3)
    assert (await st.record([ma], query="What did Zed do?"))["fired"] is False          # no such subject
    assert (await st.record([ma], query="What did Nora do?"))["sentences"] == []        # no object term named
    for i in range(24):
        await st.fact(f"item{i}", day=4)
    rec = await st.record([ma])
    assert rec["n_matched"] == 25 and rec["fired"]
    await st.fact("one more", day=4)
    rec = await st.record([ma])
    assert rec["n_matched"] == 26 and not rec["fired"] and rec["sentences"] == []


async def test_nothing_is_written(st):
    _a, ma = await st.fact("mug", day=3)
    before = st.w.signature(), len(st.w.triples())
    await st.record([ma])
    await st.rows([ma], name="fact_sentences.rows_all")
    assert (st.w.signature(), len(st.w.triples())) == before


# ------------------------------------------------------------------------------------------------ the bundle and prompt
def _bundle(items, node_ids, obs_items=()):
    sections = [BundleSection(section_type="semantic", variant="observations", content=list(obs_items),
                              token_estimate=1, source_node_ids=[o["observation_id"] for o in obs_items]),
                BundleSection(section_type="conversation", content=items, token_estimate=1,
                              source_node_ids=node_ids, order="time")]
    return ContextBundle(query="q", sections=sections, total_token_estimate=2, token_budget=100, truncated=False)


def _prompt(bundle, cfg=None):
    from campy.brain.thalamus.ask import _bundle_to_prompt
    return _bundle_to_prompt(bundle, "What hobby did Nora do?", cfg or {})


async def test_golden_prompts_flag_off_and_flag_on_nothing_matching(st):
    _a, ma = await st.fact("mug", day=3)
    mb = await st.w.message("I like rain.", day=4, speaker=S)
    await st.w.spoken_by(mb, "c-nora")           # a turn with no fact
    def items():
        return [{"text": "[Nora, 2023-05-03] I did mug number 1", "type": "Message", "role": "user"},
                {"text": "[Nora, 2023-05-04] I like rain.", "type": "Message", "role": "user"}]
    iris = [st.iri(ma), st.iri(mb)]
    golden = _prompt(_bundle(items(), iris))
    assert "→ fact:" not in golden
    # flag absent / false: the function is never called; attach is not reached
    assert fs.fact_sentences_enabled({}) is False and fs.fact_sentences_enabled({"retrieval": {"fact_sentences": False}}) is False
    # flag on, nothing matches (the question names no object): the same prompt, byte for byte
    b = _bundle(items(), iris)
    section = b.sections[1]
    rec = await fs.attach_fact_sentences(st.db, "How is the weather?", ON, section, b.sections[0])
    assert rec["fired"] is False and _prompt(b) == golden


async def test_prompt_with_a_match_adds_only_the_fact_line_inside_the_turns_block(st):
    _a, ma = await st.fact("mug", day=3, time_text="yesterday")
    mb = await st.w.message("I like rain.", day=4, speaker=S)
    await st.w.spoken_by(mb, "c-nora")
    it = [{"text": "[Nora, 2023-05-03] I did mug number 1", "type": "Message", "role": "user"},
          {"text": "[Nora, 2023-05-04] I like rain.", "type": "Message", "role": "user"}]
    base = _prompt(_bundle([dict(i) for i in it], [st.iri(ma), st.iri(mb)]))
    b = _bundle([dict(i) for i in it], [st.iri(ma), st.iri(mb)])
    rec = await fs.attach_fact_sentences(st.db, "What hobby did Nora do?", ON, b.sections[1], b.sections[0])
    assert rec["fired"] and rec["n_sentences"] == 1
    out = _prompt(b)
    line = "→ fact: Nora did: mug, on 2 May 2023.\n"[:-1]
    assert out.count("→ fact:") == 1 and line in out
    assert out.replace("\n" + line, "") == base                         # the only difference is that one line
    i = out.index(line)
    assert out.rfind("<retrieved_memory", 0, i) > out.rfind("</retrieved_memory>", 0, i)   # inside the first turn's block
    assert out.index("I like rain.") > i


async def test_attach_also_records_metadata_and_reads_semantic_observation_ids(st):
    a, ma = await st.fact("mug", day=3)
    it = [{"text": "[Nora, 2023-05-03] I did mug number 1", "type": "Message", "role": "user"}]
    obs_items = [{"text": "x", "observation_id": a, "type": "Observation"}]
    b = _bundle(it, [st.iri(ma)], obs_items)
    rec = await fs.attach_fact_sentences(st.db, "What hobby did Nora do?", ON, b.sections[1], b.sections[0])
    assert rec["n_dup_observation"] == 1 and rec["sentences"][0]["as_observation"]
    assert b.sections[1].content[0]["fact_sentences"] == [{"fact_ids": [a], "message_id": ma}]


# ------------------------------------------------------------------------------------------------ flag sites
def test_flag_default_env_and_no_profile():
    assert _DEFAULT_CONFIG["retrieval"]["fact_sentences"] is False
    assert not fs.fact_sentences_enabled(_DEFAULT_CONFIG)
    cfg = apply_env_overrides({"retrieval": {}}, environ={"CAMPY_FACT_SENTENCES": "1"})
    assert fs.fact_sentences_enabled(cfg)
    assert "fact_sentences" not in {k for p in _DEFAULT_CONFIG.get("profiles", {}).values()
                                    for t in p.values() for k in (t if isinstance(t, dict) else {})}
    from campy.brain.brainstem import config as cfgmod
    for prof in cfgmod.PROFILES.values():
        assert "fact_sentences" not in prof.get("retrieval", {})


def test_toml_has_the_commented_line():
    from pathlib import Path
    import campy
    text = (Path(campy.__file__).parent / "data" / "config" / "campy.toml").read_text()
    assert "# fact_sentences = false  # in no profile" in text
