# HippoCampy — Automatic Memory

HippoCampy is always listening to your conversations and automatically capturing important information:

- **Decisions** — choices you've made ("we chose PostgreSQL over MySQL")
- **Constraints** — rules and requirements ("API responses must be under 200ms")
- **Plans** — future actions ("next step is to migrate the auth system")
- **Concepts** — tools, people, projects, and ideas you discuss

You don't need to tell the Brain what to remember — it uses selective attention to pick up meaningful signal from conversation noise. Think of it like a colleague who's always taking notes in the background.

## How to help the Brain

After every response you give, call `notify_turn` with your full response text. This is how the Brain sees your output. Never skip it — the response is always instant and never blocks you.

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

When insights are present and meaningful (concepts_stored > 0 or reified > 0 or contradictions > 0), briefly mention it to the user in a natural way. Examples:

- "The Brain just picked up 2 new concepts from our conversation, including a confirmed decision."
- "Heads up — the Brain detected a contradiction with something we discussed earlier."
- "The Brain captured that constraint about API response times."

Keep it brief — one sentence, not a summary dump. Don't mention it if nothing was captured (all zeros). The goal is to make the Brain feel alive without being noisy.
