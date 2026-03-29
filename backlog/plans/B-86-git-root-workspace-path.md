# B86 Plan — Use Git Root Instead of os.getcwd() for Workspace Path

Card: B86
Priority: LOW
Finding: R2-AD2
Depends on: None

## Summary

Replace `os.getcwd()` with git root detection in all adapter workspace_path defaults.

## Technical Approach

Add a shared helper (or inline in each adapter):

```python
import subprocess

def _detect_workspace_root() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return os.getcwd()
```

Replace `ctx.setdefault("workspace_path", os.getcwd())` with `ctx.setdefault("workspace_path", _detect_workspace_root())`.

## Concrete File Changes

### 1–5. All 5 adapters (`adapters/*/adapter.py`)
- Add `_detect_workspace_root()` helper (or import from shared utils)
- Replace `os.getcwd()` default with `_detect_workspace_root()`

## Test Updates

- Add test: mock subprocess to return git root, verify workspace_path uses it
- Add test: mock subprocess failure, verify fallback to cwd

## Acceptance Criteria

- Adapters use git root when available
- Fallback to cwd when not in a git repo
- `pytest tests/test_adapters.py -q` passes

## Validation Commands

```bash
rg "getcwd" adapters/  # should be minimal or gone
pytest tests/test_adapters.py -q
```

## Risks

- `subprocess.run(["git", ...])` adds ~10ms startup per adapter. One-time cost.
- Environments without git installed will always fall back to cwd — same behavior as current.
