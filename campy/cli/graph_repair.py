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

from campy.brain.hippocampus.graph.gateway import get_gateway

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
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


def _open_repair_client(db_path: Path, apply: bool) -> OxigraphClient:
    """Open the graph for a repair sweep, turning a raw lock exception
    into an actionable message instead of a traceback.
    """
    try:
        return OxigraphClient(str(db_path), read_only=not apply)
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
    new_valence: float
    action: str  # always "flip" — ambiguous verdicts are skipped, never nulled
    goal: str = ""


async def find_candidates(db) -> list[PolarityCandidate]:
    """Find system-labeled outcome Lessons whose polarity disagrees with, or is
    ambiguous under, the current infer_outcome_valence. Lessons with a
    `[valence_trigger:` (post-B301, already auditable) or `[valence_relabel:`
    (already repaired by this sweep) marker are never candidates, nor are
    already-archived Lessons.
    """
    gw = get_gateway(db)
    rows = await gw.run("cli.graph_repair_find_outcome_candidates")

    candidates: list[PolarityCandidate] = []
    for row in rows:
        lesson_id = row["lesson_id"] if isinstance(row, dict) else row[0]
        text_raw = row["text_raw"] if isinstance(row, dict) else row[1]
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
    gw = get_gateway(db)
    qname = "cli.graph_repair_linked_plan_failure" if old_polarity == "failure" else "cli.graph_repair_linked_plan_success"
    await gw.run(qname, lid=lesson_id, valence=new_valence)


async def apply_candidates(db, candidates: list[PolarityCandidate]) -> None:
    gw = get_gateway(db)
    for candidate in candidates:
        if candidate.action == "flip":
            await gw.run(
                "cli.graph_repair_flip_lesson",
                lid=candidate.lesson_id, text=candidate.new_text, valence=candidate.new_valence,
            )
        else:  # archive
            await gw.run(
                "cli.graph_repair_archive_lesson",
                lid=candidate.lesson_id,
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

    Flip-only: an ambiguous re-judgment is skipped, never nulled. Until the
    report_outcome valence_source fix, explicit MCP calls were also stamped
    "system", so a 'system' source cannot prove the valence was auto-inferred
    from text. For explicitly-valenced plans the judgment was the number, not
    the goal/step text — re-judging that text is expected to return None, and
    nulling on that would erase legitimate valences (recall_plans skips
    valence-None plans entirely).
    """
    gw = get_gateway(db)
    rows = await gw.run("cli.graph_repair_find_plan_candidates")

    candidates: list[PlanValenceCandidate] = []
    for row in rows:
        plan_id = row["plan_id"] if isinstance(row, dict) else row[0]
        goal = (row["goal"] if isinstance(row, dict) else row[1]) or ""
        old_valence = row["valence"] if isinstance(row, dict) else row[2]

        step_rows = await gw.run(
            "cli.graph_repair_plan_steps",
            pid=plan_id,
        )
        step_texts = [
            (r["actual_outcome"] if isinstance(r, dict) else r[0])
            for r in step_rows
            if (r.get("actual_outcome") if isinstance(r, dict) else r[0])
        ]
        body = "\n".join([goal, *step_texts]) if step_texts else goal

        new_verdict = infer_outcome_valence(body)

        if new_verdict is None:
            continue  # ambiguous — leave untouched (flip-only, see docstring)

        old_sign = 1 if (old_valence or 0) > 0 else (-1 if (old_valence or 0) < 0 else 0)
        new_sign = 1 if new_verdict > 0 else -1
        if old_sign == new_sign:
            continue  # agrees with stored valence — leave untouched

        candidates.append(
            PlanValenceCandidate(plan_id, old_valence, new_verdict, "flip", goal)
        )

    return candidates


async def apply_plan_valence_candidates(db, candidates: list[PlanValenceCandidate]) -> None:
    gw = get_gateway(db)
    for candidate in candidates:
        await gw.run(
            "cli.graph_repair_set_plan_valence",
            pid=candidate.plan_id,
            valence=candidate.new_valence,
            source=_PLAN_VALENCE_AUDIT_SOURCE,
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
        new_label = f"{candidate.new_valence:+.1f}"
        table.add_row(candidate.plan_id, f"{old_label} → {new_label}", candidate.action)
    console.print(table)

    verb = "applied" if apply else "found"
    console.print(f"{len(candidates)} candidate(s) {verb}.")


# ---------------------------------------------------------------------------
# B465: supersession edges written backwards before B460
# ---------------------------------------------------------------------------
#
# Before B460, consolidation's Step 3b LLM wrote "A CHOSEN_OVER B" edges with
# the RETIRED value as A ("PostgreSQL 14 CHOSEN_OVER PostgreSQL 16" from "We
# migrated from PostgreSQL 14 to PostgreSQL 16"). Edges carry no link to the
# message they came from, so the repair re-reads the user's own statements:
# B460's Step 1b reads a supersession's direction off the grammar (passive,
# "from X to Y", active) with no LLM. An edge whose direction a user message
# contradicts is replaced by "new REPLACES old" between the same two
# Concepts; every edge no message speaks to is left alone and reported.

_SUPERSESSION_RELS = ("CHOSEN_OVER", "REPLACES")
_REPAIR_INFERRED_BY = "system:b465-repair"
_REPAIR_CONFIDENCE = 0.85  # Step 1b's confidence for a verb-pattern relation


@dataclass
class SupersessionStatement:
    """One "new REPLACES old" that Step 1b reads in a user message."""
    new: str
    old: str
    message_id: str
    text: str


@dataclass
class SupersessionEdgeVerdict:
    rel: str
    head: str
    head_id: str
    tail: str
    tail_id: str
    # "inverted": a user message says the tail replaced the head -> repaired
    # "right": a user message says the head replaced the tail
    # "conflicting": user messages say both -> left alone
    # "unverifiable": no user message states a supersession of the pair
    verdict: str
    evidence: list[SupersessionStatement]

    @property
    def label(self) -> str:
        return f"{self.head} -{self.rel}-> {self.tail}"


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.lower()))


def _contains_words(text: str, part: str) -> bool:
    return bool(part) and re.search(rf"(?<![^\W_]){re.escape(part)}(?![^\W_])", text) is not None


def _names(span: str, concept: str) -> bool:
    """A Step 1b span names a Concept when, case-insensitively, they are equal
    or one contains the other as whole words: Step 1b keeps versions NER
    drops ("PostgreSQL 16" vs the entity "postgresql"), and NER keeps words
    Step 1b's span stops at ("OpenTelemetry OTel" from "OpenTelemetry (OTel)").
    A Concept that names BOTH sides of a statement ("PostgreSQL" for
    "PostgreSQL 16 REPLACES PostgreSQL 14") is ruled out by the caller."""
    s, c = span.lower().strip(), concept.lower().strip()
    return bool(s and c) and (s == c or _contains_words(s, c) or _contains_words(c, s))


def _side(concept: str, st: SupersessionStatement) -> str | None:
    """'new' / 'old' when the Concept names exactly one side of the statement."""
    new, old = _names(st.new, concept), _names(st.old, concept)
    if new and not old:
        return "new"
    if old and not new:
        return "old"
    return None


def _load_nlp():
    from campy.brain.temporal_lobe.loop.step1_ner import get_nlp

    model = "en_core_web_md"
    try:
        from campy.brain.brainstem.config import load_config

        model = load_config().get("nlp", {}).get("spacy_model", model)
    except Exception:  # noqa: BLE001 -- no config: the daemon's default model
        console.print(f"[dim]No Campy config found; using spaCy model {model}.[/dim]")
    return get_nlp(model)


def _row(row, key: str, idx: int):
    return row.get(key) if isinstance(row, dict) else row[idx]


async def find_supersession_verdicts(db, nlp=None) -> list[SupersessionEdgeVerdict]:
    """Classify every Concept-Concept CHOSEN_OVER / REPLACES edge against the
    supersessions Step 1b reads in the stored user Messages (read-only)."""
    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations

    gw = get_gateway(db)
    edge_rows = await gw.run("cli.graph_repair_find_supersession_edges")
    edges = [
        (_row(r, "rel", 2), _row(r, "head", 1), str(_row(r, "head_id", 0)),
         _row(r, "tail", 4), str(_row(r, "tail_id", 3)))
        for r in edge_rows
    ]
    edges = sorted({e for e in edges if e[0] in _SUPERSESSION_RELS and e[1] and e[3]},
                   key=lambda e: (e[1].lower(), e[3].lower(), e[0]))
    if not edges:
        return []

    # Only parse messages that share a word with both ends of some edge: a
    # span naming a Concept (see _names) always does.
    pair_words = [(_words(h), _words(t)) for _, h, _, t, _ in edges]
    messages = []
    for r in await gw.run("cli.graph_repair_find_user_messages"):
        text = _row(r, "text_raw", 1) or ""
        mw = _words(text)
        if any(hw & mw and tw & mw for hw, tw in pair_words):
            messages.append((str(_row(r, "message_id", 0)), text))

    statements: list[SupersessionStatement] = []
    if messages:
        nlp = nlp or _load_nlp()
        for (mid, text), doc in zip(messages, nlp.pipe(t for _, t in messages)):
            for rel in extract_relations(doc, []):
                if rel["relation_type"] == "REPLACES":
                    statements.append(SupersessionStatement(rel["head"], rel["tail"], mid, text))

    verdicts = []
    for rel, head, head_id, tail, tail_id in edges:
        support, against = [], []
        for st in statements:
            sides = (_side(head, st), _side(tail, st))
            if sides == ("new", "old"):
                support.append(st)
            elif sides == ("old", "new"):
                against.append(st)
        if against and support:
            verdict, evidence = "conflicting", against + support
        elif against:
            verdict, evidence = "inverted", against
        elif support:
            verdict, evidence = "right", support
        else:
            verdict, evidence = "unverifiable", []
        verdicts.append(SupersessionEdgeVerdict(rel, head, head_id, tail, tail_id, verdict, evidence))
    return verdicts


async def apply_supersession_repairs(db, verdicts: list[SupersessionEdgeVerdict]) -> None:
    """For each inverted edge: remove it, then write "tail REPLACES head"
    between the same Concepts (a no-op when that edge already exists)."""
    from datetime import UTC, datetime

    gw = get_gateway(db)
    now = datetime.now(UTC).isoformat()
    for v in verdicts:
        if v.verdict != "inverted":
            continue
        await gw.run(f"orchestrator.remove_semantic_rel_{v.rel.lower()}", hid=v.head_id, tid=v.tail_id)
        await gw.run(
            "orchestrator.merge_semantic_rel_replaces",
            hid=v.tail_id, tid=v.head_id,
            confidence=_REPAIR_CONFIDENCE, inferred_by=_REPAIR_INFERRED_BY, now=now,
        )


async def repair_supersession_edges(db, apply: bool = False, nlp=None) -> list[SupersessionEdgeVerdict]:
    verdicts = await find_supersession_verdicts(db, nlp=nlp)
    if apply:
        await apply_supersession_repairs(db, verdicts)
    return verdicts


def _excerpt(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@graph_app.command("repair-supersession-edges")
def repair_supersession_edges_cmd(
    apply: bool = typer.Option(False, "--apply", help="Write changes (default: dry run)"),
    db_path: str = typer.Option(
        "", "--db-path", help="Path to the graph store (defaults to the active Campy database)"
    ),
    show_all: bool = typer.Option(
        False, "--all", help="Also list edges that are right or unverifiable (default: only inverted and conflicting)"
    ),
) -> None:
    """B465: fix CHOSEN_OVER/REPLACES edges that name the retired value as the
    winner, judged against the user's own supersession statements."""
    resolved_db_path = Path(db_path).expanduser() if db_path else get_database_path()
    if not resolved_db_path.exists():
        console.print(f"[red]Error:[/red] Campy database not found at {resolved_db_path}.")
        raise typer.Exit(code=1)

    # The store is opened writable even for a dry run (pyoxigraph's lock is
    # exclusive either way): stop the daemon first, or run on a copy.
    client = _open_repair_client(resolved_db_path, apply)
    try:
        verdicts = asyncio.run(repair_supersession_edges(client, apply=apply))
    finally:
        client.close()  # release the store's lock now, not whenever it is collected

    shown = [v for v in verdicts if show_all or v.verdict in ("inverted", "conflicting")]
    table = Table(title="Supersession edge repair — " + ("applied" if apply else "dry run"), show_lines=True)
    table.add_column("edge")
    table.add_column("verdict")
    table.add_column("action")
    table.add_column("user message")
    for v in shown:
        if v.verdict == "inverted":
            action = f"{'removed' if apply else 'remove'}; {v.tail} -REPLACES-> {v.head}"
        else:
            action = "leave"
        evidence = "\n".join(f"[{st.message_id[:8]}] {_excerpt(st.text)}" for st in v.evidence[:3])
        table.add_row(escape(v.label), v.verdict, escape(action), escape(evidence))
    console.print(table)

    counts = {k: sum(v.verdict == k for v in verdicts) for k in ("inverted", "right", "conflicting", "unverifiable")}
    console.print(
        f"{len(verdicts)} CHOSEN_OVER/REPLACES edge(s): "
        + ", ".join(f"{n} {k}" for k, n in counts.items())
        + "."
    )
    if counts["inverted"]:
        console.print(f"{counts['inverted']} inverted edge(s) {'repaired' if apply else 'would be repaired (re-run with --apply)'}.")


# --- B467: archive what benchmark sessions wrote into a personal store -------
#
# Non-isolated campy-benchmarks runs wrote their fixture conversations into the
# user's own store, and consolidation turned them into Concepts and edges that
# `ask` then read as the user's decisions. Messages, and what a Message
# ESTABLISHED (Decisions, Constraints) or CONTAINS_LESSON, carry provenance and
# are archived exactly. Concepts do not: the graph has no Concept -> Message
# link, so a Concept is archived when a purged Message names it (whole words,
# case-insensitive) and no remaining Message does. Nodes are archived, not
# deleted (retrieval skips archived nodes; their text stays in the graph, so
# an archive can be undone and re-embedded), and their vectors.db rows --
# embedding and full-text -- are removed, so they neither crowd live hits out
# of a search's top k nor count in the conversation stage's word statistics.


@dataclass
class SessionPurgePlan:
    prefixes: tuple[str, ...]
    sessions: dict[str, list[str]]  # prefix (or exact session id) -> session ids
    messages: dict[str, str]  # message_id -> text, all to be archived
    session_less: list[str]  # of those, the ones with no Session (exact copies)
    products: dict[str, list[str]]  # "Decision" / "Constraint" / "Lesson" -> ids
    concepts: dict[str, str]  # concept_id -> name, to be archived
    kept_concepts: int  # named by a purged Message, but also by a remaining one
    edges: dict[str, int]  # "both" / "one": Concept-Concept edges by archived ends
    uris: list[str]  # every node to archive: its vectors.db rows are dropped too


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _mentioned(names: dict[str, str], texts: list[str]) -> set[str]:
    """Ids of the `names` that some text contains as whole words
    (case-insensitive). A word index narrows the texts each name is tried on."""
    index: dict[str, set[int]] = {}
    lowered = [t.lower() for t in texts]
    for i, t in enumerate(lowered):
        for w in _words(t):
            index.setdefault(w, set()).add(i)
    found = set()
    for cid, name in names.items():
        words = _words(name)
        if not words:
            continue
        candidates = set.intersection(*(index.get(w, set()) for w in words))
        low = name.lower().strip()
        if any(_contains_words(lowered[i], low) for i in candidates):
            found.add(cid)
    return found


async def plan_session_purge(db, prefixes=(), sessions_exact=()) -> SessionPurgePlan:
    prefixes, exact = tuple(prefixes), tuple(sessions_exact)
    gw = get_gateway(db)

    def matches(session_id) -> str | None:
        if not session_id:
            return None
        sid = str(session_id)
        if sid in exact:
            return sid
        return next((p for p in prefixes if sid.startswith(p)), None)

    sessions: dict[str, list[str]] = {p: [] for p in prefixes + exact}
    for r in await gw.run("cli.purge_find_sessions"):
        sid = _row(r, "session_id", 0)
        if (p := matches(sid)) is not None:
            sessions[p].append(str(sid))

    purged: dict[str, str] = {}
    uri_of: dict[str, str] = {}
    remaining: list[tuple[str, str, bool]] = []  # (id, text, has_session)
    for r in await gw.run("cli.purge_find_messages"):
        mid, text = str(_row(r, "message_id", 0)), _row(r, "text_raw", 1) or ""
        archived, sid = bool(_row(r, "archived", 2)), _row(r, "session_id", 3)
        if archived:
            continue
        uri_of[mid] = str(_row(r, "uri", 4))
        if matches(sid) is not None:
            purged[mid] = text
        else:
            remaining.append((mid, text, sid is not None))

    # A Message with no Session that repeats a purged Message word for word is
    # a copy of it (written by the same runs, outside any session).
    purged_texts = {_norm(t) for t in purged.values() if t.strip()}
    session_less = [mid for mid, text, has_session in remaining
                    if not has_session and text.strip() and _norm(text) in purged_texts]
    copies = set(session_less)
    for mid, text, _ in remaining:
        if mid in copies:
            purged[mid] = text
    remaining_texts = [text for mid, text, _ in remaining if mid not in copies]

    # A Decision/Constraint/Lesson is archived only when every Message that
    # produced it is purged.
    producers: dict[tuple[str, str], set[str]] = {}
    already: set[tuple[str, str]] = set()
    product_uri: dict[tuple[str, str], str] = {}
    for r in await gw.run("cli.purge_find_message_products"):
        key = (_row(r, "kind", 1), str(_row(r, "node_id", 2)))
        producers.setdefault(key, set()).add(str(_row(r, "message_id", 0)))
        product_uri[key] = str(_row(r, "uri", 4))
        if bool(_row(r, "archived", 3)):
            already.add(key)
    products: dict[str, list[str]] = {"Decision": [], "Constraint": [], "Lesson": []}
    for (kind, nid), mids in sorted(producers.items()):
        if (kind, nid) not in already and mids <= purged.keys():
            products[kind].append(nid)

    live: dict[str, str] = {}
    concept_uri: dict[str, str] = {}
    for r in await gw.run("cli.purge_find_concepts"):
        if not bool(_row(r, "archived", 2)):
            cid = str(_row(r, "concept_id", 0))
            live[cid] = _row(r, "text_raw", 1) or ""
            concept_uri[cid] = str(_row(r, "uri", 3))
    named_by_purged = _mentioned(live, list(purged.values()))
    candidates = {cid: live[cid] for cid in named_by_purged}
    still_named = _mentioned(candidates, remaining_texts)
    concepts = {cid: name for cid, name in candidates.items() if cid not in still_named}

    edges = {"both": 0, "one": 0}
    for r in await gw.run("cli.purge_find_concept_edges"):
        ends = (str(_row(r, "head_id", 0)) in concepts) + (str(_row(r, "tail_id", 2)) in concepts)
        if ends == 2:
            edges["both"] += 1
        elif ends == 1:
            edges["one"] += 1

    uris = ([uri_of[m] for m in purged]
            + [product_uri[(k, n)] for k, ids in products.items() for n in ids]
            + [concept_uri[c] for c in concepts])
    return SessionPurgePlan(prefixes + exact, sessions, purged, session_less, products,
                            concepts, len(still_named), edges, uris)


async def apply_session_purge(db, plan: SessionPurgePlan) -> None:
    gw = get_gateway(db)
    for mid in plan.messages:
        await gw.run("cli.purge_archive_message", node_id=mid)
    for nid in plan.products["Decision"]:
        await gw.run("cli.purge_archive_decision", node_id=nid)
    for nid in plan.products["Constraint"]:
        await gw.run("cli.purge_archive_constraint", node_id=nid)
    for nid in plan.products["Lesson"]:
        await gw.run("sweep.archive_lesson", lid=nid)
    for cid in plan.concepts:
        await gw.run("quests.archive_concept", cid=cid)
    vs = getattr(db, "vector_store", None)
    if vs is not None:
        for uri in plan.uris:
            vs.delete_vector(uri)
            vs.delete_text(uri)


async def purge_sessions(db, prefixes=(), apply: bool = False, sessions=()) -> SessionPurgePlan:
    plan = await plan_session_purge(db, prefixes, sessions)
    if apply:
        await apply_session_purge(db, plan)
    return plan


_PREFIX_OPTION = typer.Option(None, "--prefix", help="Session-id prefix to archive (repeatable; no default)")
_SESSION_OPTION = typer.Option(None, "--session", help="Exact session id to archive (repeatable)")


@graph_app.command("purge-sessions")
def purge_sessions_cmd(
    prefixes: list[str] = _PREFIX_OPTION,
    sessions: list[str] = _SESSION_OPTION,
    apply: bool = typer.Option(False, "--apply", help="Write changes (default: dry run)"),
    db_path: str = typer.Option(
        "", "--db-path", help="Path to the graph store (defaults to the active Campy database)"
    ),
    sample: int = typer.Option(20, "--sample", help="Concept names to list (0: none)"),
) -> None:
    """B467: archive the Messages that sessions with these id prefixes (or
    exact ids) wrote -- benchmark runs, say -- what they established, and the
    Concepts that only they mention."""
    prefixes, sessions = list(prefixes or []), list(sessions or [])
    if not prefixes and not sessions:
        console.print("[red]Error:[/red] give at least one --prefix or --session.")
        raise typer.Exit(code=1)
    if any(not p.strip() for p in prefixes + sessions):
        console.print("[red]Error:[/red] an empty --prefix would match every session.")
        raise typer.Exit(code=1)
    resolved_db_path = Path(db_path).expanduser() if db_path else get_database_path()
    if not resolved_db_path.exists():
        console.print(f"[red]Error:[/red] Campy database not found at {resolved_db_path}.")
        raise typer.Exit(code=1)

    # Opened writable even for a dry run (pyoxigraph's lock is exclusive
    # either way): stop the daemon first, or run on a copy.
    client = _open_repair_client(resolved_db_path, apply)
    try:
        plan = asyncio.run(purge_sessions(client, prefixes, apply=apply, sessions=sessions))
    finally:
        client.close()  # release the store's lock now, not whenever it is collected

    table = Table(title="Session purge — " + ("applied" if apply else "dry run"))
    table.add_column("prefix / session")
    table.add_column("sessions", justify="right")
    for p in plan.prefixes:
        table.add_row(escape(p), str(len(plan.sessions[p])))
    console.print(table)
    verb = "archived" if apply else "to archive"
    console.print(
        f"Messages {verb}: {len(plan.messages)} "
        f"({len(plan.session_less)} with no session, word-for-word copies of purged ones)\n"
        f"Decisions / Constraints / Lessons {verb}: {len(plan.products['Decision'])} / "
        f"{len(plan.products['Constraint'])} / {len(plan.products['Lesson'])}\n"
        f"Concepts {verb}: {len(plan.concepts)} (named only by purged messages); "
        f"kept: {plan.kept_concepts} (also named by a remaining message)\n"
        f"Concept-Concept edges with both ends archived: {plan.edges['both']}, one end: {plan.edges['one']}\n"
        f"vectors.db rows (embedding + full-text) {'removed' if apply else 'to remove'} for "
        f"{len(plan.uris)} node(s)"
    )
    if sample and plan.concepts:
        names = sorted({n for n in plan.concepts.values()}, key=str.lower)
        console.print("Concepts " + verb + " (sample): " + escape(" · ".join(names[:sample])))
    if not apply and plan.messages:
        console.print("Dry run: nothing written. Re-run with --apply (daemon stopped, store backed up).")
