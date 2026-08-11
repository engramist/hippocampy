# Campy — Positioning

**Status:** internal source material for messaging, not final copy. Every factual claim below
is traceable to something in this repository; the "Verification" column says where. Read
"Before publishing externally" at the end before using any of it outside the team.

---

## The position, in one sentence

**Your agent memory should belong to you and travel with you — across harnesses, across
models, local or cloud.**

Not anti-cloud. Not anti-vendor. Anti-*lock-in*.

## The problem: memory is the lock-in

Every assistant vendor now ships a memory feature, and every one of them is a silo. A decision
you made in one harness is invisible in the next. Switch tools and you start from zero.

That is not an oversight. Accumulated context is the highest-switching-cost asset a vendor can
hold, precisely because it cannot be re-created — you would have to redo the work that produced
it. The better a vendor's memory gets, the more expensive leaving becomes.

The pain is already ordinary. Most people doing serious work with these tools use more than
one: a CLI agent for code, a desktop app for thinking, something else for review. Each one
remembers its own half of the story, and nothing remembers the whole of it.

## What Campy is

A memory layer that sits underneath the harnesses instead of inside one of them. One graph;
every tool reads and writes the same memory. Change harness, change model, change deployment —
the memory stays.

## Evidence, not adjectives

The claim is portability, so the evidence is the integration surface. All of this is checked
into this repository:

| Claim | Verification |
|---|---|
| Works across harnesses | 6 adapters in `adapters/`: Claude Code, Claude Desktop, Codex, Gemini CLI, ChatGPT Desktop, Hermes |
| Works across model providers | `campy/brain/llm/provider.py`: Ollama, OpenAI, Anthropic, Google — plus AWS Bedrock (card B324) |
| Runs where you run | Local daemon today; multi-tenant deployment into your own cloud account is cards B315/B316 |
| Your data is exportable | `export_graph` / `import_graph` in `campy/brain/hippocampus/graph/export.py` — full round-trip |

Six harnesses against one graph is a directory listing, not a marketing assertion. That is the
point: the claim is checkable.

## The ownership test

"Your memory is yours" is unfalsifiable unless there is a way to take it and go. So the test we
hold ourselves to is: **can a user leave with everything, in a format we do not control?**

Two pieces of the architecture exist to make that answer yes:

- **Export/import round-trip** — the whole graph, as plain files.
- **Earned vs projected memory** (card B313) — Campy distinguishes what it *learned* (exists
  nowhere else, irreplaceable, always yours) from what it *mirrors* from a system you already
  own (regenerable, and never a second source of truth for it). Backup and restore (card B319)
  are scoped by that split.

A vendor whose memory you cannot export is not offering you memory. They are offering you a
reason to stay.

## Supporting argument: context you can query beats a transcript you must re-read

A linear chat transcript grows without bound, and everything in it is re-read on every turn
whether or not it is relevant. A graph is queried: you retrieve the part that bears on the task
and leave the rest on disk.

We hold this to a measurement rather than an assertion, and we publish the harness. From
`benchmarks/RESULTS.md` (run 2026-03-28, git `d54ddc6`, local Ollama, 8 GB / 80% CPU limits):

| Benchmark | Metric | Result | p-value |
|---|---|---|---|
| ARC3 | solve-rate improvement | +0.08 | 0.042 |
| SWE_CI | constraint-compliance improvement | +0.12 | 0.008 |
| LONGCONTEXT | long-context accuracy improvement | +0.05 | 0.015 |
| AMA | hypothesis regression (lower is better) | −0.05 | 0.033 |

Reproduce with `python benchmarks/runner.py --all`; artifact checksums are in the same file.

**We do not claim zero token cost.** Compiling a context bundle spends tokens too. The claim is
narrower and defensible: tokens spent on retrieved, relevant context rather than on re-reading a
transcript. Card B305 exists because our own bundles were once returning irrelevant filler, and
the relevance floor that fixed it is what makes this claim honest.

## What we do not claim

Stating the limits is part of the pitch — the audience is engineers, and they will find these
anyway.

- **Not a coordination or locking layer.** Campy does not prevent concurrent agents from
  overwriting each other's work; that needs isolation in your build runtime. Campy is advisory
  and fails open — if it is unavailable, your agents run without it rather than stopping
  (card B318).
- **Not a replacement for your systems of record.** Git, your issue tracker, and your workflow
  engine remain authoritative for what they own. Campy can mirror them, labelled as mirrored.
- **Not a model or an agent.** Campy stores and retrieves; the LLM does the thinking.
- **Benchmarks are ours.** They are reproducible and the harness is public, but they are our
  benchmarks on our hardware. Run them yourself.

## Tone

Plain, specific, checkable. The strongest asset is that every claim resolves to a file, a
command, or a number — so nothing needs inflating, and no competitor needs naming. An argument
that stands on its own evidence survives a competitor shipping a fix next quarter; an argument
built on their current flaws does not.

---

## Before publishing externally

Open items for whoever turns this into public copy:

1. **Benchmark data is dated 2026-03-28 and labelled "SideQuests"** — the previous product name,
   and roughly four and a half months old at time of writing. Either re-run and regenerate, or
   date the figures explicitly wherever they appear. Do not quietly present them as current.
2. **Benchmarks ran on small local models via Ollama** (qwen2.5:3b, llama3.2:3b, phi3.5,
   llama3.1:8b). That is a fair setup to publish, but say so — results on frontier models are
   not established by this run.
3. **B324 (Bedrock) is a card, not shipped.** The provider table above lists it as such; keep
   that distinction if the table is reused.
4. **B313/B315/B316/B318/B319 are likewise cards.** Anything citing them must say "planned," not
   "available."
5. **Do not make factual claims about named competitors** without a dated, linkable source —
   particularly claims about their security or encryption posture. The argument above does not
   need one, which is a feature.
