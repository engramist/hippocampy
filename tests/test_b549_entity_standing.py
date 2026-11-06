"""B549: an entity's standing is derived by rule; the tagger's label stays evidence. Real spaCy
(en_core_web_md) and a real Oxigraph store; no LLM, no model call, no WordNet.

Pure rule: position (initial / mid), case counts, the standing table, span trimming.
Graph: the flag, the writer, the three readers (kind guard, kind-label guard, B547 lexicon) inside their queries,
admission with trimming and assessment, flag off identical, the backfill (dry run, merge, idempotence).
"""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campy.brain.brainstem.config import PROFILES, _DEFAULT_CONFIG, apply_env_overrides
from campy.brain.hippocampus import entity_admission as ea
from campy.brain.hippocampus import entity_standing as es
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.loop import orchestrator as orch
from campy.brain.thalamus import question_analysis as qa

DIM = 384
T0 = datetime(2023, 8, 11, 12, 0, tzinfo=timezone.utc)
NS = "<https://campy.dev/ns#"
CFG = {"loop": {"entity_admission": True, "entity_standing": True}, "retrieval": {"graph_linking": False}}
CFG_OFF = {"loop": {"entity_admission": True, "entity_standing": False}, "retrieval": {"graph_linking": False}}


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    def fake(text, model_name=None):
        v = [0.0] * DIM
        v[hash(text.lower()) % DIM] = 1.0
        return v
    monkeypatch.setattr(embeddings_mod, "embed", fake)
    monkeypatch.setattr(orch.emb, "embed", fake)


def _doc(text):
    return es._parse(text, "en_core_web_md")


def _kt(text):
    return es.key_tokens(text)


# --- pure rule ---------------------------------------------------------------------------------

def test_position_initial_after_interjection_and_mid():
    d = _doc("Yoga is fun. Wow, Boston is great. I love Paris.")
    pos = {t.text: es.initial_position(d, t.i) for t in d if t.text in ("Yoga", "Boston", "Paris")}
    assert pos == {"Yoga": True, "Boston": True, "Paris": False}


def test_possessive_sentence_start_is_initial_and_mid_possessive_is_mid():
    d = _doc("Yoga's a great choice. We went to Paris's cafes.")
    assert es.case_counts([d], _kt("Yoga")) == (0, 1, 0)
    assert es.case_counts([d], _kt("Paris")) == (1, 0, 0)


def test_case_counts_mid_init_low_and_leading_determiner_dropped():
    docs = [_doc(t) for t in ("I love yoga.", "Yoga is great.", "We hiked the Grand Canyon.", "the grand canyon is big")]
    assert es.case_counts(docs, _kt("Yoga")) == (0, 1, 1)
    assert _kt("the Grand Canyon") == ["grand", "canyon"]
    assert es.case_counts(docs, _kt("the Grand Canyon")) == (1, 0, 1)


@pytest.mark.parametrize("mid,init,low,speakers,want", [
    (0, 0, 0, {"dave"}, "confirmed"),          # a speaker, whatever the written evidence
    (3, 0, 0, set(), "confirmed"),             # capitalised mid-sentence, never lowercase
    (1, 1, 1, set(), "confirmed"),             # a tie confirms
    (1, 0, 2, set(), "doubtful"),              # mid < low
    (0, 2, 3, set(), "doubtful"),              # capital explained by position, lowercase twin
    (0, 0, 1, set(), "doubtful"),              # only ever lowercase
    (0, 3, 0, set(), "unverified"),            # capital only at sentence start, no lowercase twin
    (0, 0, 0, set(), "unverified"),            # no evidence at all
])
def test_standing_table(mid, init, low, speakers, want):
    assert es.standing_from(["dave"] if speakers else ["x"], mid, low, init, {s.title() for s in speakers}) == want


def test_a_multi_word_speaker_is_matched_by_tokens():
    assert es.standing_from(["mary", "ann"], 0, 0, 0, {"Mary Ann"}) == "confirmed"


def test_assess_text_over_parsed_turns():
    docs = [_doc(t) for t in ("Yoga helps me relax.", "I do yoga daily.", "We flew to Boston.", "Boston was fun.")]
    assert es.assess_text("Yoga", docs, set())[0] == "doubtful"
    assert es.assess_text("Boston", docs, set())[0] == "confirmed"
    assert es.assess_text("Awww", [_doc("Awww, that is nice!")], set())[0] == "unverified"


def _trim(text, known, label_text):
    d = _doc(text)
    s = text.index(label_text)
    sp = d.char_span(s, s + len(label_text), alignment_mode="expand")
    ns, ne = es.trim_span(d, sp.start, sp.end, known)
    return d[ns:ne].text


def test_trim_drops_a_sentence_initial_wrapper_before_a_known_name():
    assert _trim("Yep Deb, that is lovely.", {"deb"}, "Yep Deb") == "Deb"
    assert _trim("Oof, Sam, that is rough.", {"sam"}, "Oof, Sam") == "Sam"
    assert _trim("Alright Sam, have fun with it!", {"sam"}, "Alright Sam") == "Sam"


def test_trim_leaves_an_unknown_remainder_and_a_mid_sentence_span():
    assert _trim("Yep Deb, that is lovely.", {"sam"}, "Yep Deb") == "Yep Deb"
    assert _trim("I told Yep Deb the news.", {"deb"}, "Yep Deb") == "Yep Deb"
    assert _trim("Boston is great.", {"boston"}, "Boston") == "Boston"


# --- the flag ----------------------------------------------------------------------------------

def test_flag_default_off_keyless_env_profile_and_packaged_template():
    assert es.entity_standing_enabled(_DEFAULT_CONFIG) is False
    assert es.entity_standing_enabled({}) is False
    assert es.entity_standing_enabled({"loop": {}}) is False
    on = apply_env_overrides({"loop": {}}, {"CAMPY_ENTITY_STANDING": "1"})
    assert es.entity_standing_enabled(on) is True
    off = apply_env_overrides({"loop": {"entity_standing": True}}, {"CAMPY_ENTITY_STANDING": "0"})
    assert es.entity_standing_enabled(off) is False
    assert PROFILES["principled"]["loop"]["entity_standing"] is True
    path = Path(orch.__file__).parents[3] / "data/config/campy.toml"
    assert "entity_standing" not in tomllib.loads(path.read_text()).get("loop", {})
    assert "# entity_standing = false" in path.read_text()


def test_the_new_queries_are_registered_with_a_sparql_form():
    names = [n for n in REGISTRY._queries if n.startswith("entity_standing.")]
    assert len(names) >= 14
    for n in names:
        assert REGISTRY.get(n).sparql


# --- graph -------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "b549.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _turn(db, gw, mid, speaker, text, session="s1", role="user"):
    if not db._execute_and_collect(f"ASK {{ ?s a {NS}Session> ; {NS}session_id> \"{session}\" }}"):
        db.write_node("Session", {"session_id": session})
    await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                 embedding_dim=DIM, role=role, byte_end=len(text), created_at=T0.isoformat())
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=T0.isoformat())
    await gw.run("capture.link_message_sent_in_session", session_id=session, message_id=mid)


async def _concept(gw, text, label="PERSON", standing=None, mentioned_in=()):
    cid = f"c-{text}"
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text=text, emb=[0.0] * DIM, gist="Entity",
                 stype="Thing", now=T0)
    if label:
        await gw.run("entity_admission.set_ner_label", cid=cid, label=label)
    if standing:
        await gw.run("entity_standing.set_standing", cid=cid, standing=standing)
    for mid in mentioned_in:
        await gw.run("concept_links.link_message_concept", mid=mid, cid=cid)
    return cid


def _prop(db, cid, prop):
    rows = db._execute_and_collect(
        f"SELECT ?v WHERE {{ ?c {NS}concept_id> \"{cid}\" ; {NS}{prop}> ?v }}")
    return [str(r["v"]) for r in rows]


def _concept_texts(db):
    rows = db._execute_and_collect(
        f"SELECT ?t WHERE {{ ?c a {NS}Concept> ; {NS}text_raw> ?t FILTER NOT EXISTS {{ ?c {NS}archived> true }} }}")
    return sorted(str(r["t"]) for r in rows)


@pytest.mark.asyncio
async def test_set_standing_replaces_the_value_and_reads_back(db, gw):
    cid = await _concept(gw, "Yoga")
    assert (await gw.run("entity_standing.concept_standing", cid=cid))[0].get("entity_standing") is None
    await gw.run("entity_standing.set_standing", cid=cid, standing="unverified")
    await gw.run("entity_standing.set_standing", cid=cid, standing="doubtful")
    assert _prop(db, cid, "entity_standing") == ["doubtful"]
    assert _prop(db, cid, "ner_label") == ["PERSON"]             # the tagger's label is untouched


@pytest.mark.asyncio
@pytest.mark.parametrize("standing,label,stype,want", [
    ("doubtful", "PERSON", "Thing", True),       # a common word the tagger caught may be a kind
    ("unverified", "PERSON", "Thing", False),
    ("confirmed", "GPE", "Thing", False),
    (None, "ORG", "Thing", False),                # not assessed: as before
    (None, None, "Thing", True),                  # a plain Concept
    ("doubtful", "PERSON", "Person", False),      # a Person is never a kind
])
async def test_can_be_kind_reads_the_standing_in_its_query(db, gw, standing, label, stype, want):
    cid = "c-x"
    await gw.run("temporal_lobe.dict_create_concept", cid=cid, text="Art", emb=[0.0] * DIM, gist="Entity",
                 stype=stype, now=T0)
    if label:
        await gw.run("entity_admission.set_ner_label", cid=cid, label=label)
    if standing:
        await gw.run("entity_standing.set_standing", cid=cid, standing=standing)
    assert await ea.can_be_kind(gw, cid) is want
    row = (await gw.run("entity_admission.concept_status", cid=cid))[0]
    assert row["can_be_kind"] is want                            # the query decided, not Python


@pytest.mark.asyncio
async def test_the_kind_label_guard_omits_a_doubtful_text(db, gw):
    await _concept(gw, "Art", standing="doubtful")
    await _concept(gw, "Boston", "GPE", standing="confirmed")
    await _concept(gw, "Awww", standing="unverified")
    await _concept(gw, "Zed", "PERSON")
    texts = {str(r["text_raw"]) for r in await gw.run("typed_objects.named_entity_texts")}
    assert texts == {"Boston", "Awww", "Zed"}


@pytest.mark.asyncio
async def test_the_b547_lexicon_reads_the_standing_in_its_query(db, gw):
    await _concept(gw, "Glad", standing="doubtful")
    await _concept(gw, "Awww", standing="unverified")
    await _concept(gw, "Anna", standing="confirmed")
    await _concept(gw, "Zed")                                      # not assessed: weak, as before
    await _concept(gw, "Boston", "GPE", standing="confirmed")
    await gw.run("temporal_lobe.dict_create_concept", cid="c-Pat", text="Pat", emb=[0.0] * DIM, gist="Entity",
                 stype="Person", now=T0)
    lex = await qa.load_lexicon(gw)
    assert set(lex.persons) == {"anna", "zed", "pat"}
    assert lex.weak_person_ids == frozenset({"c-Anna", "c-Zed"})   # Pat is strong, typed Person
    rows = {r["text_raw"]: r for r in await gw.run("question_analysis.concept_lexicon")}
    assert rows["Glad"]["person_basis"] == "" and rows["Anna"]["person_basis"] == "weak"
    assert rows["Pat"]["person_basis"] == "strong" and rows["Boston"]["person_basis"] == ""


CONV = [
    ("m1", "Deb", "Hey Maria, I started a pottery class and I love it."),
    ("m2", "Maria", "Yep Deb, slowing down and enjoying simple moments can bring a lot of balance."),
    ("m3", "Deb", "Thanks, Maria! We flew to Boston last week."),
    ("m4", "Maria", "Boston is great, I went to Boston in May."),
]


async def _conversation(db, gw):
    for mid, sp, text in CONV:
        await _turn(db, gw, mid, sp, text)


@pytest.mark.asyncio
async def test_admission_trims_a_wrapped_span_and_records_the_standing(db, gw):
    await _conversation(db, gw)
    for mid, sp, text in CONV:
        await ea.admit_turn(gw, mid, text, sp, CFG, embedding_model="m")
    texts = _concept_texts(db)
    assert "Yep Deb" not in texts and "Deb" in texts             # trimmed to the speaker
    deb = (await gw.run("orchestrator.find_concept_by_exact_text", t="Deb"))[0]["concept_id"]
    assert _prop(db, str(deb), "entity_standing") == ["confirmed"]  # a speaker of the conversation
    boston = (await gw.run("orchestrator.find_concept_by_exact_text", t="Boston"))[0]["concept_id"]
    assert _prop(db, str(boston), "entity_standing") == ["confirmed"]
    assert _prop(db, str(boston), "ner_label") == ["GPE"]
    rows = db._execute_and_collect(
        f"SELECT ?m WHERE {{ ?m {NS}message_id> \"m2\" ; {NS}MENTIONS> ?c . ?c {NS}text_raw> \"Deb\" }}")
    assert rows                                                   # the turn mentions Deb, not the wrapper


@pytest.mark.asyncio
async def test_flag_off_admits_the_wrapper_and_writes_no_standing(db, gw):
    await _conversation(db, gw)
    for mid, sp, text in CONV:
        await ea.admit_turn(gw, mid, text, sp, CFG_OFF, embedding_model="m")
    assert "Yep Deb" in _concept_texts(db)
    assert db._execute_and_collect(f"ASK {{ ?c {NS}entity_standing> ?v }}") is False


@pytest.mark.asyncio
async def test_a_common_word_is_doubtful_over_its_conversation(db, gw):
    await _turn(db, gw, "a1", "Ann", "Yoga helps me relax.")
    await _turn(db, gw, "a2", "Bob", "I do yoga every morning and love yoga.")
    cid = await _concept(gw, "Yoga", mentioned_in=("a1",))
    await es.assess_turn(gw, "a1", [(cid, "Yoga")], "Ann", CFG)
    assert _prop(db, cid, "entity_standing") == ["doubtful"]
    assert await ea.can_be_kind(gw, cid) is True                  # "yoga" may be a kind


@pytest.mark.asyncio
async def test_the_assessment_is_incremental_and_follows_the_evidence(db, gw):
    await _turn(db, gw, "b1", "Ann", "Awww, that is nice.")
    cid = await _concept(gw, "Awww", mentioned_in=("b1",))
    await es.assess_turn(gw, "b1", [(cid, "Awww")], "Ann", CFG)
    assert _prop(db, cid, "entity_standing") == ["unverified"]
    await _turn(db, gw, "b2", "Bob", "I said awww when I saw it.")
    await gw.run("concept_links.link_message_concept", mid="b2", cid=cid)
    await es.assess_turn(gw, "b2", [], "Bob", CFG)                # the turn mentions it: re-assessed
    assert _prop(db, cid, "entity_standing") == ["doubtful"]


@pytest.mark.asyncio
async def test_a_store_without_speakers_pools_its_speakerless_turns(db, gw):
    for mid, text in (("n1", "Music is great."), ("n2", "I play music daily.")):
        await gw.run("capture.create_message", message_id=mid, text_raw=text, embedding=None, embedding_model="m",
                     embedding_dim=DIM, role="user", byte_end=len(text), created_at=T0.isoformat())
    cid = await _concept(gw, "Music", "ORG", mentioned_in=("n1",))
    assert await es.assess_entity(gw, cid, "Music", set()) == "doubtful"


# --- the backfill ------------------------------------------------------------------------------

async def _wrapped_store(db, gw):
    await _conversation(db, gw)
    deb = await _concept(gw, "Deb", standing=None, mentioned_in=("m1", "m3"))
    wrap = await _concept(gw, "Yep Deb", mentioned_in=("m2",))
    await _concept(gw, "Boston", "GPE", mentioned_in=("m3", "m4"))
    db.write_node("Observation", {"observation_id": "o1", "archived": False})
    await gw.run("observations.link_about_concept", oid="o1", cid=wrap)
    return deb, wrap


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing(db, gw):
    await _wrapped_store(db, gw)
    stats = await es.backfill_entity_standing(db, None, dry_run=True)
    assert stats.merged == 1 and stats.merges == [("Yep Deb", "Deb")] and stats.mentions_moved == 1
    assert db._execute_and_collect(f"ASK {{ ?c {NS}entity_standing> ?v }}") is False
    assert "Yep Deb" in _concept_texts(db)


@pytest.mark.asyncio
async def test_backfill_assesses_merges_the_wrapper_and_is_idempotent(db, gw):
    deb, wrap = await _wrapped_store(db, gw)
    stats = await es.backfill_entity_standing(db, None, dry_run=False)
    assert stats.merged == 1 and stats.unmerged == 0
    assert "Yep Deb" not in _concept_texts(db)                    # archived, not deleted
    assert _prop(db, wrap, "archived") == ["True"]
    assert _prop(db, deb, "entity_standing") == ["confirmed"]
    mentions = db._execute_and_collect(
        f"SELECT ?m WHERE {{ ?m {NS}MENTIONS> ?c . ?c {NS}concept_id> \"{deb}\" }}")
    assert len(mentions) == 3                                     # m1, m3 and the re-pointed m2
    about = db._execute_and_collect(
        f"SELECT ?o WHERE {{ ?o {NS}OBSERVATION_ABOUT> ?c . ?c {NS}concept_id> \"{deb}\" }}")
    assert len(about) == 1                                        # the Observation edge moved too
    alt = await gw.run("orchestrator.find_concept_by_label_text", t="Yep Deb")
    assert str(alt[0]["concept_id"]) == deb                       # the old wording finds the target
    boston = (await gw.run("orchestrator.find_concept_by_exact_text", t="Boston"))[0]["concept_id"]
    assert _prop(db, str(boston), "entity_standing") == ["confirmed"]
    before = len(db.store)
    again = await es.backfill_entity_standing(db, None, dry_run=False)
    assert again.merged == 0 and len(db.store) == before          # a second run writes nothing


@pytest.mark.asyncio
async def test_backfill_lists_a_kind_that_is_a_confirmed_entity_and_never_edits_it(db, gw):
    await _conversation(db, gw)
    cid = await _concept(gw, "Boston", "GPE", mentioned_in=("m3", "m4"))
    await gw.run("kinds.mark_kind", cid=cid, scheme="kind")
    stats = await es.backfill_entity_standing(db, None, dry_run=False)
    assert stats.kind_conflicts == ["Boston"]
    assert _prop(db, cid, "kind_scheme") == ["kind"]


@pytest.mark.asyncio
async def test_the_loop_trims_the_wrapped_span_for_every_later_step(db, gw):
    await _conversation(db, gw)
    await orch.run_loop("m1", CONV[0][2], db, None, CFG, {}, role="user", speaker="Deb")
    await orch.run_loop("m2", CONV[1][2], db, None, CFG, {}, role="user", speaker="Maria")
    texts = _concept_texts(db)
    assert "Yep Deb" not in texts and "Deb" in texts
    deb = (await gw.run("orchestrator.find_concept_by_exact_text", t="Deb"))[0]["concept_id"]
    assert _prop(db, str(deb), "entity_standing") == ["confirmed"]


@pytest.mark.asyncio
async def test_the_loop_with_the_flag_off_keeps_the_wrapper(db, gw):
    await _conversation(db, gw)
    await orch.run_loop("m2", CONV[1][2], db, None, CFG_OFF, {}, role="user", speaker="Maria")
    assert "Yep Deb" in _concept_texts(db)
