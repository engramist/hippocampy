# The fact contract

Approved 2026-11-10 (plan step 0b, `learnings/e2e-improvement-plan.md`). Design only; steps 1-3 of the plan build it.

This is what Campy hands any consumer of memory: its own `ask` stage, an MCP tool, an outside agent. It is also the target for capture: if the contract names an edge, capture writes it.

## 1. A fact

A fact is one claim node (`Observation`) with typed roles. Each role is an edge to an entity, or a typed value. Nothing is kept as untyped free text without a flag.

| Role | Required | Filled by | Edge or field | In the store today |
|---|---|---|---|---|
| subject | yes | entity | `HAS_SUBJECT` | 89% of facts |
| relation | yes | one of the 9 predicates | `predicate` | 100% |
| action | for `did` and `plans` | an action kind (bike, paint, adopt) | **`HAS_ACTION`, new** | 0%: the verb sits inside the object text |
| object | when the claim has one | entity with a kind, or a typed value (number, date, amount) | `HAS_OBJECT`, `attr_value_*` | 43% have the edge; 31% of object entities have a kind |
| with | when stated | entity | **`HAS_PARTICIPANT`, new** | 0% |
| place | when stated | place entity | **`HAS_PLACE`, new**; places chain by `LOCATED_IN` | 0% |
| event time | when stated | date or range, resolved by rule from the turn's date | existing time fields | present (the `when:` phrase and its resolved date) |
| said on | yes | date of the source turn | `EVIDENCED_BY` to `Message.occurred_at` | 100% |
| source turn | yes | the turn, with its speaker | `EVIDENCED_BY`, `SPOKEN_BY` | 100% |
| standing | yes | asserted, negated, planned, hypothetical; superseded or current | `polarity`, `DEPRECATED_BY` | present |

Example of the gap. The turn "Had a blast biking nearby with my neighbor last week" is stored today as `I | did | "bike"`, with no object entity. Under the contract it is: subject the speaker, action *bike* (a kind of cycling, a kind of exercise), with *neighbor*, event time the week before the turn, source turn attached.

A role that cannot be filled by an entity or typed value is kept as text and flagged `text`. A fact with no resolved subject is flagged `unanchored`. Reasons and opinions ("why", "what does she think") are `text` by nature: the contract carries their source turn and does not compute over them.

Kinds for actions, objects and places come from a rule or an independent source (P3), not from the extractor's free choice.

## 2. A computed result

A computed result is the output of one registered query, anchored on a subject.

| Field | Content |
|---|---|
| operation | list, count, latest, first, exists, before/after |
| anchor | the subject entity, plus the relation, action kind or object kind asked about |
| rows | the facts that produced it, each with its source turn |
| empty | an empty result is the answer "not recorded"; nothing is approximated |

The consumer is told it is computed, by which operation, and from which rows.

## 3. Renderings

One contract, two renderings. The layout is a lever and is gated in step 3; the lines below show the content, not the final layout.

- **For `ask`** (small model): one fixed-shape line per fact, and one block per computed result.
  - `[fact] Melanie · did · paint · lake sunrise (artwork) · when 2022 · said 2023-05-08 · "Yeah, I painted that lake sunrise last year!"`
  - `[computed: list, 2 rows] Evan · owns · kind car → old Prius; new Prius` followed by the two fact lines.
- **For outside agents**: the same fields as structured output from the MCP tools. Built after step 4, with its own measure.

## 4. Does it cover the questions?

The 809 category 1-4 questions of the five gate conversations, grouped by their opening word. This is a rough count for coverage, not a router.

| Question shape | Count | Served by |
|---|---|---|
| what / which | 477 | object, action or attribute of the subject's facts; lists |
| when / how long | 161 | event time |
| why / how | 81 | `text` facts with their source turn; not computed |
| would / is it likely | 35 | the answer model reasons over the facts; not computed |
| where | 25 | place, `LOCATED_IN` |
| who | 19 | subject or with |
| how many / how much | 11 | count, or a stated number |

About 86% of the questions ask for a role the contract names. The other 14% (why, would) need the source turns and the model's judgement; the contract hands those over and promises no more.

## 5. New edges, and what reads each

No write-only terms: each new edge is read by a named query in step 3.

| New edge | Read by |
|---|---|
| `HAS_ACTION` (fact to action kind) | "what did X do", lists and counts of a kind of activity, through `BROADER*` |
| `HAS_PARTICIPANT` (fact to entity) | "who did X ... with", "what did X and Y do" |
| `HAS_PLACE` (fact to place), `LOCATED_IN` (place to place) | "where", "which country / state / city" |

## 6. Decisions (approved 2026-11-10)

1. **Roles, not more predicates.** Keep the 9 predicates and add the action, with and place roles. A wider predicate list was the alternative; it was not chosen, because a verb is a kind, and kinds already have a hierarchy the queries can walk.
2. **Text is allowed, but flagged.** Reasons and opinions stay as text with their turn. The alternative, forcing every object into an entity, would invent entities.
3. **Action kinds from an independent source** (a verb hierarchy such as WordNet's), with the model choosing from a closed set and a rule confirming.
