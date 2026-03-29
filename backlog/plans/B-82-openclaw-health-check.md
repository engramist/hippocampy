# B82 Plan — Add Periodic Health Check to OpenClaw Extension

Card: B82
Priority: MEDIUM
Finding: R2-OC2
Depends on: None

## Summary

Add a `setInterval`-based daemon health check to the OpenClaw extension that detects daemon recovery/failure.

## Technical Approach

```typescript
const HEALTH_CHECK_INTERVAL = 30_000; // 30 seconds

setInterval(async () => {
  try {
    const resp = await callBrainDaemon("health_check", {});
    if (!isOnline) {
      logger.info("Brain Daemon recovered — transitioning to online");
      isOnline = true;
    }
  } catch {
    if (isOnline) {
      logger.warn("Brain Daemon unreachable — transitioning to offline");
      isOnline = false;
    }
  }
}, HEALTH_CHECK_INTERVAL);
```

## Concrete File Changes

### 1. `extensions/sidequests-brain/src/index.ts`
- Add health check interval after initial `registerService.start()`
- Track online/offline state
- Log transitions
- Clear interval on plugin deactivation/dispose

## Test Updates

- Update `tests/test_b41_plugin_startup.py` if it tests startup behavior
- Add test for health check state transitions (mock daemon responses)

## Acceptance Criteria

- Health check runs every 30s
- Online→offline and offline→online transitions detected and logged
- Interval cleared on plugin dispose
- Existing tests pass

## Validation Commands

```bash
cd extensions/sidequests-brain && npm run build
pytest tests/test_b41_plugin_startup.py -q
```

## Risks

- 30s interval may be too frequent for resource-constrained environments. Make configurable.
- Health check should be lightweight (not a full tool call). Use a simple ping or status endpoint.
