# OpenClaw Event Contract (SideQuests Brain)

Validated and locked on: 2026-03-27

## Scope
This document defines the contract between the OpenClaw plugin API and the SideQuests Brain memory extension.

## Events

### 1. User Turn Capture
- **Event Name:** `llm_input`
- **Expected Payload:** `{ prompt: string }`
- **Normalization:**
  - If `prompt` is a string, use it.
  - If `prompt` is an object, `JSON.stringify` it.
  - Trim whitespace.
  - If missing or empty after trim, skip capture and log a warning.
- **SideQuests Tool:** `notify_turn` (role: `user`)

### 2. Assistant Turn Capture
- **Event Name:** `llm_output`
- **Expected Payload:** `{ assistantTexts: string[] }`
- **Normalization:**
  - If `assistantTexts` is an array, join with `\n`.
  - If `assistantTexts` is a string (fallback), use it.
  - If `assistantTexts` is an object, `JSON.stringify` it.
  - Trim whitespace.
  - If missing or empty after trim, skip capture and log a warning.
- **SideQuests Tool:** `notify_turn` (role: `assistant`)

### 3. Auto-Recall
- **Event Name:** `before_agent_start`
- **Expected Payload:** `{ prompt: string }`
- **Normalization:** Same as `llm_input`.
- **SideQuests Tool:** `current_truth`
- **Min Length:** Query must be at least 5 characters.
- **Fallback:** Returns `{}` if query is too short or lookup fails.

## Diagnostics
The extension logs to the console when events fire. Logs include:
- Registration confirmation
- Event fire with payload shape summary (e.g., `{ prompt:string }`)
- Warning for missing/empty content
- Error message if tool call fails
- **No full content is logged.**
