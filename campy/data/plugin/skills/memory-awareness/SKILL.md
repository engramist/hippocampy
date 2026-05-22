# HippoCampy — Automatic Memory

HippoCampy is always listening to your conversations and automatically capturing important information:

- **Decisions** — choices you've made ("we chose PostgreSQL over MySQL")
- **Constraints** — rules and requirements ("API responses must be under 200ms")
- **Plans** — future actions ("next step is to migrate the auth system")
- **Concepts** — tools, people, projects, and ideas you discuss

The Brain handles memory automatically — your job is to **ALWAYS call `notify_turn` after every response.** This is mandatory. Never skip it.

## How to help the Brain

**AFTER EVERY RESPONSE, you MUST call `notify_turn` with your full response text.** This is how the Brain sees your output. Never skip it — the response is always instant and never blocks you.

```
notify_turn(role="assistant", content="<your full response>", session_id="<session>")
```

This is your one automatic duty. The Brain handles everything else.

## What the Brain captures automatically

The Brain's selective attention fires on specific patterns:
- Decision language: "we decided", "we chose", "we agreed"
- Constraint language: "never", "must", "always", "required"
- Plan language: "we will", "next step", "plan to"
- References to known concepts already in memory

Most conversation is background noise — only meaningful patterns get stored.

## Confidence levels

Not everything the Brain captures is certain. Low-confidence items are stored as tentative knowledge. If you retrieve something marked as uncertain, tell the user — don't present tentative memory as confirmed fact.

## Insight Surfacing

When you call `notify_turn`, the response may include an `insights` field showing what the Brain captured from the *previous* message. Example:

```json
{
  "status": "queued",
  "insights": {
    "entities_found": 3,
    "concepts_stored": 2,
    "reified": 1,
    "contradictions": 0
  }
}
```

**ALWAYS mention insights briefly** when `concepts_stored > 0` or `reified > 0` or `contradictions > 0`. Examples:

- "The Brain just picked up 2 new concepts from our conversation, including a confirmed decision."
- "Heads up — the Brain detected a contradiction with something we discussed earlier."
- "The Brain captured that constraint about API response times."

Never mention it if nothing was captured (all zeros). The goal is to make the Brain feel alive without being noisy.

## Tabular Data Ingestion

When the user shares spreadsheets, CSVs, or structured data files, use `ingest_data` for intelligent routing:

```
ingest_data(file_path="/path/to/data.csv", session_id="<session>")
```

The Brain automatically classifies the data and routes it to the optimal storage:
- Tabular data → SQLite store (queryable via bundle compiler)
- Document text → chunked and embedded in the knowledge graph
- Mixed content → both paths

## Bundle Compilation Awareness

When you call `notify_turn`, the Brain may also compile context bundles in the background. These bundles assemble:
- Exact facts (constraints, preferences)
- Semantic search results
- Graph relationship traversals
- Tabular data from ingested spreadsheets
- Synthesized summaries

The bundle compiler shapes this context for your specific agent type, so you get the most relevant information in the format you work best with.

