"""tests/test_b418_vector_index_roundtrip.py — B418 proof.

The Oxigraph/GraphGateway cutover left runtime node writes un-indexed in the
sqlite-vec vector store: `upsert_lesson` writes a Lesson via
`gw.run("lessons.create_lesson", emb=vector, ...)`, a `sparql=`-bearing
NamedQuery that the gateway routes straight to `execute_write()` ->
`store.update()`, bypassing `OxigraphClient.write_node()` — the only place
that calls `vector_store.upsert_vector()` / `index_text()`. So the embedding
never lands in the index and `vector_search("Lesson", ...)` returns [] for
everything written after the cutover.

Compound issue (B418): at the time this was written, the create template
minted the node at `https://campy.dev/data/Lesson/{pk}` while `vector_search`
filtered/hydrated at `https://campy.dev/id/Lesson/{pk}` (`CID_BASE`). The B418a
fix keyed the vector at the node's REAL subject URI and made `vector_search`
match either base, so the round-trip below returns the node with correct
properties regardless — exactly what ARC's `require_roundtrip_persistence`
readiness gate asserts. B418b (2026-09-12) then unified the base: all 26
`sparql=` create templates that used to mint at `/data/`, including this one,
now mint at the canonical `/id/` — see
`test_created_lesson_hydrates_at_canonical_id_base` below.
"""

from __future__ import annotations

import math
import uuid

import pytest

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.graph.queries import REGISTRY


@pytest.fixture
def ox_client(tmp_path):
    return OxigraphClient(tmp_path / "test_b418.db")


@pytest.fixture
def gw(ox_client):
    return GraphGateway(ox_client, REGISTRY)


def _embedding() -> list[float]:
    # Deterministic, non-degenerate 384-dim vector; querying with the same
    # vector yields cosine similarity 1.0 -> guaranteed top hit if indexed.
    return [math.sin(i * 0.13) for i in range(384)]


async def _create_lesson(gw, *, lid: str, text: str, emb: list[float]) -> None:
    await gw.run(
        "lessons.create_lesson",
        lid=lid,
        text=text,
        emb=emb,
        model="test-model",
        dim=len(emb),
        domain="readiness_probe",
        type="optimization",
        scene_wl_hash=None,
        scene_graph_vector=None,
        archetype=None,
        progress_score=None,
        valence=0.5,
        now="2026-01-01T00:00:00Z",
        trig_pattern=None,
        trig_hook_type=None,
        trig_tool=None,
        trig_scope=None,
        prov_source="local:test",
        prov_source_version=None,
        prov_observed_at="2026-01-01T00:00:00Z",
        prov_evidence_ref=None,
        content_hash=None,
    )


@pytest.mark.asyncio
async def test_create_lesson_is_vector_indexed_and_recallable(gw, ox_client):
    lid = str(uuid.uuid4())
    text = "arc_readiness_probe_roundtrip"
    emb = _embedding()

    await _create_lesson(gw, lid=lid, text=text, emb=emb)

    rows = ox_client.vector_search("Lesson", "lesson_embedding_idx", emb, 5)

    assert rows, "Lesson written via the sparql= create path was not vector-indexed"
    top = rows[0]["node"]
    assert top["lesson_id"] == lid
    assert top["text_raw"] == text


@pytest.mark.asyncio
async def test_created_lesson_hydrates_at_canonical_id_base(gw, ox_client):
    # B418b: the create template now mints at the canonical /id/ base (unified
    # with mint_uri/CID_BASE); vector_search must hydrate the real node's
    # scalar props, not just fill the embedding.
    lid = str(uuid.uuid4())
    emb = _embedding()
    await _create_lesson(gw, lid=lid, text="canonical_id_base_hydration", emb=emb)

    subject = ox_client.find_subject_uri("Lesson", "lesson_id", lid)
    assert subject == f"https://campy.dev/id/Lesson/{lid}"

    rows = ox_client.vector_search("Lesson", "lesson_embedding_idx", emb, 5)
    node = rows[0]["node"]
    assert node["domain"] == "readiness_probe"
    assert node["valence"] == 0.5


@pytest.mark.asyncio
async def test_created_lesson_is_text_recallable_via_fts(gw, ox_client):
    lid = str(uuid.uuid4())
    emb = _embedding()
    await _create_lesson(gw, lid=lid, text="uniqueftsprobe_zqx", emb=emb)

    rows = ox_client.fts_search("Lesson", "lesson_fts_idx", "uniqueftsprobe_zqx", 5)
    assert rows, "create_lesson text was not indexed into FTS"
    assert rows[0]["node"]["lesson_id"] == lid
