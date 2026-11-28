"""Evergreen SKOS Taxonomy unit tests (`[observations] evergreen_taxonomy`).

Uses a real Oxigraph store and deterministic in-test WordNet fixture (matching
NLTK's WordNet reader interface) so all tests run fast and offline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from campy.brain.brainstem import sweep as sweep_mod
from campy.brain.brainstem.config import (
    PROFILES,
    _DEFAULT_CONFIG,
    apply_env_overrides,
)
from campy.brain.hippocampus import evergreen_taxonomy as et
from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus import observations as obs
from campy.brain.hippocampus.graph import embeddings as embeddings_mod
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY
from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

DIM = 384
NS = "<https://campy.dev/ns#"
T0 = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Miniature WordNet (same interface as NLTK's reader)
# ---------------------------------------------------------------------------

class _Lemma:
    def __init__(self, name: str, count: int = 1):
        self._n, self._c = name, count

    def name(self) -> str:
        return self._n

    def count(self) -> int:
        return self._c


class _Syn:
    def __init__(self, name: str, lemmas: list[tuple[str, int]], lexname: str = "noun.animal"):
        self._name = name
        self._lemmas = [_Lemma(n, c) for n, c in lemmas]
        self._lex = lexname
        self._h: list[_Syn] = []
        self._ih: list[_Syn] = []

    def name(self) -> str:
        return self._name

    def lemmas(self) -> list[_Lemma]:
        return self._lemmas

    def hypernyms(self) -> list[_Syn]:
        return self._h

    def instance_hypernyms(self) -> list[_Syn]:
        return self._ih

    def lexname(self) -> str:
        return self._lex


class _WN:
    def __init__(self):
        self.s: dict[str, _Syn] = {}
        self.index: dict[str, list[str]] = {}

    def add(self, name: str, lemmas: list[tuple[str, int]], up: tuple[str, ...] = (),
            lexname: str = "noun.animal", instance_up: tuple[str, ...] = ()) -> _Syn:
        syn = _Syn(name, lemmas, lexname)
        syn._h = [self.s[u] for u in up]
        syn._ih = [self.s[u] for u in instance_up]
        self.s[name] = syn
        for lem, _ in lemmas:
            self.index.setdefault(lem.lower(), []).append(name)
        return syn

    def synsets(self, word: str, pos: str | None = None) -> list[_Syn]:
        return [self.s[n] for n in self.index.get(word.lower(), [])]

    def morphy(self, word: str, pos: str | None = None) -> str | None:
        w = word.lower()
        if w in self.index:
            return w
        if w.endswith("ies") and len(w) > 3 and (w[:-3] + "y") in self.index:
            return w[:-3] + "y"
        if w.endswith("s") and not w.endswith(("ss", "us", "is")) and w[:-1] in self.index:
            return w[:-1]
        return None

    def synset(self, name: str) -> _Syn:
        return self.s[name]

    def ensure_loaded(self) -> None:
        return None


def _fake_wordnet() -> _WN:
    w = _WN()
    w.add("entity.n.01", [("entity", 10)], lexname="noun.Tops")
    w.add("organism.n.01", [("organism", 5)], ("entity.n.01",), lexname="noun.Tops")
    w.add("animal.n.01", [("animal", 20)], ("organism.n.01",), lexname="noun.animal")
    w.add("canine.n.02", [("canine", 2)], ("animal.n.01",), lexname="noun.animal")
    w.add("dog.n.01", [("dog", 40)], ("canine.n.02",), lexname="noun.animal")
    w.add("poodle.n.01", [("poodle", 5)], ("dog.n.01",), lexname="noun.animal")
    w.add("puppy.n.01", [("puppy", 4), ("pup", 2)], ("dog.n.01",), lexname="noun.animal")
    w.add("artifact.n.01", [("artifact", 10)], ("entity.n.01",), lexname="noun.artifact")
    w.add("instrument.n.01", [("instrument", 10)], ("artifact.n.01",), lexname="noun.artifact")
    w.add("musical_instrument.n.01", [("musical_instrument", 5)], ("instrument.n.01",), lexname="noun.artifact")
    w.add("guitar.n.01", [("guitar", 15)], ("musical_instrument.n.01",), lexname="noun.artifact")
    w.add("vehicle.n.01", [("vehicle", 12)], ("artifact.n.01",), lexname="noun.artifact")
    w.add("car.n.01", [("car", 80), ("auto", 5)], ("vehicle.n.01",), lexname="noun.artifact")
    w.add("location.n.01", [("location", 10)], ("entity.n.01",), lexname="noun.location")
    w.add("city.n.01", [("city", 20)], ("location.n.01",), lexname="noun.location")
    w.add("seattle.n.01", [("Seattle", 5)], (), lexname="noun.location", instance_up=("city.n.01",))
    w.add("time.n.01", [("time", 50)], ("entity.n.01",), lexname="noun.time")
    return w


@pytest.fixture
def wn(monkeypatch):
    w = _fake_wordnet()
    monkeypatch.setattr(wn_mod, "_wn", lambda: w)
    return w


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    seen: dict[str, int] = {}

    def embed(text, model_name=None):
        v = [0.0] * DIM
        v[seen.setdefault(text.casefold(), len(seen) % DIM)] = 1.0
        return v

    monkeypatch.setattr(embeddings_mod, "embed", embed)


@pytest.fixture
def db(tmp_path):
    return OxigraphClient(tmp_path / "evergreen_tax.db")


@pytest.fixture
def gw(db):
    return GraphGateway(db, REGISTRY)


async def _add_concept(gw: GraphGateway, cid: str, text: str, *, ner_label: str | None = None) -> None:
    await gw.run(
        "temporal_lobe.dict_create_concept",
        cid=cid,
        text=text,
        emb=[0.0] * DIM,
        gist="Entity",
        stype="Thing",
        now=T0,
    )
    if ner_label:
        await gw.run("entity_admission.set_ner_label", cid=cid, label=ner_label)


async def _add_message(gw: GraphGateway, mid: str, text: str, speaker: str = "Sam") -> None:
    stamp = T0.isoformat()
    await gw.run(
        "capture.create_message",
        message_id=mid,
        text_raw=text,
        embedding=None,
        embedding_model="m",
        embedding_dim=DIM,
        role="user",
        byte_end=len(text),
        created_at=stamp,
    )
    await gw.run("capture.set_message_source", message_id=mid, speaker=speaker, occurred_at=stamp)


async def _instance_of_pairs(gw: GraphGateway) -> set[tuple[str, str]]:
    rows = gw._client._execute_and_collect(
        f"SELECT ?cl ?kl WHERE {{ ?c {NS}INSTANCE_OF> ?k . ?c {NS}text_raw> ?cl . ?k {NS}text_raw> ?kl . }}"
    )
    return {(str(r["cl"]), str(r["kl"])) for r in rows}


async def _broader_pairs(gw: GraphGateway) -> set[tuple[str, str]]:
    kinds = await kinds_mod.load_kinds(gw)
    out: set[tuple[str, str]] = set()
    for cid, k in kinds.items():
        for pid in k.broader:
            if pid in kinds:
                out.add((k.pref, kinds[pid].pref))
    return out


# ---------------------------------------------------------------------------
# 1. Config & flag gating
# ---------------------------------------------------------------------------

def test_flag_default_off_env_override_and_no_profile(monkeypatch):
    assert _DEFAULT_CONFIG["observations"]["evergreen_taxonomy"] is False
    assert et.evergreen_taxonomy_enabled(None) is False
    assert et.evergreen_taxonomy_enabled({}) is False
    assert et.evergreen_taxonomy_enabled(_DEFAULT_CONFIG) is False
    assert obs.evergreen_taxonomy_enabled(_DEFAULT_CONFIG) is False

    for prof in PROFILES.values():
        assert "evergreen_taxonomy" not in (prof.get("observations") or {})

    monkeypatch.setenv("CAMPY_EVERGREEN_TAXONOMY", "1")
    cfg = apply_env_overrides({"observations": {}})
    assert cfg["observations"]["evergreen_taxonomy"] is True
    assert et.evergreen_taxonomy_enabled(cfg) is True

    toml = (Path(__file__).resolve().parent.parent / "campy" / "data" / "config" / "campy.toml").read_text()
    assert "evergreen_taxonomy" in toml
    assert "CAMPY_EVERGREEN_TAXONOMY" in toml
    assert not any(line.strip().startswith("evergreen_taxonomy") for line in toml.splitlines())


# ---------------------------------------------------------------------------
# 2. enrich_concept_inline behavior
# ---------------------------------------------------------------------------

async def test_enrich_concept_inline_singular_kind_broader_and_alt_labels(gw, wn):
    await _add_concept(gw, "c-rex", "Rex")
    cfg_on = {"observations": {"evergreen_taxonomy": True}}

    res = await et.enrich_concept_inline(gw, "c-rex", "Rex", proposed_kind="dogs", config=cfg_on)

    assert isinstance(res, et.TaxonomyEnrichResult)
    assert res.kind_label == "dog"
    assert res.instance_of_added is True
    assert res.new_kinds_created >= 2  # "dog" + ceiling "animal" (and intermediate "canine" if any)
    assert res.new_broader >= 1
    assert res.new_alt_labels >= 1

    # Singular kind linked via INSTANCE_OF
    inst = await _instance_of_pairs(gw)
    assert ("Rex", "dog") in inst

    # Plural surface & synonym altLabels attached to "dog"
    kinds = {k.pref: k for k in (await kinds_mod.load_kinds(gw)).values()}
    assert "dog" in kinds
    assert "dogs" in kinds["dog"].alts
    assert "canine" in kinds["dog"].alts

    # WordNet BROADER walk reaches UPPER_CEILING ("animal") and stops at ceiling (no "organism"/"entity")
    broader = await _broader_pairs(gw)
    assert ("dog", "animal") in broader
    assert "animal" in kinds
    assert "organism" not in kinds
    assert "entity" not in kinds


async def test_enrich_concept_inline_skips_meta_nouns_and_closed_class(gw, wn):
    cfg_on = {"observations": {"evergreen_taxonomy": True}}
    for idx, bad in enumerate(["thing", "name", "type", "kind", "the", "and", "this", "someone"]):
        cid = f"c-bad-{idx}"
        await _add_concept(gw, cid, bad)
        res = await et.enrich_concept_inline(gw, cid, bad, proposed_kind=bad, config=cfg_on)
        assert res.kind_id is None
        assert res.instance_of_added is False

    assert await kinds_mod.load_kinds(gw) == {}


async def test_enrich_concept_inline_respects_flag_off(gw, wn):
    await _add_concept(gw, "c-rex", "Rex")
    res = await et.enrich_concept_inline(
        gw, "c-rex", "Rex", proposed_kind="dogs", config={"observations": {"evergreen_taxonomy": False}}
    )
    assert res.kind_id is None
    assert res.instance_of_added is False
    assert await kinds_mod.load_kinds(gw) == {}
    assert await _instance_of_pairs(gw) == set()


# ---------------------------------------------------------------------------
# 3. sweep_store_taxonomy & idempotency
# ---------------------------------------------------------------------------

async def test_sweep_store_taxonomy_enriches_and_is_idempotent(db, gw, wn):
    await _add_concept(gw, "c-dog", "my dogs")
    await _add_concept(gw, "c-poodle", "my poodles")
    await _add_concept(gw, "c-guitar", "acoustic guitar")
    await _add_concept(gw, "c-sam", "Sam", ner_label="PERSON")  # PERSON should not become a kind or get head-noun kind

    cfg_on = {"observations": {"evergreen_taxonomy": True}}
    stats1 = await et.sweep_store_taxonomy(db, config=cfg_on)

    assert isinstance(stats1, et.TaxonomySweepStats)
    assert stats1.entities_scanned >= 4
    assert stats1.entities_enriched >= 3
    assert stats1.new_instance_of >= 3
    assert stats1.new_broader >= 3

    inst = await _instance_of_pairs(gw)
    assert ("my dogs", "dog") in inst
    assert ("my poodles", "poodle") in inst
    assert ("acoustic guitar", "guitar") in inst
    assert all(subj != "Sam" for subj, _ in inst)

    broader = await _broader_pairs(gw)
    assert ("poodle", "dog") in broader
    assert ("dog", "animal") in broader
    assert ("guitar", "instrument") in broader or ("guitar", "musical instrument") in broader

    # Second run must be completely idempotent (0 new edges/kinds/altLabels)
    stats2 = await et.sweep_store_taxonomy(db, config=cfg_on)
    assert stats2.new_instance_of == 0
    assert stats2.new_broader == 0
    assert stats2.new_alt_labels == 0
    assert stats2.new_kinds_created == 0
    assert stats2.errors == 0


# ---------------------------------------------------------------------------
# 4. B541 cycle protection
# ---------------------------------------------------------------------------

async def test_b541_cycle_protection_prevents_reverse_and_self_loops(gw, wn):
    await _add_concept(gw, "k-animal", "animal")
    await _add_concept(gw, "k-dog", "dog")
    await _add_concept(gw, "k-poodle", "poodle")
    await kinds_mod.mark_kind(gw, "k-animal")
    await kinds_mod.mark_kind(gw, "k-dog")
    await kinds_mod.mark_kind(gw, "k-poodle")

    # Deliberately create a reverse edge animal -> dog in the store
    await kinds_mod.link_broader(gw, "k-animal", "k-dog")
    # And dog -> poodle
    await kinds_mod.link_broader(gw, "k-dog", "k-poodle")

    kinds_view = await kinds_mod.load_kinds(gw)
    _, broader_adj = et._index_kinds(kinds_view)

    # Self-loop prevented
    added_self, cyc_self = await et._safe_link_broader(gw, "k-dog", "k-dog", broader_adj, kinds_view)
    assert added_self is False
    assert cyc_self is True

    # Direct reverse (dog -> animal when animal -> dog exists) prevented
    added_rev, cyc_rev = await et._safe_link_broader(gw, "k-dog", "k-animal", broader_adj, kinds_view)
    assert added_rev is False
    assert cyc_rev is True

    # Transitive reverse (poodle -> animal when animal -> dog -> poodle exists) prevented
    added_trans, cyc_trans = await et._safe_link_broader(gw, "k-poodle", "k-animal", broader_adj, kinds_view)
    assert added_trans is False
    assert cyc_trans is True

    # Enriching k-dog inline must count cycles_prevented and must not add dog -> animal
    res = await et.enrich_concept_inline(
        gw, "k-dog", "dog", is_kind=True, config={"observations": {"evergreen_taxonomy": True}}
    )
    assert res.cycles_prevented >= 1
    assert ("dog", "animal") not in await _broader_pairs(gw)


# ---------------------------------------------------------------------------
# 5. Inline capture hook & sweep hook (flag-guarded, safe on error)
# ---------------------------------------------------------------------------

async def test_inline_capture_hook_noop_when_off_and_enriches_when_on(db, gw, wn):
    await _add_message(gw, "m1", "Sam adopted my poodle.")
    await _add_concept(gw, "c-sam", "Sam", ner_label="PERSON")
    await _add_concept(gw, "c-poodle", "poodle")

    draft = obs.ObservationDraft(
        evidence_ref="m1",
        evidence_text="Sam adopted my poodle",
        subject_text="Sam",
        subject_id="c-sam",
        predicate="owns",
        object_text="poodle",
        object_id="c-poodle",
        extraction_method="pattern",
        confidence=0.95,
    )

    # Flag OFF -> zero taxonomy writes
    cfg_off = {"observations": {"evergreen_taxonomy": False, "shacl_gate": False, "owl_properties": False}}
    res_off = await obs.record_observation(db, draft, config=cfg_off)
    assert res_off.status == "created"
    assert await kinds_mod.load_kinds(gw) == {}
    assert await _instance_of_pairs(gw) == set()

    # Flag ON on a fresh observation -> enriches object Concept inline
    await _add_message(gw, "m2", "Sam bought an acoustic guitar.")
    await _add_concept(gw, "c-guitar", "acoustic guitar")
    draft2 = obs.ObservationDraft(
        evidence_ref="m2",
        evidence_text="Sam bought an acoustic guitar",
        subject_text="Sam",
        subject_id="c-sam",
        predicate="owns",
        object_text="acoustic guitar",
        object_id="c-guitar",
        extraction_method="pattern",
        confidence=0.95,
    )
    cfg_on = {"observations": {"evergreen_taxonomy": True, "shacl_gate": False, "owl_properties": False}}
    res_on = await obs.record_observation(db, draft2, config=cfg_on)
    assert res_on.status == "created"
    assert ("acoustic guitar", "guitar") in await _instance_of_pairs(gw)
    kinds = {k.pref: k for k in (await kinds_mod.load_kinds(gw)).values()}
    assert "guitar" in kinds
    assert "musical instrument" in kinds


async def test_inline_capture_hook_swallows_taxonomy_errors(db, gw, monkeypatch, caplog):
    await _add_message(gw, "m1", "Sam bought a guitar.")
    await _add_concept(gw, "c-sam", "Sam", ner_label="PERSON")
    await _add_concept(gw, "c-guitar", "guitar")

    async def _boom(*args, **kwargs):
        raise RuntimeError("taxonomy exploded")

    monkeypatch.setattr(et, "enrich_concept_inline", _boom)

    draft = obs.ObservationDraft(
        evidence_ref="m1",
        evidence_text="Sam bought a guitar",
        subject_text="Sam",
        subject_id="c-sam",
        predicate="owns",
        object_text="guitar",
        object_id="c-guitar",
        extraction_method="pattern",
        confidence=0.95,
    )
    cfg_on = {"observations": {"evergreen_taxonomy": True, "shacl_gate": False, "owl_properties": False}}
    with caplog.at_level(logging.WARNING):
        res = await obs.record_observation(db, draft, config=cfg_on)

    assert res.status == "created"
    assert any("evergreen_taxonomy inline enrichment failed" in r.message for r in caplog.records)


async def test_derive_alt_labels_article_prep_gerund_and_idempotency(db, gw, wn):
    assert "transgender conference" in et.derive_alt_labels("a transgender conference")
    alts_race = et.derive_alt_labels("a charity race for mental health")
    assert "charity race for mental health" in alts_race and "charity race" in alts_race
    assert "field" in et.derive_alt_labels("field of study")
    assert "camping" in et.derive_alt_labels("camping trip")

    await _add_concept(gw, "c-conf", "a transgender conference")
    await _add_concept(gw, "c-race", "a charity race for mental health")
    s1 = await et.sweep_store_taxonomy(db, config={"observations": {"evergreen_taxonomy": True}})
    assert s1.new_alt_labels >= 3
    s2 = await et.sweep_store_taxonomy(db, config={"observations": {"evergreen_taxonomy": True}})
    assert s2.new_alt_labels == 0 and s2.new_broader == 0 and s2.new_instance_of == 0


async def test_sweep_hook_runs_only_when_flag_enabled(db, gw, wn, monkeypatch):
    # Stub earlier sweep steps so test focuses cleanly on Step 7.7
    monkeypatch.setattr(sweep_mod, "_decay_and_archive", AsyncMock(return_value=(0, 0, 0)))
    monkeypatch.setattr(sweep_mod, "_report_degree_hotspots", AsyncMock(return_value=[]))
    monkeypatch.setattr(sweep_mod, "_prune_session_edges", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_apply_valence_decay", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_resurrect_archived", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_index_hygiene", AsyncMock(return_value={}))
    monkeypatch.setattr(sweep_mod, "_audit_consistency", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_recompute_centroids", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_infer_retrospective_plans", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "_detect_knowledge_gaps", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(sweep_mod, "export_wiki_projection", AsyncMock(return_value={}))

    await _add_concept(gw, "c-car", "my car")

    cfg_off = {"observations": {"evergreen_taxonomy": False, "vocab_steward": False}, "sweep": {}}
    sum_off = await sweep_mod.run_sweep(db, cfg_off, None)
    assert "evergreen_taxonomy" not in sum_off
    assert await kinds_mod.load_kinds(gw) == {}

    cfg_on = {"observations": {"evergreen_taxonomy": True, "vocab_steward": False}, "sweep": {}}
    sum_on = await sweep_mod.run_sweep(db, cfg_on, None)
    assert "evergreen_taxonomy" in sum_on
    assert sum_on["evergreen_taxonomy"]["new_instance_of"] >= 1
    assert ("my car", "car") in await _instance_of_pairs(gw)
