"""
campy/cli/backup.py — B319: backup and restore for earned memory.

Campy's `CLAUDE.md` claims "KuzuDB is the single source of truth for all
persistent agent state." B313 split that claim into `earned` (Campy is the
only place the fact lives — losing it loses it forever) and `projected`
(a rebuildable mirror of something owned elsewhere). Before this module,
nothing backed that claim up: `campy/cli/graph_io.py` is a developer JSONL
dump/restore tool with no scheduling, retention, or verified restore.

    campy backup create   [--workspace ID|--all] [--out DIR] [--include-projected]
    campy backup list     [--workspace ID]
    campy backup verify   SNAPSHOT
    campy backup prune    [--keep-daily N --keep-weekly N]
    campy restore         SNAPSHOT [--workspace ID] [--force]

Design decisions (see backlog/B319.md for the full rationale):

  - Snapshot format is the existing JSONL dump from
    `campy/brain/hippocampus/graph/export.py` (`export_graph`/`import_graph`),
    not a copy of the Kùzu database directory — a file copy is faster but
    opaque and version-locked to the pinned Kùzu 0.11.3.
  - Default excludes `authority='projected'` rows (B313's
    `include_projected=False`) — reused, not reimplemented.
  - Every snapshot carries a manifest: `export_graph_dump()`'s own fields
    (format_version, engine, embedding_dim, per-table row counts, ...) plus
    `schema_version`, `campy_version`, `embedding_model`, `workspace_id`,
    and a `payload_checksum` covering every JSONL file's bytes.
  - `backup verify` restores into a private temp-directory database and
    NEVER opens/writes the live database path — see `verify_snapshot()`,
    which does not even accept a live-db argument, by construction.
  - `restore --force` takes an automatic pre-restore snapshot of whatever
    is at the target path before touching it, and prints its path first.
  - `restore` refuses a snapshot whose `schema_version` is newer than this
    running code's `schema.SCHEMA_VERSION`; older snapshots restore fine
    and `init_schema()` runs afterward so `_MIGRATIONS` brings the
    restored database's columns up to date.
  - Workspace-aware from the start (B316 composes, does not block): today
    there is exactly one implicit workspace, `"local"`; `--all` iterates
    `_list_workspace_ids()`, which is the one function B316's router will
    replace with a real directory walk — every other function here already
    takes `workspace_id` as a plain parameter and needs no rewrite.
  - Unchanged-workspace dedup: when a fresh dump's payload checksum matches
    the immediately preceding snapshot's, the new snapshot's JSONL files
    are replaced with hard links to the prior snapshot's files rather than
    kept as a second on-disk copy. Every snapshot directory stays fully
    self-contained and independently restorable/prunable — the OS, not
    bookkeeping in this module, is what makes the content shared.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from campy.brain.hippocampus.graph.export import export_graph, import_graph
from campy.brain.hippocampus.schema import SCHEMA_VERSION
from campy.paths import get_backup_root, get_database_path

app = typer.Typer(help="Backup and restore earned memory (B319)")
console = Console()

_MANIFEST_NAME = "manifest.json"
_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_TIMESTAMP_FMT = "%Y%m%dT%H%M%SZ"
_TIMESTAMP_RE = re.compile(r"^(\d{8}T\d{6}Z)")


class BackupError(Exception):
    """Raised for refusals/failures in the backup/restore flow.

    A distinct type (rather than bare ValueError/RuntimeError) so CLI
    wrappers can catch exactly this and print a clean message instead of a
    traceback, while letting genuine bugs surface normally.
    """


# ---------------------------------------------------------------------------
# Workspace discovery (Task 5 — workspace-aware from the start)
# ---------------------------------------------------------------------------


def _list_workspace_ids() -> list[str]:
    """Every workspace with a database to back up.

    B316 (per-workspace databases) has not landed. Until it does there is
    exactly one implicit workspace, `"local"`, backed by
    `campy.paths.get_database_path()`. When B316 lands, this is the one
    function that needs to change — it should walk the router's workspace
    root and return real ids; every other function in this module already
    takes `workspace_id` as an explicit parameter and requires no rewrite.
    """
    return ["local"]


def _db_path_for_workspace(workspace_id: str, *, override: Optional[Path] = None) -> Path:
    """Resolve the database path for `workspace_id`.

    `override` lets CLI commands accept `--db-path` (matching
    `graph_io.py`'s existing `--db-path`/`--db` convention) for
    testability and for explicit non-default databases. Ignores
    `workspace_id` today (single-database mode) — kept as a parameter so
    the B316 multi-workspace lookup is a one-line change here later.
    """
    if override is not None:
        return Path(override)
    return get_database_path()


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _configured_embedding_model() -> str:
    """Best-effort read of the configured embedding model name.

    Mirrors `brain_daemon.py`'s own default-resolution
    (`config.get("embeddings", {}).get("model", ...)`). Explicit CLI
    commands may run without a daemon or even without a config file (e.g.
    a fresh checkout's first `campy backup create`), so a missing/invalid
    config degrades to the same default `brain_daemon.py` would use rather
    than raising — recording *a* model name in the manifest matters more
    here than being strict about config loading.
    """
    try:
        from campy.brain.brainstem.config import load_config

        config = load_config()
    except Exception:
        return _DEFAULT_EMBEDDING_MODEL
    return config.get("embeddings", {}).get("model", _DEFAULT_EMBEDDING_MODEL)


def _campy_version() -> str:
    try:
        from importlib.metadata import version

        return version("hippocampy")
    except Exception:
        return "0.0.0-unknown"


def _payload_checksum(snapshot_dir: Path) -> str:
    """sha256 over every nodes/*.jsonl + rels/*.jsonl file's bytes, in a
    stable (sorted-path) order — reproducible, and a single flipped byte
    anywhere in the payload changes the digest (see `backup verify`'s
    corruption-detection acceptance criterion)."""
    hasher = hashlib.sha256()
    for sub in ("nodes", "rels"):
        subdir = snapshot_dir / sub
        if not subdir.exists():
            continue
        for path in sorted(subdir.glob("*.jsonl")):
            hasher.update(path.name.encode("utf-8"))
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _write_manifest(snapshot_dir: Path, manifest: dict) -> None:
    with (snapshot_dir / _MANIFEST_NAME).open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def read_manifest(snapshot_dir: Path) -> dict:
    manifest_path = Path(snapshot_dir) / _MANIFEST_NAME
    if not manifest_path.exists():
        raise BackupError(f"{snapshot_dir} does not look like a snapshot (no {_MANIFEST_NAME})")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Snapshot directory discovery
# ---------------------------------------------------------------------------


def _workspace_root(workspace_id: str, *, backup_root: Optional[Path] = None) -> Path:
    root = Path(backup_root) if backup_root is not None else get_backup_root()
    return root / workspace_id


def _list_snapshot_dirs(workspace_root: Path) -> list[Path]:
    if not workspace_root.exists():
        return []
    return sorted(
        (p for p in workspace_root.iterdir() if p.is_dir() and (p / _MANIFEST_NAME).exists()),
        key=lambda p: p.name,
    )


def _latest_snapshot_dir(workspace_root: Path, *, exclude: Optional[Path] = None) -> Optional[Path]:
    dirs = [d for d in _list_snapshot_dirs(workspace_root) if d != exclude]
    return dirs[-1] if dirs else None


def resolve_snapshot_path(snapshot: str, *, backup_root: Optional[Path] = None) -> Path:
    """Resolve a CLI-supplied `SNAPSHOT` argument to a real directory.

    Accepts either a filesystem path (absolute or relative to cwd) or a
    snapshot id relative to the backup root, e.g. `local/20260816T120000Z`
    (what `backup list` prints).
    """
    candidate = Path(snapshot)
    if (candidate / _MANIFEST_NAME).exists():
        return candidate
    root = Path(backup_root) if backup_root is not None else get_backup_root()
    relative = root / snapshot
    if (relative / _MANIFEST_NAME).exists():
        return relative
    raise BackupError(f"No snapshot found at {snapshot!r} (checked {candidate} and {relative})")


# ---------------------------------------------------------------------------
# Task 1 + 5 — campy backup create
# ---------------------------------------------------------------------------


def _hardlink_dedupe(snapshot_dir: Path, prior_dir: Path) -> None:
    """Replace `snapshot_dir`'s JSONL files with hard links to `prior_dir`'s
    byte-identical ones, so two snapshots with the same payload share disk
    blocks instead of duplicating them. Falls back to a plain copy if the
    filesystem doesn't support hard links (e.g. across devices) —
    correctness (`snapshot_dir` stays fully self-contained) matters more
    than the space saving in that case.
    """
    import os

    for sub in ("nodes", "rels"):
        new_sub = snapshot_dir / sub
        prior_sub = prior_dir / sub
        if not new_sub.exists() or not prior_sub.exists():
            continue
        for new_file in sorted(new_sub.glob("*.jsonl")):
            prior_file = prior_sub / new_file.name
            if not prior_file.exists():
                continue
            new_file.unlink()
            try:
                os.link(prior_file, new_file)
            except OSError:
                shutil.copyfile(prior_file, new_file)


def create_snapshot(
    db_path: Path,
    *,
    workspace_id: str = "local",
    out_root: Optional[Path] = None,
    include_projected: bool = False,
    skip_if_unchanged: bool = True,
    extra_manifest_fields: Optional[dict] = None,
) -> dict:
    """Create one JSONL snapshot of `db_path`, tagged with `workspace_id`.

    Returns the written manifest dict, with `_snapshot_dir` added (the
    absolute path — informational, not itself persisted to manifest.json).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise BackupError(f"database not found: {db_path}")

    workspace_root = _workspace_root(workspace_id, backup_root=out_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime(_TIMESTAMP_FMT)
    snapshot_dir = workspace_root / stamp
    suffix = 1
    while snapshot_dir.exists():
        snapshot_dir = workspace_root / f"{stamp}-{suffix}"
        suffix += 1

    export_manifest = export_graph(db_path, snapshot_dir, include_projected=include_projected)
    checksum = _payload_checksum(snapshot_dir)

    manifest = dict(export_manifest)
    manifest.update(
        {
            "schema_version": SCHEMA_VERSION,
            "campy_version": _campy_version(),
            "embedding_model": _configured_embedding_model(),
            "workspace_id": workspace_id,
            "payload_checksum": checksum,
            "source_db_path": str(db_path),
        }
    )
    if extra_manifest_fields:
        manifest.update(extra_manifest_fields)

    if skip_if_unchanged:
        prior_dir = _latest_snapshot_dir(workspace_root, exclude=snapshot_dir)
        if prior_dir is not None:
            try:
                prior_manifest = read_manifest(prior_dir)
            except BackupError:
                prior_manifest = {}
            if prior_manifest.get("payload_checksum") == checksum:
                _hardlink_dedupe(snapshot_dir, prior_dir)
                manifest["deduplicated_from"] = prior_dir.name

    _write_manifest(snapshot_dir, manifest)
    manifest["_snapshot_dir"] = str(snapshot_dir)
    return manifest


# ---------------------------------------------------------------------------
# Task 2 — campy backup verify (never touches the live database)
# ---------------------------------------------------------------------------


def _reexport_counts(db_path: Path) -> dict:
    """Re-derive per-table row counts from `db_path` by reusing
    `export_graph_dump()` against a scratch output directory, rather than
    hand-writing new counting queries (which would grow the B314 inline-
    Cypher ratchet for no reason — the counting Cypher already exists and
    is already counted)."""
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

    with tempfile.TemporaryDirectory(prefix="campy-backup-count-") as scratch:
        db = KuzuClient(str(db_path), read_only=True)
        try:
            from campy.brain.hippocampus.graph.export import export_graph_dump

            return export_graph_dump(db, scratch, include_projected=True)
        finally:
            db.close()


def _expected_counts_from_dump(snapshot_dir: Path, manifest: dict) -> dict:
    """What `import_graph_dump()` should actually produce from this
    snapshot's own JSONL files — deliberately *not* just a copy of
    `manifest`'s own counts.

    Node counts always carry over 1:1 (every dumped node row inserts).
    Rel counts do not: B313's documented behavior is that a relationship
    row whose endpoint was a `projected` node omitted from the dump (the
    default) fails its `MATCH` on import and is silently skipped — see
    `export.py`'s `import_graph_dump()` docstring. That is expected
    behavior, not corruption, so it must not fail `backup verify`. This
    function re-derives the *restorable* rel count directly from the
    snapshot's own node/rel JSONL files (which endpoints are actually
    present) so the comparison in `verify_snapshot()` catches genuine
    import discrepancies without also flagging the documented, intentional
    ones.
    """
    from campy.brain.hippocampus.table_registry import pk_for

    node_tables = {
        name: {"rows": info.get("rows", 0)} for name, info in manifest.get("node_tables", {}).items()
    }

    present_pks: dict[str, set] = {}
    for table_name in manifest.get("node_tables", {}):
        pk_name = pk_for(table_name)
        node_file = snapshot_dir / "nodes" / f"{table_name}.jsonl"
        pks: set = set()
        if pk_name and node_file.exists():
            for line in node_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if pk_name in row:
                    pks.add(row[pk_name])
        present_pks[table_name] = pks

    rel_tables = {}
    for rel_name in manifest.get("rel_tables", {}):
        rel_file = snapshot_dir / "rels" / f"{rel_name}.jsonl"
        count = 0
        if rel_file.exists():
            for line in rel_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                from_ok = row.get("_from_pk") in present_pks.get(row.get("_from_table"), set())
                to_ok = row.get("_to_pk") in present_pks.get(row.get("_to_table"), set())
                if from_ok and to_ok:
                    count += 1
        rel_tables[rel_name] = {"rows": count}

    return {"node_tables": node_tables, "rel_tables": rel_tables}


def _counts_match(expected_manifest: dict, actual_manifest: dict) -> tuple[bool, list[str]]:
    mismatches: list[str] = []
    for section in ("node_tables", "rel_tables"):
        expected = expected_manifest.get(section, {})
        actual = actual_manifest.get(section, {})
        for table, info in expected.items():
            expected_rows = info.get("rows")
            actual_rows = actual.get(table, {}).get("rows")
            if expected_rows != actual_rows:
                mismatches.append(f"{table}: expected={expected_rows} restored={actual_rows}")
    return (not mismatches, mismatches)


async def _run_recall_sample(db_path: Path) -> list[dict]:
    from campy.brain.hippocampus.graph.gateway import GraphGateway
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.hippocampus.graph.queries import REGISTRY

    db = KuzuClient(str(db_path), read_only=True)
    try:
        gateway = GraphGateway(db, REGISTRY)
        return await gateway.run("backup.recall_sample")
    finally:
        db.close()


def verify_snapshot(snapshot_dir: Path) -> dict:
    """Verify `snapshot_dir` without ever touching the live database.

    Deliberately takes no live-db argument at all — there is nothing in
    this function's body that can reach `campy.paths.get_database_path()`
    or any path a caller does not explicitly hand it, which is what makes
    "verify never touches the live database" true by construction rather
    than by discipline.

    Steps (B319 Task 2):
      1. Checksum the payload against the manifest.
      2. Restore into a private `tempfile` throwaway database.
      3. Assert restored per-table counts match the manifest.
      4. Run one real recall query against the restored graph.
      5. Compare the manifest's embedding_model against the currently
         configured one — mismatch is a warning, not a failure.
    """
    snapshot_dir = Path(snapshot_dir)
    manifest = read_manifest(snapshot_dir)
    warnings: list[str] = []
    errors: list[str] = []

    actual_checksum = _payload_checksum(snapshot_dir)
    expected_checksum = manifest.get("payload_checksum")
    checksum_ok = expected_checksum is not None and actual_checksum == expected_checksum
    if not checksum_ok:
        errors.append(
            f"payload checksum mismatch: manifest says {expected_checksum!r}, "
            f"computed {actual_checksum!r} — the snapshot payload is corrupted or was edited"
        )

    counts_ok = False
    recall_ok = False
    if checksum_ok:
        tmp_dir = tempfile.mkdtemp(prefix="campy-backup-verify-")
        try:
            tmp_db_path = Path(tmp_dir) / "verify.db"
            # A private, throwaway path under tempfile's own directory —
            # never `campy.paths.get_database_path()` or any caller-supplied
            # path. `import_graph()` opens/creates/closes its own
            # KuzuClient on this path.
            import_graph(tmp_db_path, snapshot_dir)

            actual_manifest = _reexport_counts(tmp_db_path)
            expected_manifest = _expected_counts_from_dump(snapshot_dir, manifest)
            counts_ok, mismatches = _counts_match(expected_manifest, actual_manifest)
            if not counts_ok:
                errors.append("restored counts do not match the snapshot payload: " + "; ".join(mismatches))

            recall_rows = asyncio.run(_run_recall_sample(tmp_db_path))
            recall_ok = len(recall_rows) > 0
            if not recall_ok:
                errors.append(
                    "recall smoke query (Concept/Decision/Lesson) returned no rows "
                    "against the restored graph"
                )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        errors.append("skipped restore verification because the payload checksum already failed")

    configured_model = _configured_embedding_model()
    manifest_model = manifest.get("embedding_model")
    embedding_model_match = manifest_model is None or manifest_model == configured_model
    if manifest_model and not embedding_model_match:
        warnings.append(
            f"snapshot embedding_model={manifest_model!r} does not match the currently "
            f"configured model {configured_model!r} — restoring is fine, but vectors will "
            f"need rebuilding to match the running model"
        )

    ok = checksum_ok and counts_ok and recall_ok
    return {
        "ok": ok,
        "checksum_ok": checksum_ok,
        "counts_ok": counts_ok,
        "recall_ok": recall_ok,
        "embedding_model_match": embedding_model_match,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Task 3 — campy restore (the dangerous one)
# ---------------------------------------------------------------------------


def _wipe_db_file(db_path: Path) -> None:
    db_path.unlink(missing_ok=True)
    Path(str(db_path) + ".wal").unlink(missing_ok=True)


def restore_snapshot(
    snapshot_dir: Path,
    *,
    target_db_path: Path,
    force: bool = False,
    pre_restore_out_root: Optional[Path] = None,
    on_pre_restore_snapshot=None,
) -> dict:
    """Restore `snapshot_dir` into `target_db_path`.

    Refuses (raises `BackupError`, changing nothing) when:
      - the target database already exists and is non-empty, and `force`
        is not set
      - the snapshot's manifest `schema_version` is newer than this
        running code's `schema.SCHEMA_VERSION` (a forward restore would
        silently drop columns this code does not know to write back)

    With `force` set and a non-empty target, takes an automatic
    pre-restore snapshot of the *current* contents of `target_db_path`
    before touching anything else, and returns its directory in the
    result dict's `pre_restore_snapshot` key. `on_pre_restore_snapshot`,
    if given, is called with that directory's path immediately after the
    safety snapshot is written and *before* the target database is wiped —
    the CLI wires this to `console.print()` so the path is printed before
    anything destructive happens, not merely present in the final result.
    """
    snapshot_dir = Path(snapshot_dir)
    target_db_path = Path(target_db_path)
    manifest = read_manifest(snapshot_dir)

    if pre_restore_out_root is None:
        # Layout is always <root>/<workspace_id>/<timestamp>/ (see
        # create_snapshot()) — default the safety snapshot to the same
        # backup root the snapshot being restored came from, so a custom
        # `--out` root (tests; a non-default backup location) is honored
        # without every caller having to thread it through explicitly.
        pre_restore_out_root = snapshot_dir.parent.parent

    snapshot_schema_version = int(manifest.get("schema_version") or 0)
    if snapshot_schema_version > SCHEMA_VERSION:
        raise BackupError(
            f"Refusing to restore: snapshot schema_version={snapshot_schema_version} is "
            f"newer than this running code's SCHEMA_VERSION={SCHEMA_VERSION}. A forward "
            f"restore could silently drop columns this code does not know to write back — "
            f"upgrade Campy before restoring this snapshot."
        )

    non_empty = target_db_path.exists() and target_db_path.stat().st_size > 0
    if non_empty and not force:
        raise BackupError(
            f"{target_db_path} already exists and is not empty. Pass --force to overwrite "
            f"it (an automatic pre-restore snapshot is taken first)."
        )

    pre_restore_snapshot = None
    if non_empty and force:
        pre_restore_snapshot = create_snapshot(
            target_db_path,
            workspace_id=manifest.get("workspace_id", "local"),
            out_root=pre_restore_out_root,
            include_projected=True,
            skip_if_unchanged=False,
            extra_manifest_fields={
                "pre_restore_for": str(snapshot_dir),
            },
        )
        if on_pre_restore_snapshot is not None:
            on_pre_restore_snapshot(pre_restore_snapshot["_snapshot_dir"])
        _wipe_db_file(target_db_path)

    import_result = import_graph(target_db_path, snapshot_dir)

    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.hippocampus.schema import init_schema

    embedding_model = manifest.get("embedding_model") or _configured_embedding_model()
    db = KuzuClient(str(target_db_path))
    try:
        seed_path = _resolve_seed_examples_path()
        init_schema(db, seed_path, embedding_model)
    finally:
        db.close()

    return {
        "ok": True,
        "manifest": manifest,
        "node_rows_loaded": import_result["node_rows_loaded"],
        "rel_rows_loaded": import_result["rel_rows_loaded"],
        "pre_restore_snapshot": pre_restore_snapshot["_snapshot_dir"] if pre_restore_snapshot else None,
    }


def _resolve_seed_examples_path() -> str:
    """Reuse `campy.cli.install`'s existing dev-checkout/package-data
    resolution rather than re-deriving it here — see that module's
    `resolve_seed_examples_path()` docstring for the search order."""
    from campy.cli.install import resolve_seed_examples_path

    return resolve_seed_examples_path()


# ---------------------------------------------------------------------------
# Task 4 — campy backup prune (minimal retention)
# ---------------------------------------------------------------------------


def _snapshot_timestamp(snapshot_dir: Path) -> Optional[datetime]:
    match = _TIMESTAMP_RE.match(snapshot_dir.name)
    if not match:
        return None
    return datetime.strptime(match.group(1), _TIMESTAMP_FMT).replace(tzinfo=timezone.utc)


def prune_workspace(
    workspace_root: Path,
    *,
    keep_daily: int = 7,
    keep_weekly: int = 4,
    dry_run: bool = False,
) -> dict:
    """Apply daily/weekly retention to one workspace's snapshots.

    Never deletes the most recent snapshot, regardless of `keep_daily`/
    `keep_weekly` — there must always be at least one restorable point.
    Snapshots deduplicated via hard links (see `_hardlink_dedupe`) are
    ordinary, independently-restorable directories, so pruning one has no
    effect on any other snapshot's ability to restore: the OS keeps the
    shared file content alive as long as at least one directory entry
    still links to it.
    """
    snapshots = list(reversed(_list_snapshot_dirs(workspace_root)))  # newest first
    if not snapshots:
        return {"kept": [], "deleted": []}

    keep: set[str] = {snapshots[0].name}

    seen_days: set[str] = set()
    for snap in snapshots:
        ts = _snapshot_timestamp(snap)
        day = ts.strftime("%Y-%m-%d") if ts else snap.name
        if day not in seen_days and len(seen_days) < keep_daily:
            seen_days.add(day)
            keep.add(snap.name)

    seen_weeks: set[tuple[int, int]] = set()
    for snap in snapshots:
        ts = _snapshot_timestamp(snap)
        if ts is None:
            continue
        iso = ts.isocalendar()
        week_key = (iso[0], iso[1])
        if week_key not in seen_weeks and len(seen_weeks) < keep_weekly:
            seen_weeks.add(week_key)
            keep.add(snap.name)

    to_delete = [snap for snap in snapshots if snap.name not in keep]
    if not dry_run:
        for snap in to_delete:
            shutil.rmtree(snap)

    return {
        "kept": sorted(keep),
        "deleted": sorted(snap.name for snap in to_delete),
    }


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command("create")
def create_cmd(
    workspace: Optional[str] = typer.Option(None, "--workspace", help="Workspace id to back up"),
    all_workspaces: bool = typer.Option(False, "--all", help="Back up every workspace"),
    out: Optional[str] = typer.Option(None, "--out", help="Backup root directory (default: ~/.campy/backups)"),
    db_path: Optional[str] = typer.Option(None, "--db-path", help="Override the source database path"),
    include_projected: bool = typer.Option(
        False, "--include-projected", help="Include authority='projected' rows (default: earned only)"
    ),
) -> None:
    """Create a snapshot of one or every workspace's earned memory."""
    if workspace and all_workspaces:
        console.print("[red]Error:[/red] specify only one of --workspace or --all")
        raise typer.Exit(code=1)

    workspace_ids = [workspace] if workspace else _list_workspace_ids()
    out_root = Path(out).expanduser() if out else None
    override_db = Path(db_path).expanduser() if db_path else None

    for ws in workspace_ids:
        source_db = _db_path_for_workspace(ws, override=override_db)
        try:
            manifest = create_snapshot(
                source_db,
                workspace_id=ws,
                out_root=out_root,
                include_projected=include_projected,
            )
        except BackupError as exc:
            console.print(f"[red]Error:[/red] workspace {ws!r}: {exc}")
            raise typer.Exit(code=1)

        note = " (deduplicated)" if "deduplicated_from" in manifest else ""
        console.print(f"[green]OK[/green] {ws}: {manifest['_snapshot_dir']}{note}")


@app.command("list")
def list_cmd(
    workspace: Optional[str] = typer.Option(None, "--workspace", help="Filter by workspace id"),
    out: Optional[str] = typer.Option(None, "--out", help="Backup root directory (default: ~/.campy/backups)"),
) -> None:
    """List available snapshots."""
    root = Path(out).expanduser() if out else get_backup_root()
    if workspace:
        workspace_ids = [workspace]
    elif root.exists():
        workspace_ids = sorted(p.name for p in root.iterdir() if p.is_dir())
    else:
        workspace_ids = []

    table = Table(title="Campy Backups")
    table.add_column("Workspace", style="cyan")
    table.add_column("Snapshot", style="magenta")
    table.add_column("Exported At")
    table.add_column("Nodes")
    table.add_column("Rels")

    found = False
    for ws in workspace_ids:
        for snap_dir in _list_snapshot_dirs(_workspace_root(ws, backup_root=root)):
            manifest = read_manifest(snap_dir)
            node_rows = sum(v.get("rows", 0) for v in manifest.get("node_tables", {}).values())
            rel_rows = sum(v.get("rows", 0) for v in manifest.get("rel_tables", {}).values())
            table.add_row(
                ws,
                snap_dir.name,
                manifest.get("exported_at", ""),
                str(node_rows),
                str(rel_rows),
            )
            found = True

    if not found:
        console.print("[yellow]No snapshots found.[/yellow]")
        return
    console.print(table)


@app.command("verify")
def verify_cmd(
    snapshot: str = typer.Argument(..., help="Snapshot directory or id (e.g. local/20260816T120000Z)"),
    out: Optional[str] = typer.Option(None, "--out", help="Backup root directory (default: ~/.campy/backups)"),
) -> None:
    """Verify a snapshot restores cleanly into a throwaway database.

    Never touches the live database — restores into a private temp
    directory only. See `verify_snapshot()`.
    """
    root = Path(out).expanduser() if out else None
    try:
        snapshot_dir = resolve_snapshot_path(snapshot, backup_root=root)
    except BackupError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    result = verify_snapshot(snapshot_dir)
    if result["ok"]:
        console.print(f"[green]OK[/green] {snapshot_dir} verified.")
    else:
        console.print(f"[red]FAILED[/red] {snapshot_dir}:")
        for err in result["errors"]:
            console.print(f"  [red]- {err}[/red]")
    for warn in result["warnings"]:
        console.print(f"  [yellow]warning: {warn}[/yellow]")

    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("prune")
def prune_cmd(
    keep_daily: int = typer.Option(7, "--keep-daily", help="Number of most recent daily snapshots to keep"),
    keep_weekly: int = typer.Option(4, "--keep-weekly", help="Number of additional weekly snapshots to keep"),
    workspace: Optional[str] = typer.Option(None, "--workspace", help="Prune only this workspace"),
    out: Optional[str] = typer.Option(None, "--out", help="Backup root directory (default: ~/.campy/backups)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be deleted without deleting"),
) -> None:
    """Apply daily/weekly retention, never deleting the most recent snapshot."""
    root = Path(out).expanduser() if out else get_backup_root()
    workspace_ids = [workspace] if workspace else _list_workspace_ids()

    for ws in workspace_ids:
        result = prune_workspace(
            _workspace_root(ws, backup_root=root),
            keep_daily=keep_daily,
            keep_weekly=keep_weekly,
            dry_run=dry_run,
        )
        verb = "Would delete" if dry_run else "Deleted"
        console.print(f"{ws}: kept {len(result['kept'])}, {verb.lower()} {len(result['deleted'])}")
        for name in result["deleted"]:
            console.print(f"  [dim]{verb}: {name}[/dim]")


def restore_cmd(
    snapshot: str = typer.Argument(..., help="Snapshot directory or id to restore"),
    workspace: Optional[str] = typer.Option(None, "--workspace", help="Workspace id (defaults to the snapshot's own)"),
    force: bool = typer.Option(False, "--force", help="Overwrite a non-empty target database"),
    yes: bool = typer.Option(False, "--yes", help="Skip the interactive confirmation prompt"),
    db_path: Optional[str] = typer.Option(None, "--db-path", help="Target database path (default: the active Campy database)"),
    out: Optional[str] = typer.Option(None, "--out", help="Backup root directory (default: ~/.campy/backups)"),
) -> None:
    """Restore a snapshot. Refuses a non-empty target without --force;
    --force takes an automatic pre-restore snapshot first and prints its
    path before doing anything else."""
    root = Path(out).expanduser() if out else None
    try:
        snapshot_dir = resolve_snapshot_path(snapshot, backup_root=root)
    except BackupError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    manifest = read_manifest(snapshot_dir)
    ws = workspace or manifest.get("workspace_id", "local")
    target_db_path = Path(db_path).expanduser() if db_path else _db_path_for_workspace(ws)

    console.print(f"Restoring {snapshot_dir} -> {target_db_path} (workspace={ws})")
    node_rows = sum(v.get("rows", 0) for v in manifest.get("node_tables", {}).values())
    rel_rows = sum(v.get("rows", 0) for v in manifest.get("rel_tables", {}).values())
    console.print(f"  Snapshot contains {node_rows} node rows, {rel_rows} rel rows.")

    non_empty = target_db_path.exists() and target_db_path.stat().st_size > 0
    if non_empty and not force:
        console.print(
            f"[red]Error:[/red] {target_db_path} already exists and is not empty. "
            f"Pass --force to overwrite (a pre-restore snapshot is taken first)."
        )
        raise typer.Exit(code=1)

    if non_empty and not yes:
        confirmed = typer.confirm(f"This will overwrite {target_db_path}. Continue?")
        if not confirmed:
            raise typer.Abort()

    def _announce_pre_restore(path: str) -> None:
        console.print(f"[yellow]Pre-restore snapshot:[/yellow] {path}")

    try:
        result = restore_snapshot(
            snapshot_dir,
            target_db_path=target_db_path,
            force=force,
            on_pre_restore_snapshot=_announce_pre_restore,
        )
    except BackupError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]OK[/green] Restored {result['node_rows_loaded']} node rows, "
        f"{result['rel_rows_loaded']} rel rows into {target_db_path}"
    )
