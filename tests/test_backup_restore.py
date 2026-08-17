"""
Tests for B319 — Backup and Restore for Earned Memory.

Follows the pattern established by tests/test_provenance.py / test_authority.py:
a real, embedded, file-backed Kùzu database via KuzuClient, with embeddings
monkeypatched to a fixed vector so nothing here depends on network access to
a sentence-transformers / Ollama endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.schema import NODE_TABLES, REL_TABLES, SCHEMA_VERSION, init_schema
from campy.brain.hippocampus.provenance import provenance_fields
from campy.cli import backup as b
from campy.cli.main import app as cli_app

SEED_PATH = "campy/data/GistSeedExamples.md"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_FAKE_VEC = [0.01] * 384


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """See tests/test_provenance.py's identical fixture for why this patches
    each consuming module's already-bound `emb` object directly rather than
    the dotted import path."""
    from campy.brain.hippocampus import schema as _schema_mod

    def _fake_embed(text, model_name=None):
        return list(_FAKE_VEC)

    def _fake_embed_batch(texts, model_name=None):
        return [list(_FAKE_VEC) for _ in texts]

    monkeypatch.setattr(_schema_mod.emb, "embed", _fake_embed)
    monkeypatch.setattr(_schema_mod.emb, "embed_batch", _fake_embed_batch)


def _embed(head: list[float]) -> list[float]:
    return (head + [0.0] * 384)[:384]


def _seed_graph(db: KuzuClient) -> None:
    """One earned Concept, one projected Concept (same source), one earned
    Decision, and a CO_OCCURS_WITH edge between the two Concepts — enough
    surface to exercise property-level round-trip, the authority filter,
    and relationship restoration together."""
    prov_earned = provenance_fields(source="agent:test", authority="earned")
    prov_projected = provenance_fields(
        source="git:harvest", source_version="v1", authority="projected"
    )

    db.execute(
        "CREATE (n:Concept {concept_id: 'c-earned', text_raw: 'earned alpha', "
        "embedding: $emb, embedding_model: 'mini', embedding_dim: 384, confidence: 0.95, "
        "confidence_low: false, pathway_strength: 0.9, archived: false, "
        "created_at: timestamp('2026-01-01T12:00:00'), source: $source, "
        "source_version: $source_version, observed_at: timestamp($observed_at), "
        "evidence_ref: $evidence_ref, authority: $authority})",
        {"emb": _embed([1.0, 0.0, 0.0, 0.0]), **prov_earned},
    )
    db.execute(
        "CREATE (n:Concept {concept_id: 'c-projected', text_raw: 'projected beta', "
        "embedding: $emb, embedding_model: 'mini', embedding_dim: 384, confidence: 0.7, "
        "confidence_low: true, pathway_strength: 0.2, archived: false, "
        "created_at: timestamp('2026-01-02T12:00:00'), source: $source, "
        "source_version: $source_version, observed_at: timestamp($observed_at), "
        "evidence_ref: $evidence_ref, authority: $authority})",
        {"emb": _embed([0.0, 1.0, 0.0, 0.0]), **prov_projected},
    )
    db.execute(
        "CREATE (n:Decision {decision_id: 'd-earned', text_raw: 'earned decision', "
        "embedding: $emb, embedding_model: 'mini', embedding_dim: 384, confidence: 0.9, "
        "confidence_low: false, pathway_strength: 0.4, archived: false, "
        "created_at: timestamp('2026-01-03T12:00:00'), authority: 'earned'})",
        {"emb": _embed([0.2, 0.8, 0.0, 0.0])},
    )
    db.execute(
        "MATCH (a:Concept {concept_id: 'c-earned'}), (b:Concept {concept_id: 'c-projected'}) "
        "CREATE (a)-[:CO_OCCURS_WITH {count: 3, strength: 0.75}]->(b)"
    )


def _create_schema_db(db_path: Path) -> KuzuClient:
    db = KuzuClient(str(db_path))
    for table, ddl in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table} ({ddl})")
    for ddl in REL_TABLES:
        db.execute(ddl)
    return db


def _concept_rows(db: KuzuClient) -> dict[str, dict]:
    rows = {}
    result = db.execute(
        "MATCH (n:Concept) RETURN n.concept_id, n.text_raw, n.confidence, n.authority "
        "ORDER BY n.concept_id"
    )
    while result.has_next():
        row = result.get_next()
        rows[row[0]] = {"text_raw": row[1], "confidence": row[2], "authority": row[3]}
    return rows


# ---------------------------------------------------------------------------
# Round-trip + projected/earned filter (AC1, AC2)
# ---------------------------------------------------------------------------


def test_round_trip_preserves_earned_nodes_and_edges(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")
    assert manifest["node_tables"]["Concept"]["rows"] == 1  # projected excluded by default
    assert manifest["node_tables"]["Decision"]["rows"] == 1

    target = tmp_path / "restored.db"
    result = b.restore_snapshot(Path(manifest["_snapshot_dir"]), target_db_path=target, force=False)
    assert result["ok"] is True

    restored = KuzuClient(str(target))
    try:
        concepts = _concept_rows(restored)
        assert set(concepts) == {"c-earned"}
        assert concepts["c-earned"]["text_raw"] == "earned alpha"
        assert concepts["c-earned"]["confidence"] == pytest.approx(0.95)

        decisions = restored.execute(
            "MATCH (n:Decision) RETURN n.decision_id, n.text_raw"
        )
        rows = []
        while decisions.has_next():
            rows.append(tuple(decisions.get_next()))
        assert rows == [("d-earned", "earned decision")]

        # The projected Concept was excluded, so the edge (which pointed at
        # it) has nothing to attach to and is correctly absent, not errored.
        edge_count = restored.execute(
            "MATCH ()-[r:CO_OCCURS_WITH]->() RETURN count(r)"
        ).get_next()[0]
        assert edge_count == 0
    finally:
        restored.close()


def test_include_projected_flag_includes_projected_rows(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(
        db_path, workspace_id="local", out_root=tmp_path / "backups", include_projected=True
    )
    assert manifest["node_tables"]["Concept"]["rows"] == 2

    target = tmp_path / "restored.db"
    b.restore_snapshot(Path(manifest["_snapshot_dir"]), target_db_path=target, force=False)

    restored = KuzuClient(str(target))
    try:
        concepts = _concept_rows(restored)
        assert set(concepts) == {"c-earned", "c-projected"}
        assert concepts["c-projected"]["authority"] == "projected"
        edge_count = restored.execute(
            "MATCH ()-[r:CO_OCCURS_WITH]->() RETURN count(r)"
        ).get_next()[0]
        assert edge_count == 1
    finally:
        restored.close()


# ---------------------------------------------------------------------------
# Manifest contents (AC3)
# ---------------------------------------------------------------------------


def test_manifest_records_required_fields(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["campy_version"]
    assert manifest["embedding_model"]
    assert manifest["embedding_dim"] == 384
    assert manifest["workspace_id"] == "local"
    assert manifest["payload_checksum"]
    assert manifest["node_tables"]["Concept"]["rows"] == 1

    on_disk = json.loads((Path(manifest["_snapshot_dir"]) / "manifest.json").read_text())
    assert on_disk["schema_version"] == SCHEMA_VERSION
    assert on_disk["payload_checksum"] == manifest["payload_checksum"]


# ---------------------------------------------------------------------------
# backup verify (AC4, AC5, AC10)
# ---------------------------------------------------------------------------


def test_verify_detects_corrupted_payload(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")
    snapshot_dir = Path(manifest["_snapshot_dir"])

    good = b.verify_snapshot(snapshot_dir)
    assert good["ok"] is True

    node_file = next((snapshot_dir / "nodes").glob("Concept.jsonl"))
    data = bytearray(node_file.read_bytes())
    data[0] = (data[0] + 1) % 256
    node_file.write_bytes(bytes(data))

    bad = b.verify_snapshot(snapshot_dir)
    assert bad["ok"] is False
    assert bad["checksum_ok"] is False
    assert any("checksum" in err for err in bad["errors"])


def test_verify_never_touches_live_database(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")

    mtime_before = db_path.stat().st_mtime_ns
    content_before = db_path.read_bytes()

    result = b.verify_snapshot(Path(manifest["_snapshot_dir"]))
    assert result["ok"] is True

    assert db_path.stat().st_mtime_ns == mtime_before
    assert db_path.read_bytes() == content_before


def test_verify_embedding_model_mismatch_is_warning_not_failure(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")
    snapshot_dir = Path(manifest["_snapshot_dir"])

    on_disk = json.loads((snapshot_dir / "manifest.json").read_text())
    on_disk["embedding_model"] = "some-other-model/v2"
    (snapshot_dir / "manifest.json").write_text(json.dumps(on_disk))

    result = b.verify_snapshot(snapshot_dir)
    assert result["ok"] is True  # payload/counts/recall unaffected by the edit
    assert result["embedding_model_match"] is False
    assert any("embedding_model" in w for w in result["warnings"])

    # And restore still proceeds despite the mismatch.
    target = tmp_path / "restored.db"
    restore_result = b.restore_snapshot(snapshot_dir, target_db_path=target, force=False)
    assert restore_result["ok"] is True


# ---------------------------------------------------------------------------
# restore safety (AC6, AC7, AC8, AC9)
# ---------------------------------------------------------------------------


def test_restore_refuses_non_empty_target_without_force(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")

    content_before = db_path.read_bytes()
    with pytest.raises(b.BackupError):
        b.restore_snapshot(Path(manifest["_snapshot_dir"]), target_db_path=db_path, force=False)

    assert db_path.read_bytes() == content_before  # changed nothing


def test_restore_force_takes_pre_restore_snapshot_first(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    backups_root = tmp_path / "backups"
    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=backups_root)

    result = b.restore_snapshot(
        Path(manifest["_snapshot_dir"]), target_db_path=db_path, force=True
    )
    assert result["ok"] is True
    assert result["pre_restore_snapshot"]
    pre_restore_dir = Path(result["pre_restore_snapshot"])
    assert pre_restore_dir.exists()
    pre_manifest = b.read_manifest(pre_restore_dir)
    # The pre-restore snapshot is a real, independently-verifiable snapshot
    # of what was in db_path immediately before the destructive restore.
    assert pre_manifest["node_tables"]["Concept"]["rows"] >= 1


def test_restore_refuses_newer_schema_version(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")
    snapshot_dir = Path(manifest["_snapshot_dir"])
    on_disk = json.loads((snapshot_dir / "manifest.json").read_text())
    on_disk["schema_version"] = SCHEMA_VERSION + 1
    (snapshot_dir / "manifest.json").write_text(json.dumps(on_disk))

    target = tmp_path / "does-not-exist.db"
    with pytest.raises(b.BackupError, match="newer"):
        b.restore_snapshot(snapshot_dir, target_db_path=target, force=False)
    assert not target.exists()


def test_restore_of_older_schema_snapshot_migrates_forward(tmp_path):
    """A snapshot whose rows predate a schema column (simulating a pre-B313
    dump with no `authority` key at all) restores successfully, and the
    resulting database has the current schema — including the `authority`
    column added by B313 — because `_ensure_graph_schema()` always creates
    tables from the *current* `NODE_TABLES` DDL and `init_schema()` runs
    `_MIGRATIONS` afterward regardless."""
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    manifest = b.create_snapshot(db_path, workspace_id="local", out_root=tmp_path / "backups")
    snapshot_dir = Path(manifest["_snapshot_dir"])

    # Simulate an older-vintage dump: strip 'authority' from the Concept
    # row and mark the manifest as schema_version 0 (older than current).
    node_file = snapshot_dir / "nodes" / "Concept.jsonl"
    lines = node_file.read_text().splitlines()
    stripped = []
    for line in lines:
        row = json.loads(line)
        row.pop("authority", None)
        stripped.append(json.dumps(row))
    node_file.write_text("\n".join(stripped) + "\n")

    on_disk = json.loads((snapshot_dir / "manifest.json").read_text())
    on_disk["schema_version"] = 0
    # Payload changed (we edited the jsonl) — recompute the checksum so
    # this test exercises the schema-migration path, not the checksum
    # guard from test_verify_detects_corrupted_payload.
    on_disk["payload_checksum"] = b._payload_checksum(snapshot_dir)
    (snapshot_dir / "manifest.json").write_text(json.dumps(on_disk))

    target = tmp_path / "restored-old.db"
    result = b.restore_snapshot(snapshot_dir, target_db_path=target, force=False)
    assert result["ok"] is True

    restored = KuzuClient(str(target))
    try:
        cols = set()
        r = restored.execute("CALL table_info('Concept') RETURN *")
        while r.has_next():
            cols.add(str(r.get_next()[1]))
        assert "authority" in cols  # post-B312/B313 column present after migration
        row = restored.execute(
            "MATCH (n:Concept {concept_id: 'c-earned'}) RETURN n.authority"
        ).get_next()
        assert row[0] is None  # restored NULL — authority_of() would read this as "earned"
    finally:
        restored.close()


# ---------------------------------------------------------------------------
# backup prune (AC11)
# ---------------------------------------------------------------------------


def test_prune_honors_retention_and_keeps_most_recent(tmp_path):
    workspace_root = tmp_path / "backups" / "local"
    workspace_root.mkdir(parents=True)

    # Fabricate 10 bare snapshot dirs spread across distinct days.
    names = []
    for day in range(10):
        name = f"202601{day + 1:02d}T120000Z"
        snap_dir = workspace_root / name
        (snap_dir / "nodes").mkdir(parents=True)
        (snap_dir / "rels").mkdir(parents=True)
        b._write_manifest(snap_dir, {"payload_checksum": f"chk-{day}", "node_tables": {}, "rel_tables": {}})
        names.append(name)

    result = b.prune_workspace(workspace_root, keep_daily=3, keep_weekly=0, dry_run=False)

    assert names[-1] in result["kept"]  # most recent always kept
    remaining = {p.name for p in workspace_root.iterdir()}
    assert remaining == set(result["kept"])
    assert len(result["kept"]) <= 3 + 1  # never deletes the newest even beyond retention math


def test_prune_never_deletes_sole_snapshot_even_with_zero_retention(tmp_path):
    workspace_root = tmp_path / "backups" / "local"
    snap_dir = workspace_root / "20260101T000000Z"
    (snap_dir / "nodes").mkdir(parents=True)
    (snap_dir / "rels").mkdir(parents=True)
    b._write_manifest(snap_dir, {"payload_checksum": "only", "node_tables": {}, "rel_tables": {}})

    result = b.prune_workspace(workspace_root, keep_daily=0, keep_weekly=0, dry_run=False)
    assert result["deleted"] == []
    assert snap_dir.exists()


# ---------------------------------------------------------------------------
# Dedup via hard links
# ---------------------------------------------------------------------------


def test_unchanged_workspace_snapshot_is_hardlinked_not_duplicated(tmp_path):
    import os

    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    backups_root = tmp_path / "backups"
    first = b.create_snapshot(db_path, workspace_id="local", out_root=backups_root)
    second = b.create_snapshot(db_path, workspace_id="local", out_root=backups_root)

    assert second.get("deduplicated_from") == Path(first["_snapshot_dir"]).name

    first_file = Path(first["_snapshot_dir"]) / "nodes" / "Concept.jsonl"
    second_file = Path(second["_snapshot_dir"]) / "nodes" / "Concept.jsonl"
    assert os.stat(first_file).st_ino == os.stat(second_file).st_ino

    # Both snapshots verify independently even though they share inodes.
    assert b.verify_snapshot(Path(first["_snapshot_dir"]))["ok"] is True
    assert b.verify_snapshot(Path(second["_snapshot_dir"]))["ok"] is True


# ---------------------------------------------------------------------------
# CLI wiring smoke tests
# ---------------------------------------------------------------------------


def test_cli_create_list_verify_prune_restore_roundtrip(tmp_path):
    db_path = tmp_path / "brain.db"
    db = _create_schema_db(db_path)
    _seed_graph(db)
    db.close()

    backups_root = tmp_path / "backups"
    runner = CliRunner()

    create_result = runner.invoke(
        cli_app,
        ["backup", "create", "--workspace", "local", "--out", str(backups_root), "--db-path", str(db_path)],
    )
    assert create_result.exit_code == 0, create_result.output

    list_result = runner.invoke(cli_app, ["backup", "list", "--out", str(backups_root)])
    assert list_result.exit_code == 0, list_result.output
    assert "local" in list_result.output

    workspace_root = backups_root / "local"
    snapshot_name = next(p.name for p in workspace_root.iterdir() if p.is_dir())

    verify_result = runner.invoke(
        cli_app, ["backup", "verify", f"local/{snapshot_name}", "--out", str(backups_root)]
    )
    assert verify_result.exit_code == 0, verify_result.output

    prune_result = runner.invoke(cli_app, ["backup", "prune", "--out", str(backups_root)])
    assert prune_result.exit_code == 0, prune_result.output

    target_db = tmp_path / "restored-cli.db"
    restore_result = runner.invoke(
        cli_app,
        [
            "restore",
            f"local/{snapshot_name}",
            "--out",
            str(backups_root),
            "--db-path",
            str(target_db),
            "--yes",
        ],
    )
    assert restore_result.exit_code == 0, restore_result.output
    restored = KuzuClient(str(target_db))
    try:
        count = restored.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0]
        assert count == 1
    finally:
        restored.close()
