"""B302: relabel or retire wrong-polarity outcome Lessons.

One-shot maintenance sweep — not a Loop step, no daemon involvement. Finds
Lessons whose text was labeled ("Plan outcome (success|failure): ...") by the
pre-B301 outcome sense (no `[valence_trigger:` audit marker), re-runs the
current `infer_outcome_valence` on the outcome body, and either leaves the
Lesson untouched (verdict agrees), relabels it (verdict disagrees), or
archives it (verdict is ambiguous). Linked system-valence Plans are repaired
to match.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.temporal_lobe.loop.step4_pattern import infer_outcome_valence
from campy.paths import get_database_path

console = Console()
graph_app = typer.Typer(help="Graph maintenance commands")

_PREFIX_RE = re.compile(r"^Plan outcome \((success|failure)\):\s*(.*)", re.DOTALL)


_LOCK_HELP_MESSAGE = (
    "Could not open the Campy database — it appears to be locked by another "
    "process (the daemon is probably running).\n"
    "Stop the daemon first: [bold]launchctl bootout gui/$UID/ai.hippocampy.brain[/bold]"
)


def _open_repair_client(db_path: Path, apply: bool) -> KuzuClient:
    """Open the graph for a repair sweep, turning a raw Kuzu lock exception
    into an actionable message instead of a traceback.
    """
    try:
        return KuzuClient(str(db_path), read_only=not apply)
    except Exception as exc:
        if "lock" in str(exc).lower():
            console.print(f"[red]Error:[/red] {_LOCK_HELP_MESSAGE}")
            raise typer.Exit(code=1) from exc
        raise


@dataclass
class PolarityCandidate:
    lesson_id: str
    old_polarity: str
    new_polarity: str | None  # None means "archive" (ambiguous verdict)
    action: str  # "flip" | "archive"
    new_text: str | None = None
    new_valence: float | None = None


_PLAN_VALENCE_AUDIT_SOURCE = "system:b303-audited"


@dataclass
class PlanValenceCandidate:
    plan_id: str
    old_valence: float | None
    new_valence: float | None  # None means "null out" (ambiguous verdict)
    action: str  # "flip" | "null"
    goal: str = ""


async def find_candidates(db) -> list[PolarityCandidate]:
    """Find system-labeled outcome Lessons whose polarity disagrees with, or is
    ambiguous under, the current infer_outcome_valence. Lessons with a
    `[valence_trigger:` (post-B301, already auditable) or `[valence_relabel:`
    (already repaired by this sweep) marker are never candidates, nor are
    already-archived Lessons.
    """
    rows = await db.execute_read(
        "MATCH (l:Lesson) "
        "WHERE l.text_raw STARTS WITH 'Plan outcome (' "
        "AND NOT l.text_raw CONTAINS '[valence_trigger:' "
        "AND NOT l.text_raw CONTAINS '[valence_relabel:' "
        "AND (l.archived IS NULL OR l.archived = false) "
        "RETURN l.lesson_id AS lesson_id, l.text_raw AS text_raw"
    )

    candidates: list[PolarityCandidate] = []
    for row in rows:
        lesson_id = row["lesson_id"]
        text_raw = row["text_raw"]
        match = _PREFIX_RE.match(text_raw)
        if not match:
            continue

        old_polarity, body = match.group(1), match.group(2)
        new_verdict = infer_outcome_valence(body)

        if new_verdict is None:
            candidates.append(
                PolarityCandidate(
                    lesson_id=lesson_id,
                    old_polarity=old_polarity,
                    new_polarity=None,
                    action="archive",
                )
            )
            continue

        new_polarity = "success" if new_verdict > 0 else "failure"
        if new_polarity == old_polarity:
            continue  # agrees with stored polarity — leave untouched

        new_text = (
            text_raw.replace(
                f"Plan outcome ({old_polarity}):", f"Plan outcome ({new_polarity}):", 1
            )
            + f"\n[valence_relabel: B302, was {old_polarity}]"
        )
        candidates.append(
            PolarityCandidate(
                lesson_id=lesson_id,
                old_polarity=old_polarity,
                new_polarity=new_polarity,
                action="flip",
                new_text=new_text,
                new_valence=new_verdict,
            )
        )

    return candidates


async def _repair_linked_plan(db, lesson_id: str, old_polarity: str, new_valence: float | None) -> None:
    """Correct a linked Plan's valence when it was system-sourced and shares
    the old (wrong) polarity's sign. Explicit valences are never touched.
    """
    sign_clause = "p.valence < 0" if old_polarity == "failure" else "p.valence > 0"
    await db.execute_write(
        "MATCH (p:Plan)-[:PRODUCED_PLAN_LESSON]->(l:Lesson {lesson_id: $lid}) "
        f"WHERE p.valence_source = 'system' AND {sign_clause} "
        "SET p.valence = $valence",
        {"lid": lesson_id, "valence": new_valence},
    )


async def apply_candidates(db, candidates: list[PolarityCandidate]) -> None:
    for candidate in candidates:
        if candidate.action == "flip":
            await db.execute_write(
                "MATCH (l:Lesson {lesson_id: $lid}) SET l.text_raw = $text, l.valence = $valence",
                {"lid": candidate.lesson_id, "text": candidate.new_text, "valence": candidate.new_valence},
            )
        else:  # archive
            await db.execute_write(
                "MATCH (l:Lesson {lesson_id: $lid}) SET l.archived = true",
                {"lid": candidate.lesson_id},
            )
        await _repair_linked_plan(db, candidate.lesson_id, candidate.old_polarity, candidate.new_valence)


async def repair_outcome_polarity(db, apply: bool = False) -> list[PolarityCandidate]:
    candidates = await find_candidates(db)
    if apply and candidates:
        await apply_candidates(db, candidates)
    return candidates


@graph_app.command("repair-outcome-polarity")
def repair_outcome_polarity_cmd(
    apply: bool = typer.Option(False, "--apply", help="Write changes (default: dry run)"),
    db_path: str = typer.Option(
        "", "--db-path", help="Path to the Kuzu database file (defaults to the active Campy database)"
    ),
) -> None:
    """B302: relabel or archive wrong-polarity outcome Lessons."""
    resolved_db_path = Path(db_path).expanduser() if db_path else get_database_path()
    if not resolved_db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(code=1)

    client = _open_repair_client(resolved_db_path, apply)
    candidates = asyncio.run(repair_outcome_polarity(client, apply=apply))

    title = "Outcome polarity repair — " + ("applied" if apply else "dry run")
    table = Table(title=title)
    table.add_column("lesson_id")
    table.add_column("old → new")
    table.add_column("action")
    for candidate in candidates:
        new_label = candidate.new_polarity or "archived"
        table.add_row(candidate.lesson_id, f"{candidate.old_polarity} → {new_label}", candidate.action)
    console.print(table)

    verb = "applied" if apply else "found"
    console.print(f"{len(candidates)} candidate(s) {verb}.")


async def find_plan_valence_candidates(db) -> list[PlanValenceCandidate]:
    """B303: find residual wrong-polarity Plan valences B302's Lesson-driven
    sweep can't reach — plans whose Lesson was archived, and plans whose
    valence came directly from the old buggy auto-report_outcome. Re-judges
    Plan.goal + PlanStep.actual_outcome text with the fixed
    infer_outcome_valence. Plans already audited by this sweep (valence_source
    carries the b303-audited marker) or with an explicit (non-system)
    valence_source are never candidates, nor are archived Plans.
    """
    rows = await db.execute_read(
        "MATCH (p:Plan) "
        "WHERE (p.valence_source IS NULL OR p.valence_source = 'system') "
        "AND p.valence IS NOT NULL "
        "AND (p.archived IS NULL OR p.archived = false) "
        "RETURN p.plan_id AS plan_id, p.goal AS goal, p.valence AS valence"
    )

    candidates: list[PlanValenceCandidate] = []
    for row in rows:
        plan_id = row["plan_id"]
        goal = row["goal"] or ""
        old_valence = row["valence"]

        step_rows = await db.execute_read(
            "MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) "
            "RETURN ps.actual_outcome AS actual_outcome ORDER BY ps.step_number ASC",
            {"pid": plan_id},
        )
        step_texts = [r["actual_outcome"] for r in step_rows if r.get("actual_outcome")]
        body = "\n".join([goal, *step_texts]) if step_texts else goal

        new_verdict = infer_outcome_valence(body)

        if new_verdict is None:
            if old_valence is None:
                continue  # already unset, nothing to repair
            candidates.append(
                PlanValenceCandidate(plan_id, old_valence, None, "null", goal)
            )
            continue

        old_sign = 1 if (old_valence or 0) > 0 else (-1 if (old_valence or 0) < 0 else 0)
        new_sign = 1 if new_verdict > 0 else -1
        if old_sign == new_sign:
            continue  # agrees with stored valence — leave untouched

        candidates.append(
            PlanValenceCandidate(plan_id, old_valence, new_verdict, "flip", goal)
        )

    return candidates


async def apply_plan_valence_candidates(db, candidates: list[PlanValenceCandidate]) -> None:
    for candidate in candidates:
        await db.execute_write(
            "MATCH (p:Plan {plan_id: $pid}) SET p.valence = $valence, p.valence_source = $source",
            {
                "pid": candidate.plan_id,
                "valence": candidate.new_valence,
                "source": _PLAN_VALENCE_AUDIT_SOURCE,
            },
        )


async def repair_plan_valence(db, apply: bool = False) -> list[PlanValenceCandidate]:
    candidates = await find_plan_valence_candidates(db)
    if apply and candidates:
        await apply_plan_valence_candidates(db, candidates)
    return candidates


@graph_app.command("repair-plan-valence")
def repair_plan_valence_cmd(
    apply: bool = typer.Option(False, "--apply", help="Write changes (default: dry run)"),
    db_path: str = typer.Option(
        "", "--db-path", help="Path to the Kuzu database file (defaults to the active Campy database)"
    ),
) -> None:
    """B303: repair residual wrong-polarity Plan valences (system-sourced, not
    reached by B302's Lesson-driven sweep)."""
    resolved_db_path = Path(db_path).expanduser() if db_path else get_database_path()
    if not resolved_db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(code=1)

    client = _open_repair_client(resolved_db_path, apply)
    candidates = asyncio.run(repair_plan_valence(client, apply=apply))

    title = "Plan valence repair — " + ("applied" if apply else "dry run")
    table = Table(title=title)
    table.add_column("plan_id")
    table.add_column("old → new")
    table.add_column("action")
    for candidate in candidates:
        old_label = "null" if candidate.old_valence is None else f"{candidate.old_valence:+.1f}"
        new_label = "null" if candidate.new_valence is None else f"{candidate.new_valence:+.1f}"
        table.add_row(candidate.plan_id, f"{old_label} → {new_label}", candidate.action)
    console.print(table)

    verb = "applied" if apply else "found"
    console.print(f"{len(candidates)} candidate(s) {verb}.")
