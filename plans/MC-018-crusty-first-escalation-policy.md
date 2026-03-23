# MC-018 — Crusty-first escalation policy for autonomous execution

## Purpose

DJ approved a more autonomous operating model:
- Claws should proceed by default.
- Only higher-risk categories should pause for review.
- Those ask-first cases should go to **Crusty first**, not directly to DJ.
- **Crusty** is the decision gate for most risky work and only elevates to DJ when explicit criteria are met.

This policy defines:
1. what Claws routes to Crusty first
2. what Crusty can approve or decide without DJ
3. what Crusty must elevate to DJ
4. the operational changes needed to make the rule durable

---

## Default operating rule

### Claws
If work is:
- low-risk
- reversible
- inside established strategy
- not public/external
- not materially expensive

then **Claws proceeds without asking**.

### Crusty-first rule
If work falls into an ask-first category, **Claws routes it to Crusty first** with:
- the requested action
- why it may be risky
- the likely blast radius
- reversibility
- recommended path
- what decision is needed

### DJ interruption rule
DJ should only be interrupted when the issue crosses a threshold that is:
- business-critical
- trust/safety-critical
- materially costly
- materially irreversible
- strategy- or priority-setting
- likely to create personal/account/legal exposure for DJ

---

## Tier model

### Tier 0 — Auto-proceed
Claws proceeds without review.

Examples:
- normal research, writing, planning, summaries
- routine code/docs changes in the active repo
- low-risk refactors
- bug fixes with clear rollback
- internal task organization
- normal test runs and local verification
- reversible file edits that do not delete important assets

### Tier 1 — Route to Crusty first
Claws pauses and asks Crusty, but does **not** interrupt DJ.

This is the default destination for higher-risk execution.

### Tier 2 — Crusty may approve/decide
After review, Crusty can authorize or choose the path without DJ if the action:
- stays within DJ’s already stated goals
- is technically/risk-wise understandable
- is reversible or containable
- does not create meaningful external, financial, or reputational exposure
- does not change the top-level strategy, ownership, or commitments

### Tier 3 — Crusty must elevate to DJ
Crusty must escalate when the decision affects DJ’s authority, money, reputation, identity, account control, legal position, or major roadmap direction.

---

## What Claws routes to Crusty first

Claws should route the decision to Crusty before acting when any of the following are true.

### 1) Destructive or hard-to-reverse changes
Examples:
- deleting data, branches, cards, logs, or artifacts that are not clearly disposable
- schema/data migrations with possible loss or corruption
- force-pushes, history rewrites, bulk renames, or large moves
- replacing operational configs in ways that may break running systems
- changing or removing monitoring, audit, or workflow history

**Why routed to Crusty first:** technical blast radius and reversibility need review.

### 2) External or public side effects
Examples:
- sending messages to outside users or communities
- posting publicly
- opening/closing/commenting on GitHub issues or PRs in a way that represents DJ/org intent
- contacting vendors, collaborators, customers, or stakeholders
- triggering integrations that create outward-facing events

**Why routed to Crusty first:** external action may be operationally valid but still needs judgment on representation and timing.

### 3) Material technical risk
Examples:
- production/runtime config changes
- auth/token/account-context changes
- gateway, cron, delivery, or routing changes with system-wide impact
- security-sensitive code paths
- architectural refactors that alter contracts or workflow semantics
- automations that can self-trigger, chain, or fan out

**Why routed to Crusty first:** these are CTO-shaped calls.

### 4) Major strategy or priority changes
Examples:
- changing what project/repo owns a workstream
- redefining ownership between Claws, Crusty, Gemini, or automation
- changing roadmap order without a clear prior DJ instruction
- creating new durable policies that alter how the org runs
- reframing project scope, boundaries, or product direction

**Why routed to Crusty first:** Crusty can filter technical/operational noise before DJ gets interrupted.

### 5) Costly or resource-intensive actions
Examples:
- actions likely to consume paid API budget materially
- long-running compute/workloads with unclear payoff
- spawning large numbers of agents/jobs
- tasks that may create repeated retries or runaway automation
- purchases/subscriptions/infrastructure spend questions

**Why routed to Crusty first:** cost/benefit and safeguards need review.

### 6) Ambiguous risk or unclear user intent
Examples:
- request appears safe but hidden blast radius is plausible
- user intent conflicts with existing policy or repo boundaries
- unclear whether action is routine execution or strategic commitment
- uncertainty about whether a message/action would speak for DJ personally

**Why routed to Crusty first:** ambiguity itself is a routing signal.

---

## What Crusty can approve or decide without DJ

Crusty may decide and instruct execution without DJ when all of the following are true:

1. **Within intent** — the action is clearly in-bounds with DJ’s stated goal or active card.
2. **No major strategy reset** — the decision does not materially change roadmap, ownership, or business direction.
3. **Contained blast radius** — impact is local, technically understandable, and reversible or recoverable.
4. **No meaningful external commitment** — it does not commit DJ to promises, positions, or relationships.
5. **No meaningful financial/legal exposure** — cost is minor and ordinary; no contract, legal, or compliance implications.
6. **No identity/account transfer** — the action does not hand over, revoke, or materially change control of DJ’s accounts, secrets, or public voice.
7. **Auditability exists** — the decision and reasoning can be written to the card/spec/notes.

### Typical decisions Crusty can make alone
- approve risky-but-contained technical fixes
- approve reversible destructive actions with backup/rollback plan
- approve internal repo reorganization when strategy is already decided
- approve runtime/config/debugging changes in service of an existing goal
- choose between technical implementation paths
- throttle, stage, or sandbox a risky change instead of blocking it
- require extra guardrails, logging, backups, or tests before execution
- reject a proposed action and send Claws back with a safer alternative

### Crusty’s expected response shape
For Tier 1/Tier 2 asks, Crusty should answer in one of four forms:
- **approve** — proceed as proposed
- **approve with guardrails** — proceed with explicit limits/checks
- **reroute** — different owner/path, no DJ needed
- **elevate to DJ** — include exact reason and question for DJ

---

## What Crusty must elevate to DJ

Crusty must elevate when any of the following are true.

### 1) Strategy / priority authority
- changes top-level roadmap or business direction
- changes repo/product boundaries in a way not already authorized
- changes who owns a major area of responsibility
- trades off one major objective against another without clear DJ guidance

### 2) External commitments or public representation
- public statements in DJ’s name
- commitments to customers, collaborators, or community members
- promises about timelines, scope, support, availability, or roadmap
- sensitive PR/issue/comment actions that imply official position beyond routine maintenance

### 3) Money / spend / commercial exposure
- any real-money spend, subscription, or infrastructure commitment above normal incidental usage
- materially higher model/API spend than established norms
- anything that could create billing surprises or recurring cost

### 4) Secrets / account control / trust boundaries
- creating, rotating, sharing, revoking, or relocating high-value secrets
- changing account ownership, admin access, login method, or public-facing identities
- actions that could expose private data or widen system access materially

### 5) Legal / policy / safety exposure
- anything plausibly involving compliance, licensing, privacy, regulated data, or legal risk
- any step that could be interpreted as deceptive, manipulative, or unsafe in a user-facing context
- any security incident or suspected compromise with non-trivial impact

### 6) Irreversible or high-blast-radius actions
- no good rollback path
- possible data loss affecting important assets
- multi-system changes that could impair normal operation broadly
- irreversible publication, deletion, migration, or transfer

### 7) Human preference or value judgment dominates
- the choice is not mainly technical but personal, aesthetic, political, reputational, or relationship-driven
- multiple acceptable options exist and the tie-breaker is “what DJ prefers”

### 8) Conflicting instructions or unclear mandate
- DJ’s past instructions conflict
- Crusty cannot confidently map the action to existing authority
- the action would be hard to defend later without explicit DJ buy-in

---

## Quick decision rubric for Crusty

Use this sequence.

### Crusty approves without DJ if:
- goal is already authorized
- risk is technically understandable
- rollback exists
- cost/exposure is minor
- no major public/business commitment is created

### Crusty elevates to DJ if any answer is yes:
- does this set or reset strategy?
- does this spend meaningful money or create recurring cost?
- does this speak publicly for DJ or commit DJ to others?
- does this change account control, secrets, or trust boundaries?
- does this create meaningful legal, safety, or reputational risk?
- is the action effectively irreversible?
- is the real question mostly DJ preference rather than technical judgment?

If yes to any of the above, elevate.

---

## Operational updates required

### 1) Add explicit routing language to card handoffs
For cards or asks routed from Claws to Crusty, include:
- `risk_tier`: `tier0_auto | tier1_crusty_review | tier2_crusty_decide | tier3_dj_required`
- `risk_reason`
- `blast_radius`
- `reversibility`
- `external_effects`
- `cost_scope`
- `dj_decision_required`: true/false
- `dj_decision_question`: nullable string

### 2) Add a standard decision note format
When Crusty reviews an ask, record:
- decision: approve / approve_with_guardrails / reroute / elevate_to_dj
- rationale
- required guardrails
- rollback/containment plan
- exact question for DJ if escalated

### 3) Update Claws operating discipline
Claws should stop asking DJ directly for routine ask-first categories.
Instead:
1. classify risk
2. route Tier 1+ to Crusty
3. wait for Crusty decision
4. only interrupt DJ if Crusty marks `elevate_to_dj`

### 4) Keep DJ escalations narrow
When Crusty elevates, the message to DJ should include only:
- what action is proposed
- why Crusty will not decide it alone
- options/recommendation
- the exact approval or preference needed

### 5) Preserve auditability in Mission Control
MC cards that cross risk thresholds should carry:
- the tier
- who made the risk decision
- whether DJ was interrupted
- the explicit escalation trigger

This prevents policy drift back into chat-only decisions.

---

## Recommended defaults by actor

### Claws default
Proceed unless the action looks Tier 1+.
Do not route uncertainty directly to DJ unless there is an obvious Tier 3 trigger.

### Crusty default
Decide whenever the issue is primarily technical/operational and contained.
Do not elevate merely because a decision is non-trivial.
Elevate only when DJ’s authority, money, reputation, trust boundary, or strategic preference is actually implicated.

### DJ default
Only receives compressed, decision-ready questions.
DJ should not be used as a generic safety blanket for normal higher-risk execution.

---

## Examples

### Example A — safe destructive cleanup
Delete generated artifacts and stale logs after backup, in a known local path.
- Claws routes to Crusty if the deletion is not obviously disposable.
- Crusty can approve with guardrails: verify path, backup retained, no user data.
- No DJ escalation needed.

### Example B — public GitHub response implying roadmap commitment
A PR comment would commit to delivery timing or product direction.
- Claws routes to Crusty.
- Crusty recognizes external commitment + roadmap implication.
- Crusty elevates to DJ.

### Example C — runtime auth fix with reversible config change
Need to patch cron/delivery auth behavior in a contained way.
- Claws routes to Crusty.
- Crusty approves, adds logging + rollback guardrails.
- No DJ escalation unless the fix requires rotating high-value secrets or changes account ownership.

### Example D — spinning up many costly runs
A plan would fan out many model calls with unclear cap.
- Claws routes to Crusty.
- Crusty may approve only with budget cap / batch limit / stop condition.
- Elevate to DJ only if spend becomes materially meaningful or recurring.

### Example E — repo boundary change
Move a large workstream into a new repo without prior authorization.
- Claws routes to Crusty.
- If DJ already decided the boundary, Crusty can decide execution details.
- If boundary direction itself is still open, Crusty elevates to DJ.

---

## Durable policy summary

1. **Proceed by default.**
2. **Ask-first categories go to Crusty first, not DJ.**
3. **Crusty is the normal approval gate for risky but contained technical/operational work.**
4. **Crusty elevates only for strategy, money, external commitments, secrets/account control, legal/safety/reputation, irreversibility, or DJ-preference questions.**
5. **All such decisions should be written onto cards/specs so the policy survives the chat that created it.**
