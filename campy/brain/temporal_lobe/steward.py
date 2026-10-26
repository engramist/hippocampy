"""
campy/brain/temporal_lobe/steward.py -- B535: a vocabulary steward above the NLP pipeline.

WordNet runs inside the NLP process (B534) and links kinds that are lexical hypernyms. It misses the
common-sense links ("dog" is a "pet": WordNet files the pet sense elsewhere) and some of its links are wrong for
a conversation ("book series" under "group"). A steward sits ABOVE that process and keeps adding and checking
those links. Three closed-choice tasks, each a fixed package built from the graph:

  a. parent  -- a kind with no BROADER parent: the kind, three entities filed under it with their source
                quotes, and the other live kinds as a numbered list. The answer is one number or "none".
  b. kind    -- an entity that is the object of a live `owns` Observation and has no kind: the entity, the
                turns that name it, and the live kinds as a numbered list. One number or "none".
  c. review  -- each WordNet BROADER link: "is every <child> a kind of <parent>?" keep or reject.

The rules it works under (PRINCIPLES 3, and campy-graph rule 3):

  * The steward PROPOSES, it never publishes. Everything it writes is a reifier (an RDF-star node) that does
    NOT assert the link it describes, so the walk (B524) and the ownable test (B523), which read the plain
    `BROADER` / `INSTANCE_OF` triples, cannot see it. status candidate | promoted | rejected | disputed.
  * A model's answer picks from a closed numbered list of kinds that already exist, and echoes the name of the
    one it picked. A number outside the list, or a number whose echoed name is another kind's, is rejected and
    counted; there is no way to name a new kind or an id.
  * A DECLARED RULE promotes (`PROMOTION_RULE`): a proposal is promoted when an independent second source
    agrees: (i) WordNet's hypernym closure contains the parent (`wordnet.hypernym_support`), (ii) the same
    proposal recurs from two different evidence sets (different entities or turns, and the candidate list in the
    opposite order), (iii) a second model family, when one is configured, picks the same answer. A person can also
    agree (`agree`). A steward "reject" of a WordNet link retracts the link only when (ii) or (iii) agrees;
    otherwise the link is "disputed" and stays in the walk.
  * Every vote and every agreeing source is recorded on the reifier (`steward.proposals` reads them).
  * The steward reads the graph only. It is never given a benchmark question or answer, and the model that
    writes the vocabulary is `[llm.steward]` (default the global `[llm]`) while the second source is
    `[llm.steward_second]`, a different model family when one is available (off when the block is absent).

Flag `[observations] vocab_steward` (env `CAMPY_VOCAB_STEWARD`), default off: off, or no model reachable, writes
nothing. Run it as a daemon sweep step or as `scripts/run_steward.py` on a store copy.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from campy.brain.hippocampus import kinds as kinds_mod
from campy.brain.hippocampus.concept_links import norm_key

_logger = logging.getLogger(__name__)

PROMOTION_RULE = (
    "A steward proposal is promoted when an independent second source agrees: (i) WordNet's hypernym closure "
    "contains the proposed parent, (ii) the same proposal recurs from two different evidence sets, or (iii) a "
    "second model family, when configured, gives the same answer. A steward reject of a WordNet link retracts "
    "the link only on (ii) or (iii); otherwise it is disputed and the link stays.")

SOURCE = "steward"
ROUTES = ("wordnet", "recurrence", "second_model", "person")
EXAMPLES_PER_SET = 3          # entities (or turns) shown per call
SETS_PER_RUN = 2              # evidence sets asked per subject per run (the recurrence route needs two)
QUOTE_CHARS = 240
SWEEP_MAX_CALLS = 24          # the daemon sweep step's cap per sweep
MAX_TOKENS = 1500             # output cap per call (a reasoning model spends most of it before it answers)

TASKS = ("parent", "kind", "review")
_BROADER, _INSTANCE_OF = "BROADER", "INSTANCE_OF"


def steward_enabled(config: dict | None) -> bool:
    """`[observations] vocab_steward` (default false; env `CAMPY_VOCAB_STEWARD=1` turns it on)."""
    return bool(((config or {}).get("observations") or {}).get("vocab_steward", False))


def second_model_configured(config: dict | None) -> bool:
    """The second source (iii) exists only when `[llm.steward_second]` is a table in the config."""
    return isinstance(((config or {}).get("llm") or {}).get("steward_second"), dict)


# --- closed answers ---------------------------------------------------------------------

@dataclass(frozen=True)
class Answer:
    kind: str                     # "choice" | "none" | "keep" | "reject" | "invalid" | "mismatch"
    index: int | None = None      # 0-based into the candidate list, for "choice"
    reason: str = ""
    raw: str = ""


def _json_object(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_choice(text: str, labels: list[str]) -> Answer:
    """`{"choice": <1..n | "none">, "name": "<that kind's name>", "reason": "..."}` -> Answer. The answer is
    accepted only if the number is in 1..n AND the echoed name is the listed kind's name: a number the model
    mis-indexed (the reason names one kind, the number another) is "mismatch". Out of range, non-numeric,
    unparsable, or no name: "invalid". The caller counts both and writes nothing."""
    obj = _json_object(text)
    if obj is None or "choice" not in obj:
        return Answer("invalid", raw=text or "")
    raw = obj["choice"]
    reason = " ".join(str(obj.get("reason") or "").split())[:300]
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in {"none", "null", "0", ""}):
        return Answer("none", reason=reason, raw=text)
    try:
        number = int(str(raw).strip())
    except ValueError:
        return Answer("invalid", raw=text)
    if number == 0:
        return Answer("none", reason=reason, raw=text)
    if not 1 <= number <= len(labels):
        return Answer("invalid", reason=reason, raw=text)
    if " ".join(str(obj.get("name") or "").split()).casefold() != labels[number - 1].casefold():
        return Answer("mismatch", number - 1, reason, text)
    return Answer("choice", number - 1, reason, text)


def parse_verdict(text: str) -> Answer:
    """`{"verdict": "keep" | "reject", "reason": "..."}` -> Answer; anything else is "invalid"."""
    obj = _json_object(text)
    verdict = str((obj or {}).get("verdict") or "").strip().lower()
    if verdict not in {"keep", "reject"}:
        return Answer("invalid", raw=text or "")
    return Answer(verdict, reason=" ".join(str((obj or {}).get("reason") or "").split())[:300], raw=text)


# --- packages and prompts -----------------------------------------------------------------

@dataclass
class Package:
    task: str                                         # parent | kind | review
    subject_id: str                                   # the kind (parent, review) or entity (kind) Concept id
    subject: str                                      # its label
    examples: list[tuple[str, str]]                   # (label or turn id, source quote or turn text)
    evidence_set: str                                 # sorted ids, comma-joined: what this call argued from
    candidates: list[tuple[str, str]] = field(default_factory=list)   # (concept id, label), numbered 1..n
    parent_id: str = ""                               # review: the link's parent
    parent: str = ""

    def summary(self) -> str:
        shown = "; ".join(f"{a}: {b}"[:100] for a, b in self.examples) or "(none)"
        return f"{self.subject} | examples: {shown}"


_JSON_CHOICE = ('Reply with JSON only: {"choice": <the number, or "none">, "name": "<that listed kind\'s name, copied>", '
                '"reason": "<one short sentence>"}. Choose only from the numbered list; "none" if no listed kind fits.')
_JSON_VERDICT = 'Reply with JSON only: {"verdict": "keep" or "reject", "reason": "<one short sentence>"}.'


def _examples_block(pkg: Package, heading: str) -> str:
    if not pkg.examples:
        return ""
    lines = [f'- {label}: "{quote}"' if quote else f"- {label}" for label, quote in pkg.examples]
    return heading + "\n" + "\n".join(lines) + "\n"


def build_messages(pkg: Package) -> list[dict]:
    """The fixed package for one call. The same package, byte for byte, goes to the second model."""
    system = ("You curate the vocabulary of kinds of a personal memory graph. You only choose among the options "
              "given; you never invent a kind.")
    if pkg.task == "review":
        user = (f'Claim: every "{pkg.subject}" is a kind of "{pkg.parent}".\n'
                + _examples_block(pkg, f'Things filed under "{pkg.subject}", with the sentence each came from:')
                + f'Is the claim true for a conversation about people\'s lives? {_JSON_VERDICT}')
    else:
        numbered = "\n".join(f"{i}. {label}" for i, (_, label) in enumerate(pkg.candidates, 1))
        if pkg.task == "parent":
            user = (f'Kind: "{pkg.subject}".\n'
                    + _examples_block(pkg, f'Things filed under "{pkg.subject}", with the sentence each came from:')
                    + f'Which numbered kind is the next broader category, so that every "{pkg.subject}" is a kind '
                      f'of it?\n{numbered}\n{_JSON_CHOICE}')
        else:
            user = (f'Entity: "{pkg.subject}" (something one of the speakers owns).\n'
                    + _examples_block(pkg, "Turns that mention it:")
                    + f'Which numbered kind is "{pkg.subject}" an instance of?\n{numbered}\n{_JSON_CHOICE}')
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _chunks(items: list, size: int, count: int) -> list[list]:
    return [items[i * size:(i + 1) * size] for i in range(count) if items[i * size:(i + 1) * size]]


def _set_key(ids: list[str], fallback: str) -> str:
    return ",".join(sorted(ids)) if ids else fallback


# --- the run ------------------------------------------------------------------------------

@dataclass
class Record:
    task: str
    subject: str
    input: str
    answer: str
    reason: str
    outcome: str = ""             # filled after the promotion pass: promoted | rejected | disputed | candidate | -
    child_id: str = ""
    parent_id: str = ""
    relation: str = ""


@dataclass
class StewardReport:
    enabled: bool = True
    llm_unavailable: bool = False
    calls: int = 0
    second_calls: int = 0
    invalid: int = 0              # an answer outside the closed set (or unparsable): rejected and counted
    mismatch: int = 0             # a number whose echoed name is not the listed kind's: rejected and counted
    none: int = 0
    kept: int = 0                 # review: the link was kept (a keep changes nothing, so it is not stored)
    proposed: int = 0             # candidates written / disputes recorded
    agreed: Counter = field(default_factory=Counter)      # route -> count
    promoted: int = 0
    rejected: int = 0             # WordNet links retracted
    records: list[Record] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "llm_unavailable": self.llm_unavailable, "calls": self.calls,
                "second_calls": self.second_calls, "invalid": self.invalid, "mismatch": self.mismatch, "none": self.none, "kept": self.kept,
                "proposed": self.proposed, "agreed": dict(self.agreed), "promoted": self.promoted,
                "rejected": self.rejected}


class _Unavailable(Exception):
    """The model cannot be reached: the run stops and writes nothing more."""


Ask = Callable[[list[dict]], Awaitable[str]]


def _asker(client: Any) -> Ask:
    async def ask(messages: list[dict]) -> str:
        try:
            return await client.achat(messages, max_tokens=MAX_TOKENS)
        except Exception as exc:                       # connection refused, timeout, bad key ...
            raise _Unavailable(str(exc)) from exc
    return ask


def create_clients(config: dict) -> tuple[Any | None, Any | None]:
    """(steward client, second-source client or None). `[llm.steward]` over the global `[llm]`; the second
    source only when `[llm.steward_second]` exists."""
    from campy.brain.llm.provider import create_llm_client_for_step

    primary = create_llm_client_for_step(config, "steward")
    second = create_llm_client_for_step(config, "steward_second") if second_model_configured(config) else None
    return primary, second


async def _label_index(gw: Any) -> dict[str, kinds_mod.Kind]:
    return await kinds_mod.load_kinds(gw)


def _candidate_list(kinds: dict[str, kinds_mod.Kind], exclude: set[str], reverse: bool) -> list[tuple[str, str]]:
    items = sorted(((k.concept_id, k.pref) for k in kinds.values() if k.concept_id not in exclude),
                   key=lambda t: (t[1].casefold(), t[0]))
    return list(reversed(items)) if reverse else items


def _quote(text: Any) -> str:
    return " ".join(str(text or "").split())[:QUOTE_CHARS]


async def _examples_by_entity(gw: Any, kind_id: str) -> list[tuple[str, str, str]]:
    """(entity id, label, first quote) per entity filed under the kind, ordered by id."""
    seen: dict[str, tuple[str, str]] = {}
    for r in await gw.run("steward.kind_examples", kind_id=kind_id):
        eid = str(r["entity_id"])
        if eid not in seen:
            seen[eid] = (str(r.get("entity_label") or ""), _quote(r.get("quote")))
    return [(eid, lab, q) for eid, (lab, q) in sorted(seen.items())]


async def _kind_sets(gw: Any, kind_id: str, rounds: int) -> list[tuple[str, list[tuple[str, str]]]]:
    """Up to `rounds` evidence sets for a kind: (set key, [(entity label, quote)]). A kind with no entity has
    one empty set (the label alone)."""
    ents = await _examples_by_entity(gw, kind_id)
    if not ents:
        return [(f"kind:{kind_id}", [])]
    return [(_set_key([e[0] for e in chunk], kind_id), [(e[1], e[2]) for e in chunk])
            for chunk in _chunks(ents, EXAMPLES_PER_SET, rounds)]


async def _recorded(gw: Any) -> set[tuple[str, str]]:
    return {(str(r["child_id"]), str(r["es"])) for r in await gw.run("steward.recorded_sets")}


async def run_steward(gw: Any, config: dict, *, tasks: tuple[str, ...] = TASKS, max_calls: int | None = None,
                      rounds: int = SETS_PER_RUN, client: Any | None = None, second_client: Any | None = None,
                      only: set[str] | None = None) -> StewardReport:
    """One steward pass. Flag off: nothing, no model is created. `client` / `second_client` override the
    configured models (tests, scripts). `max_calls` caps the primary model calls (a small sample first).
    `only` limits the subjects to labels (case-insensitive). Writes candidates, then applies the promotion rule."""
    report = StewardReport(enabled=steward_enabled(config))
    if not report.enabled:
        return report
    if client is None:
        client, made_second = create_clients(config)
        second_client = second_client or made_second
    if client is None:
        report.llm_unavailable = True
        return report
    ask, ask_second = _asker(client), (_asker(second_client) if second_client is not None else None)
    budget = [max_calls if max_calls is not None else 10 ** 9]
    kinds = await _label_index(gw)
    try:
        if "parent" in tasks:
            await _task_parent(gw, kinds, ask, ask_second, report, budget, rounds, only)
        if "kind" in tasks:
            await _task_kind(gw, kinds, ask, ask_second, report, budget, rounds, only)
        if "review" in tasks:
            await _task_review(gw, kinds, ask, ask_second, report, budget, rounds, only)
    except _Unavailable as exc:
        _logger.warning("vocabulary steward stopped: model unreachable (%s)", exc)
        report.llm_unavailable = True
    await apply_promotion_rule(gw, kinds, report)
    await _fill_outcomes(gw, report)
    return report


async def _call(ask: Ask, ask_second: Ask | None, pkg: Package, parse: Callable[[str], Answer], report: StewardReport,
                budget: list[int]) -> tuple[Answer, bool | None] | None:
    """Ask the primary model (and the second, when the primary's answer is a proposal). None when the call
    budget is spent. Returns (answer, second_agrees or None when there was no second opinion)."""
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    messages = build_messages(pkg)
    answer = parse(await ask(messages))
    report.calls += 1
    if answer.kind == "invalid":
        report.invalid += 1
    elif answer.kind == "mismatch":
        report.mismatch += 1
    elif answer.kind == "none":
        report.none += 1
    agrees = None
    if ask_second is not None and answer.kind in {"choice", "reject"}:
        second = parse(await ask_second(messages))
        report.second_calls += 1
        agrees = second.kind == answer.kind and second.index == answer.index
    return answer, agrees


async def _propose(gw: Any, rel: str, child_id: str, parent_id: str, evidence_set: str, reason: str,
                   report: StewardReport) -> None:
    name = rel.lower()
    await gw.run(f"steward.propose_{name}", cid=child_id, pid=parent_id, reason=reason or "")
    await gw.run(f"steward.add_evidence_{name}", cid=child_id, pid=parent_id, lsrc=SOURCE, es=evidence_set)
    report.proposed += 1


async def agree(gw: Any, relation: str, child_id: str, parent_id: str, by: str, *, link_source: str = SOURCE,
                report: StewardReport | None = None) -> None:
    """Record an independent source (`by`: wordnet, recurrence, second_model, person) that agrees on a pair.
    The promotion pass then promotes it (a steward candidate) or retracts it (a disputed WordNet link)."""
    if by not in ROUTES:
        raise ValueError(f"unknown agreeing source {by!r}")
    await gw.run(f"steward.agree_{relation.lower()}", cid=child_id, pid=parent_id, lsrc=link_source, by=by)
    if report is not None:
        report.agreed[by] += 1


async def _task_parent(gw, kinds, ask, ask_second, report, budget, rounds, only) -> None:
    done = await _recorded(gw)
    for row in sorted(await gw.run("steward.parentless_kinds"), key=lambda r: str(r["kind_id"])):
        kid, label = str(row["kind_id"]), str(row["label"])
        if only and label.casefold() not in only:
            continue
        narrower = {str(r["narrower_id"]) for r in await gw.run("steward.narrower_kinds", kind_id=kid)}
        for i, (key, examples) in enumerate(await _kind_sets(gw, kid, rounds)):
            if (kid, key) in done:
                continue
            pkg = Package("parent", kid, label, examples, key,
                          _candidate_list(kinds, {kid} | narrower, reverse=bool(i % 2)))
            if not pkg.candidates:
                continue
            res = await _call(ask, ask_second, pkg, lambda t, c=[c[1] for c in pkg.candidates]: parse_choice(t, c), report, budget)
            if res is None:
                return
            answer, second_agrees = res
            rec = Record("parent", label, pkg.summary(), "none" if answer.kind != "choice" else pkg.candidates[answer.index][1],
                         answer.reason, "-", kid, relation=_BROADER)
            if answer.kind in {"invalid", "mismatch"}:
                rec.answer = f"{answer.kind.upper()}: {answer.raw[:80]!r}"
            if answer.kind == "choice":
                rec.parent_id = pkg.candidates[answer.index][0]
                await _propose(gw, _BROADER, kid, rec.parent_id, key, answer.reason, report)
                if second_agrees:
                    await agree(gw, _BROADER, kid, rec.parent_id, "second_model", report=report)
            report.records.append(rec)


async def _task_kind(gw, kinds, ask, ask_second, report, budget, rounds, only) -> None:
    done = await _recorded(gw)
    for row in sorted(await gw.run("steward.owned_without_kind"), key=lambda r: str(r["entity_id"])):
        eid, label = str(row["entity_id"]), str(row["label"])
        if only and label.casefold() not in only:
            continue
        turns = [(str(r["message_id"]), _quote(r["text"])) for r in await gw.run("steward.entity_turns", entity_id=eid)]
        sets = _chunks(turns, EXAMPLES_PER_SET, rounds) or [[]]
        for i, chunk in enumerate(sets):
            key = _set_key([m for m, _ in chunk], f"entity:{eid}")
            if (eid, key) in done:
                continue
            pkg = Package("kind", eid, label, [(f"turn {j}", q) for j, (_, q) in enumerate(chunk, 1)], key,
                          _candidate_list(kinds, set(), reverse=bool(i % 2)))
            if not pkg.candidates:
                continue
            res = await _call(ask, ask_second, pkg, lambda t, c=[c[1] for c in pkg.candidates]: parse_choice(t, c), report, budget)
            if res is None:
                return
            answer, second_agrees = res
            rec = Record("kind", label, pkg.summary(), "none" if answer.kind != "choice" else pkg.candidates[answer.index][1],
                         answer.reason, "-", eid, relation=_INSTANCE_OF)
            if answer.kind in {"invalid", "mismatch"}:
                rec.answer = f"{answer.kind.upper()}: {answer.raw[:80]!r}"
            if answer.kind == "choice":
                rec.parent_id = pkg.candidates[answer.index][0]
                await _propose(gw, _INSTANCE_OF, eid, rec.parent_id, key, answer.reason, report)
                if second_agrees:
                    await agree(gw, _INSTANCE_OF, eid, rec.parent_id, "second_model", report=report)
            report.records.append(rec)


async def _task_review(gw, kinds, ask, ask_second, report, budget, rounds, only) -> None:
    done = await _recorded(gw)
    links = sorted(await gw.run("steward.wordnet_links"), key=lambda r: (str(r["child_id"]), str(r["parent_id"])))
    for row in links:
        cid, pid = str(row["child_id"]), str(row["parent_id"])
        child, parent = str(row["child"]), str(row["parent"])
        if only and child.casefold() not in only:
            continue
        for key, examples in await _kind_sets(gw, cid, rounds):
            if (cid, key) in done:
                continue
            pkg = Package("review", cid, child, examples, key, parent_id=pid, parent=parent)
            res = await _call(ask, ask_second, pkg, parse_verdict, report, budget)
            if res is None:
                return
            answer, second_agrees = res
            rec = Record("review", f"{child} -> {parent}", pkg.summary(), answer.kind, answer.reason, "-", cid, pid, _BROADER)
            if answer.kind == "keep":
                report.kept += 1
            elif answer.kind == "reject":
                await gw.run("steward.dispute_broader", cid=cid, pid=pid, es=key, reason=answer.reason)
                report.proposed += 1
                if second_agrees:
                    await agree(gw, _BROADER, cid, pid, "second_model", link_source="wordnet", report=report)
            report.records.append(rec)


# --- the promotion rule -------------------------------------------------------------------

async def apply_promotion_rule(gw: Any, kinds: dict[str, kinds_mod.Kind] | None, report: StewardReport | None = None) -> StewardReport:
    """(i) WordNet agreement for open BROADER candidates, (ii) recurrence over evidence sets, then promote the
    candidates that have an agreeing source and retract the disputed WordNet links that have one. Idempotent."""
    report = report if report is not None else StewardReport()
    kinds = kinds if kinds is not None else await kinds_mod.load_kinds(gw)
    from campy.brain.temporal_lobe.lexicon import wordnet as wn_mod

    if wn_mod.available():
        for r in await gw.run("steward.open_candidates"):
            if r["relation"] != _BROADER:
                continue
            parent = kinds.get(str(r["parent_id"]))
            keys = parent.keys() if parent is not None else {norm_key(str(r["parent"]))}
            if wn_mod.hypernym_support(str(r["child"]), keys) is not None:
                await agree(gw, _BROADER, str(r["child_id"]), str(r["parent_id"]), "wordnet", report=report)
    for r in await gw.run("steward.recurring"):
        await agree(gw, str(r["relation"]), str(r["child_id"]), str(r["parent_id"]), "recurrence",
                    link_source=str(r["lsrc"]), report=report)
    for r in await gw.run("steward.agreed_open"):
        rel, cid, pid = str(r["relation"]), str(r["child_id"]), str(r["parent_id"])
        if r["lsrc"] == SOURCE:
            await gw.run(f"steward.promote_{rel.lower()}", cid=cid, pid=pid)
            report.promoted += 1
        else:
            await gw.run("steward.reject_broader", cid=cid, pid=pid)
            report.rejected += 1
    return report


async def _fill_outcomes(gw: Any, report: StewardReport) -> None:
    """Label each record with where its pair stands now (read from the decision records)."""
    state = {(r["relation"], r["child"], r["parent"]): (r["status"], r["source"]) for r in await gw.run("steward.proposals")}
    labels = {k.concept_id: k.pref for k in (await kinds_mod.load_kinds(gw)).values()}
    for rec in report.records:
        if rec.task == "review":
            child, _, parent = rec.subject.partition(" -> ")
            hit = state.get((_BROADER, child, parent))
            rec.outcome = hit[0] if hit and rec.answer == "reject" else ("kept" if rec.answer == "keep" else "-")
        elif rec.parent_id:
            hit = state.get((rec.relation, rec.subject, labels.get(rec.parent_id, "")))
            rec.outcome = hit[0] if hit else "-"
        else:
            rec.outcome = "-"
