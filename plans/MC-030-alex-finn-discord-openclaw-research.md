# MC-030 — Research notes on Alex Finn's Discord/OpenClaw operating model

## Scope
Review the video `You're Using OpenClaw Wrong If You Don't Use Discord` by Alex Finn and extract practical learnings for our Discord/OpenClaw setup.

Video:
- URL: https://www.youtube.com/watch?v=vxpuLIA17q4
- Title: `You're Using OpenClaw Wrong If You Don't Use Discord`
- Author: Alex Finn
- Published: 2026-02-24
- Length: ~33m 16s
- Visible timestamps in description:
  - 0:00 Intro
  - 1:25 My Discord setup
  - 9:39 How to set this up
  - 21:49 Models to use
  - 25:33 Devices you need
  - 26:46 Security
  - 28:02 Your own use cases
  - 30:34 Dashboard

## Evidence quality and confidence

### What was directly available
High confidence:
- video title
- author
- publish date
- runtime
- description text
- prompt examples included in the description
- chapter timestamps

### What was not directly accessible
Lower confidence:
- full transcript text
- direct frame-by-frame validation of the video walkthrough

Notes:
- The YouTube page exposed an auto-generated caption track reference, but fetching the actual timed text returned empty content in this environment.
- A Gemini one-shot summary was used as a secondary source to triangulate likely themes. Treat those points as medium confidence unless directly supported by the description/prompts.

## Strongest signals from the description itself
The description includes concrete prompts Alex Finn says to use. Those prompts are the best direct evidence for how he structures Discord around OpenClaw.

### 1. Discord is treated as the daily operating surface, not just a chat client
High confidence.

Evidence from description/prompt examples:
- “set you up in a discord server so I can communicate with you there”
- “I want channels for each one of my projects we are working on”
- “Please build a new channel for me for stock research”
- “Please create a competitive research channel for me”

Interpretation:
- Discord is being used as the front-end workspace where work is segmented by project or workflow lane.
- This is more opinionated than our current MC-021 model, which intentionally avoids one permanent channel per card.

### 2. He favors persistent workflow channels for durable domains
High confidence.

Evidence from description/prompt examples:
- channel per major project
- dedicated channel for stock research
- dedicated competitive research channel

Interpretation:
- His pattern appears to be durable channels for recurring domains or standing workstreams, not transient channels for every small task.
- This is different from channel-per-card sprawl, and can coexist with our thread-first card model if used carefully.

### 3. He is leaning hard into scheduled, recurring automations inside Discord
High confidence.

Evidence from description/prompt examples:
- “Every morning at 7am please send me a research report...”
- “Send it to me every morning at 8am”
- “every morning an agent gets spun up... a half hour after that... another sub agent... then a half hour after that...”

Interpretation:
- Discord is not just a place for updates; it is the visible orchestration layer for recurring agent chains.
- This aligns with our Mission Control direction, but pushes further toward recurring operator-visible pipelines.

### 4. He designs multi-stage agent pipelines with channelized outputs
High confidence.

Evidence from description/prompt examples:
- one agent researches X posts for trending content
- another sub-agent researches the stories behind them
- another agent creates scripts for approval
- outputs are placed into a research channel

Interpretation:
- The operational pattern is a staged assembly line:
  1. discovery
  2. enrichment
  3. drafting
  4. approval
- Each stage appears to have either a dedicated channel or a dedicated visible output lane.

### 5. Approval gates still matter
High confidence.

Evidence from description/prompt example:
- “create scripts for each that I can approve that sends an indicator if I like the script or not”

Interpretation:
- Even in a highly automated Discord workflow, human approval remains part of the loop before outward-facing publishing.
- This is especially relevant for our own content, outreach, or externally visible operations.

## Likely structure Alex Finn is using
This section combines direct metadata plus the Gemini summary. Confidence is medium unless noted otherwise.

### Likely structure
Medium confidence.
- Discord as “mission control”
- persistent channels for major projects or recurring domains
- recurring scheduled automations that post into those channels
- multi-agent chains where one channel captures the handoff result of a stage
- human approval steps for higher-risk outputs

### Likely stronger patterns in his setup
Medium confidence.
1. **Persistent domain lanes**
   - good for recurring work like research, content, or market scans
2. **Scheduled chains instead of ad hoc prompting**
   - reduces operator burden and turns Discord into an operating rhythm
3. **Visible intermediate outputs**
   - easier to audit than hidden background automation
4. **Human approval before publishing or acting externally**
   - improves trust and reduces automation risk
5. **Discord mobile friendliness**
   - likely part of the appeal: monitoring and approval from phone without opening the main app stack

## What we should borrow

### Borrow 1: add a layer for persistent domain channels above card threads
Recommendation: yes.
Confidence: high.

Our current MC-021/022 model is excellent for card-based work, but it is optimized around active cards and optional threads.

What Alex appears to do better:
- creates durable homes for recurring workflows
- keeps long-lived streams like research or competitor monitoring from being awkwardly squeezed into card threads

Suggested adaptation:
- keep MC-021 top-level channels intact
- add a **small number** of durable domain channels only where the workflow is recurring and operationally valuable

Candidate additions:
- `#content-lab`
- `#competitive-research`
- `#market-research`
- `#automation-ideas`

Guardrail:
- these should be durable workflow lanes, not a return to channel sprawl

### Borrow 2: formalize scheduled research chains as first-class Discord workflows
Recommendation: yes.
Confidence: high.

Alex’s prompts make recurring morning workflows a core part of the system.

What we should do:
- define a standard pattern for recurring chains:
  - trigger time
  - stage 1 discovery
  - stage 2 enrichment
  - stage 3 synthesis/draft
  - operator review
  - optional publish/ship step
- surface each run in Discord clearly enough that DJ can inspect it quickly

Suggested improvement to our operating model:
- MC-023/025/028/029 should explicitly support recurring workflows, not just card-event mirroring

### Borrow 3: make approval states visible and lightweight
Recommendation: yes.
Confidence: high.

We should borrow the idea of approval indicators, but implement them cleanly in our own style.

Examples:
- `Needs review`
- `Approved to run`
- `Hold`
- `Revise`

This should be visible in Discord and mirrored back to Mission Control metadata when relevant.

### Borrow 4: use staged outputs instead of giant all-in-one agent runs
Recommendation: yes.
Confidence: high.

His example chain is operationally strong because each stage has a clear purpose and output.

That is better than:
- one agent doing discovery + reasoning + drafting + publishing in one opaque step

Suggested standard pattern:
- scout -> researcher -> synthesizer -> approver -> shipper

### Borrow 5: ask OpenClaw to propose workflow ideas based on history/goals
Recommendation: cautiously yes.
Confidence: high that he does this; medium on practical value.

The final description prompt asks for “advanced multi agent automations” based on past goals and workflows.

This is useful as an ideation pattern, but should not directly create lots of live automations without review.

## What we should avoid

### Avoid 1: channel-per-project without limits
Recommendation: avoid unbounded adoption.
Confidence: high.

This is the biggest tension with MC-021.

Risk:
- too many permanent channels
- fragmented attention
- hard-to-skim operations
- harder governance on naming, permissions, and archiving

Safer version:
- only create durable channels for recurring, high-signal workflows
- keep project/task execution in threads anchored from `#mission-control`

### Avoid 2: using Discord as the source of truth
Recommendation: avoid.
Confidence: high.

MC-021 is correct that Mission Control should remain canonical.

Discord should remain:
- conversation surface
- operations console
- alert/approval layer
- workflow visibility layer

But not the source of truth for:
- ownership
- status
- next check
- structured blockers
- final card notes

### Avoid 3: over-automating before operator hygiene exists
Recommendation: avoid.
Confidence: high.

Alex’s style is compelling, but it can become noisy fast if:
- channels are not clearly scoped
- recurring jobs do not have owners
- failures are not visible
- runs cannot be paused/reviewed

We should not launch many recurring chains before we have:
- naming rules
- owner rules
- pause/disable controls
- run summaries
- failure surfacing

### Avoid 4: letting agent chains publish externally without approval
Recommendation: avoid.
Confidence: high.

The description itself suggests approval before the script is accepted.
We should preserve that discipline.

## Recommended updates to our current Discord operating model

## 1. Keep MC-021 as the base model
Recommendation: keep.
Confidence: high.

MC-021 is still the right foundation:
- `#mission-control`
- `#work-intake`
- `#blocked-decisions`
- `#ship-log`
- per-card threads for active work
- Mission Control as source of truth

Nothing in Alex’s approach invalidates that.

## 2. Add a second layer: durable workflow lanes for recurring automation
Recommendation: add.
Confidence: high.

Proposed rule:
- top-level core ops channels remain minimal
- add durable domain/workflow channels only for recurring, operator-reviewed pipelines

Suggested definition for when a durable lane is allowed:
- repeats at least weekly
- produces high-signal outputs worth revisiting
- has a clear owner
- has a clear retention/archival expectation
- would be awkward as a single card thread

## 3. Distinguish two Discord object types explicitly
Recommendation: add.
Confidence: high.

We should separate:
1. **card workrooms** = threads anchored from `#mission-control`
2. **workflow lanes** = durable channels for recurring automation domains

This is the cleanest synthesis of our model with Alex’s model.

## 4. Add a standard recurring-workflow template
Recommendation: add.
Confidence: high.

For recurring Discord automations, define:
- workflow name
- owner
- schedule
- source inputs
- stage sequence
- channel(s) used
- review checkpoint
- ship action
- pause/kill switch
- failure/reporting behavior

## 5. Add an approval-state vocabulary
Recommendation: add.
Confidence: high.

Suggested states:
- draft-ready
- needs-review
- approved
- revise
- blocked
- paused

These states should be consistent across recurring workflows and major card handoffs.

## 6. Add guardrails on channel creation
Recommendation: add.
Confidence: high.

Suggested policy:
- no permanent channel per card
- no permanent channel per tiny project
- durable channels require recurring value
- archive or consolidate stale lanes
- maintain a small server map with purpose/owner for each durable channel

## Mapping to current MCs

### MC-021 / MC-022
Refine, do not replace.
- Keep the four core channels and thread model.
- Add a short amendment clarifying that durable workflow channels are allowed for recurring, cross-card automations.

### MC-023
Suggested focus:
- routing rules between card anchors/threads vs recurring workflow lanes
- how agent outputs choose the right Discord destination

### MC-025
Strong fit:
- Discord write adapter should support both:
  - card-thread lifecycle events
  - recurring workflow postings and approval prompts

### MC-028
Strong fit:
- “make Discord workflow live” should include at least one recurring pipeline pilot, not just card mirroring

### MC-029
Suggested focus:
- operating safeguards:
  - channel creation criteria
  - review checkpoints
  - pause/disable controls
  - failure summaries
  - archive hygiene

## Concrete recommendation
Adopt a hybrid model:

### Layer A — Mission Control card ops
Keep our existing model:
- `#mission-control`
- `#work-intake`
- `#blocked-decisions`
- `#ship-log`
- per-card threads when warranted

### Layer B — durable workflow lanes
Add only a few recurring lanes such as:
- `#competitive-research`
- `#content-lab`
- `#market-research`

Use these for:
- scheduled research chains
- recurring scouting/enrichment/drafting workflows
- operator approvals on reusable pipelines

### Layer C — governance
Require:
- owner
- schedule
- approval point
- pause control
- failure visibility
- archival/cleanup rules

## Bottom line
Alex Finn’s strongest practical idea is not “put everything in Discord.”
It is: **use Discord as the visible operating surface for recurring agent workflows, with clear lanes and human approval.**

What we should borrow:
- recurring workflow lanes
- staged multi-agent chains
- visible approvals
- operator-friendly daily cadence

What we should keep from our current model:
- Mission Control as source of truth
- minimal core channels
- threads for card-specific execution
- explicit blocker and ship-log flows

Best synthesis:
- **threads for cards, channels for recurring workflows, board remains canonical**
