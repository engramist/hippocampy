# B27 OpenClaw Passive Ingestion Validation Plan

Status: Draft for approval
Owner: Opus (plan) -> Gemini CLI (implementation)
Primary card: backlog/B27.md
Related blocker: backlog/B29.md

## Goal
Validate and lock the OpenClaw passive-ingestion hook contract so SideQuests can reliably capture both user and assistant turns in live OpenClaw sessions.

This plan turns the current assumed event wiring in the OpenClaw extension into an explicit, testable contract. It does not change the Brain Daemon or loop logic. It focuses on the plugin boundary where passive ingestion is currently weakest.

## Scope
In scope:
- Extract the OpenClaw event contract from hardcoded assumptions into explicit constants/helpers
- Normalize payload extraction for user and assistant turn events
- Add lightweight diagnostic logging so live validation can confirm which hooks fire and with what payload shape
- Add regression tests that fail if event names or payload extraction logic changes silently
- Add a short compatibility note in code or docs describing the validated event names and payload fields

Out of scope:
- B29 end-to-end cross-session recall harness
- Brain Daemon memory semantics or retrieval ranking
- Quest routing changes
- OpenClaw transport changes
- Building a full TypeScript unit-test harness for the extension

## Current State (verified)
File: extensions/sidequests-brain/src/index.ts

The extension already wires three assumed OpenClaw events:
- llm_input -> forwards event.prompt as a user notify_turn
- llm_output -> forwards event.assistantTexts as an assistant notify_turn
- before_agent_start -> queries current_truth using event.prompt

Current weaknesses:
1. Event names are hardcoded and undocumented beyond inline comments.
2. Payload extraction is optimistic and assumes event.prompt and event.assistantTexts are always present with the expected shape.
3. All failures are silently swallowed in catch blocks, so a contract drift looks like "memory just stopped working".
4. Existing tests only verify alias wiring and startup behavior; they do not pin passive-ingestion event wiring.
5. The extension package has no JS/TS test runner configured, so this repo's practical test strategy is Python source-level assertions plus targeted compile validation.

## Files To Modify
1. extensions/sidequests-brain/src/index.ts
2. tests/test_extension_aliases.py
3. tests/test_b41_plugin_startup.py

## Files To Create
1. tests/test_extension_ingestion_contract.py

Optional if the compatibility note is moved out of code:
2. docs/openclaw-event-contract.md

## Implementation Strategy

### 1. Make the event contract explicit in the extension
File: extensions/sidequests-brain/src/index.ts

Add a small contract block near the top of the file so the expected OpenClaw event names and payload fields are visible and reusable.

Add constants similar to:

```ts
const OPENCLAW_EVENT_CONTRACT = {
  userTurnEvent: "llm_input",
  assistantTurnEvent: "llm_output",
  preAgentEvent: "before_agent_start",
  userPromptFields: ["prompt"],
  assistantTextFields: ["assistantTexts"],
} as const;
```

Rules:
- Keep the event names exactly as they are today unless live validation proves they are wrong.
- Do not scatter raw event names throughout the file after this change.
- The contract object should be easy for source-level tests to inspect.

### 2. Centralize payload extraction
File: extensions/sidequests-brain/src/index.ts

Add small helpers so payload handling is uniform and testable.

Add functions with behavior equivalent to:

```ts
function normalizePromptPayload(event: any): string | null
function normalizeAssistantPayload(event: any): string | null
function summarizeEventShape(event: any): string
```

Expected behavior:
- normalizePromptPayload:
  - Return null for missing, empty, or whitespace-only prompt content.
  - Accept string prompt directly.
  - For non-string prompt values, JSON.stringify with fallback to String(value) if serialization fails.
- normalizeAssistantPayload:
  - Return null for missing assistantTexts, empty arrays, or all-empty strings.
  - Join non-empty assistantTexts with "\n".
  - If assistantTexts is not an array but is a string, accept it as a compatibility fallback.
  - If assistantTexts is present in an unexpected non-string, non-array shape, stringify defensively.
- summarizeEventShape:
  - Return a compact summary of top-level event keys and the detected types for diagnostics.
  - Never log full prompt text or assistant content.

Do not introduce heavy abstractions. The helpers should remain local to the extension file.

### 3. Replace silent hook assumptions with contract-based registration
File: extensions/sidequests-brain/src/index.ts

Refactor the passive-ingestion registration blocks to use the contract constants and extraction helpers.

Requirements:
- Register user capture with OPENCLAW_EVENT_CONTRACT.userTurnEvent
- Register assistant capture with OPENCLAW_EVENT_CONTRACT.assistantTurnEvent
- Register auto-recall with OPENCLAW_EVENT_CONTRACT.preAgentEvent
- Only call brain.callTool("notify_turn", ...) when normalized content is non-null
- Keep failures non-fatal to the agent session

### 4. Add diagnostic logging for live contract validation
File: extensions/sidequests-brain/src/index.ts

Add concise console logging around hook registration and hook firing.

Required logs:
- On registration: one line indicating which event names were registered for capture and recall
- On hook fire success: one line per event showing event name and payload summary, not full content
- On hook fire skip: one line when the event fired but produced no usable content
- On hook error: one line with event name and a short reason

Constraints:
- Do not log full user prompts or assistant responses
- Do not throw on logging failures
- Keep logging concise enough that it is usable in OpenClaw gateway logs during manual validation

Suggested log style:

```ts
console.log(`[SideQuests Brain] Event ${eventName} fired (${summarizeEventShape(event)})`);
console.warn(`[SideQuests Brain] Event ${eventName} produced no usable content`);
console.warn(`[SideQuests Brain] Event ${eventName} failed: ${message}`);
```

### 5. Make fallback behavior explicit
File: extensions/sidequests-brain/src/index.ts

The B27 card requires explicit fallback behavior if an expected hook is unavailable or changes shape.

Implement this at the code-contract level, not by inventing undocumented OpenClaw APIs.

Required behavior:
- If llm_input fires without a usable prompt payload, skip notify_turn and log that the event fired with an unsupported or empty shape.
- If llm_output fires without a usable assistant payload, skip notify_turn and log the same.
- If before_agent_start fires without a usable prompt payload, return {} and log a skip.
- Do not attempt speculative alternate event names in code unless they are confirmed during live validation.
- The compatibility note must state exactly which event names and payload fields are expected, and what the fallback behavior is when the payload is present but unusable.

### 6. Add a compatibility note
Preferred location: extensions/sidequests-brain/src/index.ts as a short comment block above the contract constants.

Alternative: docs/openclaw-event-contract.md if the in-code note becomes too large.

The compatibility note must include:
- OpenClaw version validated against, if known from live testing
- Event names used
- Payload fields consumed
- Fallback behavior for empty or shape-mismatched payloads

Keep it short and factual.

### 7. Add regression tests for the passive-ingestion contract
Create file: tests/test_extension_ingestion_contract.py

Use the existing pattern in tests/test_extension_aliases.py and tests/test_b41_plugin_startup.py: inspect the extension source as text and assert that the expected contract elements exist.

Add tests that verify:
1. OPENCLAW_EVENT_CONTRACT exists in the source.
2. The contract includes llm_input, llm_output, and before_agent_start.
3. normalizePromptPayload exists.
4. normalizeAssistantPayload exists.
5. summarizeEventShape exists.
6. User capture registers using the contract constant, not a repeated raw string.
7. Assistant capture registers using the contract constant, not a repeated raw string.
8. Auto-recall registers using the contract constant, not a repeated raw string.
9. User capture still calls brain.callTool("notify_turn", ...) with role "user".
10. Assistant capture still calls brain.callTool("notify_turn", ...) with role "assistant".
11. Auto-recall still calls brain.callTool("current_truth", ...).
12. Diagnostic logging mentions event firing or skipped payloads.
13. Fallback behavior is explicit for unusable prompt payloads.
14. Fallback behavior is explicit for unusable assistant payloads.

Keep the tests resilient to formatting changes by checking for stable structural substrings rather than exact large blocks.

### 8. Extend nearby source-inspection tests only where useful
Files:
- tests/test_extension_aliases.py
- tests/test_b41_plugin_startup.py

Allowed changes:
- Add 1 or 2 targeted assertions if the new contract/logging blocks naturally belong with these files.
- Do not overload unrelated tests with B27-specific behavior.

Examples:
- tests/test_extension_aliases.py can keep alias-only concerns.
- tests/test_b41_plugin_startup.py can remain startup-focused unless one new assertion about startup registration logging fits cleanly.

### 9. Compile-check the extension after edits
Because there is no JS/TS unit test harness here, include a TypeScript compile check in validation.

Use:

```bash
npx tsc -p extensions/sidequests-brain/tsconfig.json --noEmit
```

Do not add package scripts for this card.

## Manual Validation Plan (Opus after Gemini)

This card cannot be fully closed by static edits alone. After Gemini finishes, Opus must validate against a live OpenClaw session.

Manual validation steps:
1. Install or load the SideQuests Brain extension in OpenClaw.
2. Start one agent session with the plugin enabled.
3. Send one user prompt and let the assistant answer once.
4. Confirm gateway/plugin logs show:
   - llm_input fired
   - llm_output fired
   - payload summaries were logged
5. Confirm the Brain receives two notify_turn calls with non-empty content.
6. Start a fresh agent session and confirm before_agent_start still issues a current_truth lookup when prompt length is sufficient.
7. If the observed event names or payload fields differ from the contract, update the contract constants and compatibility note before closing B27.

## Exact Commands For Validation

Run in this order:

1. `pytest tests/test_extension_ingestion_contract.py -q --no-header`
2. `pytest tests/test_extension_aliases.py tests/test_b41_plugin_startup.py -q --no-header`
3. `npx tsc -p extensions/sidequests-brain/tsconfig.json --noEmit`

If these pass, proceed to the live OpenClaw validation checklist above.

## Delegation Prompt (for Gemini)

Use exactly:

`gemini -p "Read B-27-openclaw-passive-ingestion-validation.md and implement exactly as specified. Read extensions/sidequests-brain/src/index.ts and the existing tests that inspect extension source first. Preserve current tool behavior. Do not invent undocumented OpenClaw APIs. Add only the smallest code and test changes needed to make the passive-ingestion contract explicit, logged, and regression-tested." --yolo 2>&1`

## Acceptance Checklist
- The extension defines an explicit passive-ingestion event contract instead of relying on scattered hardcoded assumptions.
- User capture, assistant capture, and auto-recall all use centralized payload extraction helpers.
- Live logs can show whether hooks fired and what payload shape was observed, without logging message content.
- Regression tests fail if event names or extraction helpers are removed or silently changed.
- The extension still forwards user and assistant turns through notify_turn and still uses current_truth before agent start.
- TypeScript compile check passes.
- Live OpenClaw validation confirms both user and assistant events fire with non-empty content, or the contract is updated to match reality before B27 is marked complete.

## Notes
- B29 should not start implementation until this card has passed both static validation and a live OpenClaw event check.
- If live validation reveals different event names or payload fields, treat that as the successful outcome of B27. The objective is a verified contract, not preserving the current guesses.