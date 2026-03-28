# B28: Fix Tool Binding in OpenClaw Agent Sessions

**Status:** In Progress  
**Priority:** P0 — blocks all active memory features  
**Date:** 2026-03-22  

---

## Root Cause Analysis

Three issues identified from log analysis:

### Issue 1: Tools not in tools.profile allowlist
The `tools.profile = "coding"` allowlist in openclaw config contains `memory_search` and `memory_get`
(memory-core tool names). Our plugin registers `memory_recall`, `memory_store`, `memory_search_analogies`,
`memory_status`, `memory_open_loops`. None of these are in the allowlist.

**Fix:** Update `openclaw.json` tools.profile to include our tool names.

### Issue 2: Plugin ID mismatch
`package.json` name is `@sidequests/openclaw-brain`. OpenClaw infers plugin ID from the last segment
of the package name → `openclaw-brain`. But `openclaw.plugin.json` declares `id: "sidequests-brain"`.
This mismatch may prevent the plugin from loading correctly.

**Fix:** Change `package.json` name to `@sidequests/sidequests-brain` to match the manifest ID.

### Issue 3: Plugin register() never fires
No `[SideQuests Brain] Connected` log entry anywhere — the service registered in `register()` never
starts. Either the plugin fails to load due to Issue 2, or the TypeScript compilation is stale.

**Fix:** After fixing Issue 2, reinstall the plugin so the compiled output is fresh.

---

## Changes Required

### 1. `extensions/sidequests-brain/package.json`
Change:
```json
"name": "@sidequests/openclaw-brain"
```
To:
```json
"name": "@sidequests/sidequests-brain"
```

### 2. `~/.openclaw/openclaw.json` — tools profile
The `tools.profile` is `"coding"`. We need to add our tool names to the allowed list.
Look for `tools` section and add an allowlist entry, OR switch to a custom profile.

Current config has:
```json
"tools": {
  "profile": "coding",
  "web": { "search": { "provider": "perplexity" } }
}
```

Add:
```json
"tools": {
  "profile": "coding",
  "web": { "search": { "provider": "perplexity" } },
  "allow": ["memory_recall", "memory_store", "memory_search_analogies", "memory_status", "memory_open_loops"]
}
```

### 3. Reinstall plugin after package.json fix
```bash
cd ~/Desktop/GitProjects/sidequests-brain
openclaw plugins install extensions/sidequests-brain --force
```

### 4. Verify
After gateway restart, check logs for:
- No more "plugin id mismatch" warning
- `[SideQuests Brain] Connected to Brain Daemon` message
- No more "unknown entries" for our tool names

---

## Test Plan
1. Start a new session
2. Ask: "use memory_recall to search for 'MCP'"  
3. Should return results from Brain, not "Tool not found"
4. Check gateway logs — no mismatch warnings
