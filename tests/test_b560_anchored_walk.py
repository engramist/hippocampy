"""B560: the concept walk is anchored on the question's subject, through `Message -SPOKEN_BY-> Concept`.

Real Oxigraph store, real gateway, no model, no LLM. Pins:
- the flag `[loop] spoken_by` (default off, env, in the principled profile); the edge is written by the Loop under
  the flag and not without it; the backfill (dry run, idempotent, never creates a Concept);
- the walk query: only the subject's own turns (another speaker's linked turn is left out), hop 1 before hop 2,
  more seeds before fewer, evidence before recency, shown/archived/assistant turns out, nothing without a subject
  or a seed; a regression for the scope bug (a FILTER inside a UNION branch cannot see an outer variable, so the
  first version of the anchor silently returned no turn at all);
- the stage: no analysis, no subject, a tie or no seed adds nothing and the query never runs; profile main runs
  no walk.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import spoken_by as sb
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.thalamus import bundle_compiler as bc
from campy.brain.thalamus.question_analysis import QuestionAnalysis

pytestmark = pytest.mark.asyncio

DIM = 384
NS = "<https://campy.dev/ns#"
T0 = datetime(2023, 5, 7, 12, 0, tzinfo=timezone.utc)
WALK = {"retrieval": {"graph_linking": True, "graph_linking_limit": 12, "conversation_token_budget": 0},
        "observations": {"retrieval": False}}
MAIN = {"retrieval": {"graph_linking": True, "graph_linking_limit": 0, "conversation_token_budget": 0},
        "observations": {"retrieval": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    def fake(text, model_name=None):
        v = [0.0] * DIM
        v[hash(text.lower()) % DIM] = 1.0
        return v
    monkeypatch.setattr(embeddings_mod, "embed", fake)
    monkeypatch.setattr(orch.emb, "embed", fake)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b560.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


class Store:
    def __init__(self, db, gw):
        self.db, self.gw, self.n = db, gw, 0

    async def concept(self, cid, text):
        await self.gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text,
                          emb=[0.0] * DIM, gist="Category", stype="DefinedTerm", now=T0)

    async def message(self, text, *, speaker="Sam", spoken_by="c-sam", mentions=(), day=1, role="user", mid=None):
        self.n += 1
        mid = mid or f"m{self.n}"
        stamp = f"2023-05-{day:02d}T12:00:00+00:00"
        await self.gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                          embedding_model="m", embedding_dim=DIM, role=role, byte_end=len(text), created_at=stamp)
        await self.gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)
        if spoken_by:
            self.db.write_edge("SPOKEN_BY", mint_uri("Message", mid), mint_uri("Concept", spoken_by))
        for cid in mentions:
            self.db.write_edge("MENTIONS", mint_uri("Message", mid), mint_uri("Concept", cid))
        return mid

    def edges(self, edge):
        rows = self.db._execute_and_collect(f"SELECT ?s ?o WHERE {{ ?s {NS}{edge}> ?o }}")
        return {(str(r["s"]).rsplit("/", 1)[-1], str(r["o"]).rsplit("/", 1)[-1]) for r in rows}


@pytest.fixture
def store(db, gw):
    return Store(db, gw)


async def walk(gw, seeds, subject="c-sam", shown=()):
    rows = await gw.run("thalamus.bundle_concept_walk", sids=list(seeds),
                        subj_ids=[subject] if subject else [], shown=list(shown))
    return rows


def mids(rows):
    return [str(r["i"]).rsplit("/", 1)[-1] for r in rows]


def analysis(*concepts, subject=None, tie=False, unresolved=()):
    return QuestionAnalysis(
        question="q?", text="q?", subject_id=subject, subject=subject, anchor_ids=(subject,) if subject else (),
        subjects=tuple({"id": s, "label": s} for s in ([subject] if subject else [])), tie=tie,
        subject_unresolved=tuple(unresolved),
        concepts=tuple({"id": c, "label": c, "span": c, "source": "t", "role": r} for c, r in concepts))


# --- the flag -----------------------------------------------------------------------

async def test_flag_default_off_env_on_and_in_the_principled_profile():
    assert _DEFAULT_CONFIG["loop"]["spoken_by"] is False
    assert sb.spoken_by_enabled(_DEFAULT_CONFIG) is False and sb.spoken_by_enabled({}) is False
    assert sb.spoken_by_enabled({"loop": {"spoken_by": True}}) is True
    assert apply_env_overrides({"loop": {}}, {"CAMPY_SPOKEN_BY": "1"})["loop"]["spoken_by"] is True
    assert PROFILES["principled"]["loop"]["spoken_by"] is True
    assert "spoken_by" not in PROFILES["main"].get("loop", {})


# --- the edge is written by the Loop, under the flag only ---------------------------

def _loop_cfg(on):
    return {"loop": {"spoken_by": on}, "retrieval": {"graph_linking": False}}


async def _loop(db, gw, mid, text, speaker, on, monkeypatch):
    monkeypatch.setattr(orch, "classify_concept",
                        lambda *a, **k: {"system": "noise", "gist_class": None, "confidence": 0.1, "vector": None})
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None,
                 embedding_model="m", embedding_dim=DIM, role="user", byte_end=len(text),
                 created_at=T0.isoformat())
    await orch.run_loop(mid, text, db, None, _loop_cfg(on), {}, role="user", speaker=speaker)


def _speaker_of(db, mid):
    rows = db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?m {NS}message_id> \"{mid}\" ; {NS}SPOKEN_BY> ?c . ?c {NS}text_raw> ?t }}")
    return sorted(str(r["t"]) for r in rows)


async def test_the_loop_writes_spoken_by_under_the_flag(db, gw, monkeypatch):
    await _loop(db, gw, "a1", "I went hiking today.", "Caroline", True, monkeypatch)
    await _loop(db, gw, "a2", "Sounds fun, I stayed in.", "Melanie", True, monkeypatch)
    await _loop(db, gw, "a3", "More hiking tomorrow.", "Caroline", True, monkeypatch)
    assert _speaker_of(db, "a1") == ["Caroline"] and _speaker_of(db, "a2") == ["Melanie"]
    assert _speaker_of(db, "a3") == ["Caroline"]
    caro = {r["concept_id"] for r in await gw.run("orchestrator.find_concept_by_exact_text", t="Caroline")}
    assert len(caro) == 1                                      # the one Concept the Loop seeds, not a second


async def test_the_loop_writes_nothing_without_the_flag(db, gw, monkeypatch):
    await _loop(db, gw, "b1", "I went hiking today.", "Caroline", False, monkeypatch)
    assert _speaker_of(db, "b1") == []


async def test_a_generic_speaker_gets_no_edge(db, gw, monkeypatch):
    await _loop(db, gw, "g1", "I went hiking today.", "user", True, monkeypatch)
    await _loop(db, gw, "g2", "I went hiking today again.", None, True, monkeypatch)
    assert _speaker_of(db, "g1") == [] and _speaker_of(db, "g2") == []


# --- the backfill -------------------------------------------------------------------

async def _unlinked_store(store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    a = await store.message("model kit A", spoken_by=None)
    b = await store.message("model kit B", spoken_by=None, speaker="Ann")        # a speaker with no Concept
    c = await store.message("model kit C", spoken_by=None, speaker="user")       # a role, not a person
    d = await store.message("model kit D", spoken_by=None)
    return a, b, c, d


async def test_backfill_dry_run_writes_nothing_then_apply_is_idempotent(db, gw, store):
    a, b, c, d = await _unlinked_store(store)
    dry = await sb.backfill_spoken_by(gw, dry_run=True)
    assert dry.turns_seen == 4 and dry.linked == 2 and store.edges("SPOKEN_BY") == set()
    assert dry.generic_speaker == 1 and dry.no_concept == 1 and dry.unresolved_names == {"Ann": 1}
    first = await sb.backfill_spoken_by(gw, dry_run=False)
    assert first.linked == 2 and store.edges("SPOKEN_BY") == {(a, "c-sam"), (d, "c-sam")}
    second = await sb.backfill_spoken_by(gw, dry_run=False)
    assert second.linked == 0 and second.already_linked_before == 2 and second.turns_seen == 2
    assert store.edges("SPOKEN_BY") == {(a, "c-sam"), (d, "c-sam")}
    names = {str(r["t"]) for r in db._execute_and_collect(f"SELECT ?t WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> ?t }}")}
    assert "Ann" not in names                                  # a backfill never creates a Concept


# --- the walk query -----------------------------------------------------------------

async def test_the_walk_returns_the_subjects_turns_only(db, gw, store):
    """Scope-bug regression: the subject's own linked turn must come back (the first anchor, a FILTER inside a
    UNION branch comparing a label bound outside it, returned nothing)."""
    await store.concept("c-sam", "Sam")
    await store.concept("c-amy", "Amy")
    await store.concept("c-kit", "model kit")
    mine = await store.message("I built a model kit", mentions=["c-kit"], day=2)
    theirs = await store.message("I built a model kit too", speaker="Amy", spoken_by="c-amy", mentions=["c-kit"], day=3)
    unlinked = await store.message("my model kit", spoken_by=None, mentions=["c-kit"], day=4)
    rows = await walk(gw, ["c-kit"])
    assert mids(rows) == [mine]
    assert mids(await walk(gw, ["c-kit"], subject="c-amy")) == [theirs]
    assert unlinked not in mids(rows)
    assert rows[0]["speaker"] == "Sam" and rows[0]["h"] == 1 and "model kit" in rows[0]["text"]


async def test_no_subject_or_no_seed_returns_nothing(db, gw, store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    await store.message("I built a model kit", mentions=["c-kit"])
    assert await walk(gw, ["c-kit"], subject=None) == []
    assert await walk(gw, [], subject="c-sam") == []
    assert await walk(gw, ["c-kit"], subject="c-nobody") == []


async def test_second_hop_reaches_siblings_parents_and_children_of_the_subjects_turns(db, gw, store):
    for cid, text in [("c-sam", "Sam"), ("c-kit", "model kit"), ("c-f15", "Revell F-15 Eagle"),
                      ("c-spit", "Tamiya Spitfire"), ("c-hobby", "hobby")]:
        await store.concept(cid, text)
    for child, parent in [("c-f15", "c-kit"), ("c-spit", "c-kit"), ("c-kit", "c-hobby")]:
        await gw.run("concept_links.link_is_a", cid=child, pid=parent)
    a = await store.message("The F-15 is done.", mentions=["c-f15"], day=3)
    b = await store.message("The Spitfire is next.", mentions=["c-spit"], day=9)
    c = await store.message("I love my hobby.", mentions=["c-hobby"], day=15)
    rows = await walk(gw, ["c-f15"])
    assert sorted(mids(rows)) == sorted([a, b]) and {str(r["i"]).rsplit("/", 1)[-1]: r["h"] for r in rows} == {a: 1, b: 2}
    rows = await walk(gw, ["c-kit"])
    assert sorted(mids(rows)) == sorted([a, b, c]) and all(r["h"] == 2 for r in rows)


async def test_order_is_hop_then_seeds_then_evidence_then_newest(db, gw, store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    await store.concept("c-tank", "tank")
    await store.concept("c-sib", "kit sibling")
    await store.concept("c-top", "top")
    await gw.run("concept_links.link_is_a", cid="c-kit", pid="c-top")
    await gw.run("concept_links.link_is_a", cid="c-sib", pid="c-top")
    hop2 = await store.message("sibling turn, newest", mentions=["c-sib"], day=29)
    one_new = await store.message("kit only, newer", mentions=["c-kit"], day=20)
    one_old = await store.message("kit only, older", mentions=["c-kit"], day=5)
    two = await store.message("kit and tank", mentions=["c-kit", "c-tank"], day=2)
    rows = await walk(gw, ["c-kit", "c-tank"])
    # two seeds first, then one seed newest first, hop 2 last whatever its date
    assert mids(rows) == [two, one_new, one_old, hop2]
    # the evidence count breaks a tie between equal seeds and dates: a turn the subject's Observations rest on first
    ev = await store.message("kit with a fact", mentions=["c-kit"], day=20)
    plain = await store.message("kit without", mentions=["c-kit"], day=20)
    oid = "o-1"                                   # a fact about Sam whose evidence turn is `ev`
    db.write_edge("HAS_SUBJECT", mint_uri("Observation", oid), mint_uri("Concept", "c-sam"))
    db.write_edge("EVIDENCED_BY", mint_uri("Observation", oid), mint_uri("Message", ev))
    rows = await walk(gw, ["c-kit"])
    got = mids(rows)
    assert got.index(ev) < got.index(plain)


async def test_shown_archived_and_assistant_turns_are_out(db, gw, store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    keep = await store.message("model kit A", mentions=["c-kit"], day=3)
    shown = await store.message("model kit B", mentions=["c-kit"], day=4)
    gone = await store.message("model kit C", mentions=["c-kit"], day=5)
    asst = await store.message("model kit D", mentions=["c-kit"], day=6, role="assistant")
    await db.execute_write(f"INSERT DATA {{ <https://campy.dev/id/Message/{gone}> {NS}archived> true }}")
    rows = await walk(gw, ["c-kit"], shown=[f"https://campy.dev/id/Message/{shown}", "an-observation-id"])
    assert mids(rows) == [keep] and asst not in mids(rows)


# --- the stage ----------------------------------------------------------------------

def _spy(monkeypatch, gw):
    ran = []
    real = gw.run

    async def spy(name, **kw):
        ran.append((name, kw))
        return await real(name, **kw)
    monkeypatch.setattr(bc, "get_gateway", lambda _db: type("G", (), {"run": staticmethod(spy)})())
    return ran


async def _kit_store(store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-amy", "Amy")
    await store.concept("c-kit", "model kit")
    await store.message("I finished the Spitfire model kit", mentions=["c-kit"], day=2)
    await store.message("Amy built a model kit as well", speaker="Amy", spoken_by="c-amy", mentions=["c-kit"], day=3)


async def test_the_stage_shows_the_subjects_turns_stamped_and_oldest_first(db, gw, store):
    await _kit_store(store)
    await store.message("Another model kit, the Tiger", mentions=["c-kit"], day=9)
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam")
    sec = await bc._stage_concept_walk(db, "What did Sam do with the model kit?", WALK, set(), analysis=a)
    assert sec.section_type == "linked" and sec.reads == ["concept_ids", "subject_id"]
    assert [c["text"] for c in sec.content] == [
        "[Sam, 2023-05-02 12:00] I finished the Spitfire model kit", "[Sam, 2023-05-09 12:00] Another model kit, the Tiger"]
    assert all(c["type"] == "Message" for c in sec.content) and len(sec.source_node_ids) == 2


async def test_the_stage_adds_nothing_without_an_anchor_and_never_runs_the_query(db, gw, store, monkeypatch):
    await _kit_store(store)
    ran = _spy(monkeypatch, gw)
    cases = {
        "no analysis": None,
        "no subject (a first-person question)": analysis(("c-kit", "entity")),
        "a tie": analysis(("c-sam", "person"), ("c-amy", "person"), ("c-kit", "entity"), subject="c-sam", tie=True),
        "an unresolved name": analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam", unresolved=("Zed",)),
        "no seed": analysis(("c-sam", "person"), subject="c-sam"),
    }
    for label, a in cases.items():
        assert await bc._stage_concept_walk(db, "q", WALK, set(), analysis=a) is None, label
    assert ran == []


async def test_the_stage_passes_the_subject_the_seeds_and_what_is_shown(db, gw, store, monkeypatch):
    await _kit_store(store)
    ran = _spy(monkeypatch, gw)
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam")
    await bc._stage_concept_walk(db, "q", WALK, {"https://campy.dev/id/Message/m1"}, analysis=a)
    (name, kw), = ran
    assert name == "thalamus.bundle_concept_walk"
    assert kw["sids"] == ["c-kit"] and kw["subj_ids"] == ["c-sam"] and kw["shown"] == ["https://campy.dev/id/Message/m1"]


async def test_the_cap_is_graph_linking_limit(db, gw, store):
    await store.concept("c-sam", "Sam")
    await store.concept("c-kit", "model kit")
    for i in range(6):
        await store.message(f"model kit number {i}", mentions=["c-kit"], day=2 + i)
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam")
    cfg = {**WALK, "retrieval": {**WALK["retrieval"], "graph_linking_limit": 4}}
    sec = await bc._stage_concept_walk(db, "q", cfg, set(), analysis=a)
    assert [c["text"].split("] ")[-1] for c in sec.content] == [f"model kit number {i}" for i in (2, 3, 4, 5)]


async def test_profile_main_runs_no_walk(db, gw, store, monkeypatch):
    await _kit_store(store)
    ran = _spy(monkeypatch, gw)
    a = analysis(("c-sam", "person"), ("c-kit", "entity"), subject="c-sam")
    assert await bc._stage_concept_walk(db, "q", MAIN, set(), analysis=a) is None
    assert ran == []
