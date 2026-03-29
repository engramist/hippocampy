# B-22-openclaw-plugins-allow-warning — OpenClaw Extension: plugins.allow Warning

**Card:** B22 | **Priority:** P7 | **Depends on:** None (extension config)

## Summary
Suppress or address the `plugins.allow` warning that appears during OpenClaw plugin installation. Improves user experience by removing noise from setup flow.

## Technical Approach

- Identify root cause: OpenClaw warns about plugin safety/allowlist
- Solution approach: either
  - Implement auto-approving behavior in install script, or
  - Suppress warning via config flag, or
  - Provide clear guidance to user on why warning exists
- Update `sidequests setup --target openclaw` to handle this gracefully

## Files to Create/Modify

- `sidequests/cli/register_openclaw.py` — handle plugins.allow dialog
- Update install docs with warning explanation

## Acceptance Criteria

1. `sidequests setup --target openclaw` completes without plugins.allow error blocking it
2. Warning is either suppressed or user is given clear, actionable guidance
3. No security downgrade (don't bypass legitimate safety mechanisms)

## Notes

- Low-effort card: likely 1-2 line config or documentation fix
