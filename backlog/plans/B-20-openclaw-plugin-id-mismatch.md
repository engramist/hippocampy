# B-20-openclaw-plugin-id-mismatch — OpenClaw Extension: Plugin ID Mismatch

**Card:** B20 | **Priority:** P7 | **Depends on:** None (extension bug)

## Summary
Fix plugin ID mismatch in OpenClaw extension registration. Ensure extension identifier matches across config, manifest, and runtime.

## Technical Approach

- Identify current mismatch in `extensions/sidequests-brain/package.json` or manifest
- Align plugin ID consistently: "sidequests-brain" everywhere
- Verify OpenClaw can load extension by ID without ambiguity
- Test: `openclaw plugins list | grep sidequests`

## Files to Create/Modify

- `extensions/sidequests-brain/package.json` — plugin ID alignment
- `extensions/sidequests-brain/.claude-plugin/plugin.json` — ID consistency
- Documentation of correct ID scheme

## Acceptance Criteria

1. Plugin ID is "sidequests-brain" consistently across all config files
2. `openclaw plugins list` shows extension with correct ID
3. `openclaw plugins install --link extensions/sidequests-brain` succeeds
4. No ID collision warnings in OpenClaw logs

## Notes

- Minimal change, likely 1-2 line fix
