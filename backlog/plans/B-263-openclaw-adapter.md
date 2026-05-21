# B263 - OpenClaw Adapter Activation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the OpenClaw integration by adding `register_openclaw()`, implementing autoCapture/autoRecall behavior, and wiring the plugin to the Campy daemon.

**Architecture:** OpenClaw's plugin system reads `openclaw.plugin.json` from an extensions directory. `register_openclaw()` copies the existing config from `extensions/hippocampy/openclaw.plugin.json` to OpenClaw's extensions dir. The adapter connects to Campy via the REST API (`/api/v1/`) for simplicity.

**Tech Stack:** Python, JSON config, REST API client, existing detect.py/register.py patterns

---

### Task 1: Improve OpenClaw Detection

**Files:**
- Modify: `campy/cli/detect.py`
- Create: `tests/cli/test_detect_openclaw.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_detect_openclaw.py
from campy.cli.detect import detect_openclaw

def test_detect_openclaw_checks_path():
    """detect_openclaw should check for openclaw CLI in PATH."""
    result = detect_openclaw()
    assert isinstance(result, bool)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/cli/test_detect_openclaw.py -v`
Expected: PASS (function already exists, returns bool)

- [ ] **Step 3: Enhance detection to also check config directory**

Update `detect_openclaw()` in `campy/cli/detect.py`:

```python
def detect_openclaw() -> bool:
    """Check for OpenClaw CLI in PATH or config directory."""
    if shutil.which("openclaw") is not None:
        return True
    # Also check common config directory
    config_dirs = [
        os.path.expanduser("~/.openclaw"),
        os.path.expanduser("~/.config/openclaw"),
    ]
    return any(os.path.isdir(d) for d in config_dirs)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/cli/test_detect_openclaw.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/detect.py tests/cli/test_detect_openclaw.py
git commit -m "feat(B263): enhance OpenClaw detection with config directory check"
```

---

### Task 2: Implement register_openclaw()

**Files:**
- Create: `campy/cli/register_openclaw.py`
- Create: `tests/cli/test_register_openclaw.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_register_openclaw.py
import tempfile
from pathlib import Path

def test_register_openclaw_copies_plugin_config(tmp_path):
    """register_openclaw should copy plugin config to extensions dir."""
    from campy.cli.register_openclaw import register_openclaw
    
    # Use tmp_path as the extensions dir
    extensions_dir = tmp_path / "extensions"
    repo_root = Path(__file__).parent.parent.parent
    
    result = register_openclaw(repo_root=repo_root, extensions_dir=extensions_dir)
    assert result is True
    
    config_path = extensions_dir / "hippocampy" / "openclaw.plugin.json"
    assert config_path.exists()
    
    import json
    config = json.loads(config_path.read_text())
    assert config["id"] == "hippocampy"
    assert config["configSchema"]["properties"]["brainUrl"]["default"] == "http://127.0.0.1:7799"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_register_openclaw.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement register_openclaw.py**

```python
# campy/cli/register_openclaw.py
"""Register Campy with OpenClaw."""
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_openclaw_extensions_dir() -> Optional[Path]:
    """Find OpenClaw's extensions directory."""
    candidates = [
        Path.home() / ".openclaw" / "extensions",
        Path.home() / ".config" / "openclaw" / "extensions",
    ]
    for candidate in candidates:
        if candidate.parent.is_dir():
            return candidate
    # Default to first candidate
    return candidates[0]


def register_openclaw(
    repo_root: Path = None,
    extensions_dir: Path = None,
) -> bool:
    """Register Campy as an OpenClaw plugin.
    
    Copies extensions/hippocampy/openclaw.plugin.json to OpenClaw's
    extensions directory.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent
    
    source = repo_root / "extensions" / "hippocampy" / "openclaw.plugin.json"
    if not source.exists():
        logger.error(f"OpenClaw plugin config not found at {source}")
        return False
    
    if extensions_dir is None:
        extensions_dir = _find_openclaw_extensions_dir()
    
    target_dir = extensions_dir / "hippocampy"
    target_dir.mkdir(parents=True, exist_ok=True)
    
    target = target_dir / "openclaw.plugin.json"
    shutil.copy2(source, target)
    
    logger.info(f"OpenClaw plugin registered at {target}")
    return True
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/test_register_openclaw.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/register_openclaw.py tests/cli/test_register_openclaw.py
git commit -m "feat(B263): implement register_openclaw() plugin config installer"
```

---

### Task 3: Wire into CLI and Doctor

**Files:**
- Modify: `campy/cli/register.py`
- Modify: `campy/cli/main.py`
- Modify: `campy/cli/doctor.py`

- [ ] **Step 1: Import and expose in register.py**

Add to `campy/cli/register.py`:

```python
from campy.cli.register_openclaw import register_openclaw
```

- [ ] **Step 2: Add openclaw target to setup command in main.py**

In the `setup()` function in `campy/cli/main.py`, add in the target-specific block:

```python
elif target == "openclaw":
    from campy.cli.register_openclaw import register_openclaw
    results["OpenClaw"] = register_openclaw()
```

And in the auto-detect block:

```python
if clients.get("openclaw"):
    console.print("[green]Detected OpenClaw. Registering...[/green]")
    from campy.cli.register_openclaw import register_openclaw
    results["OpenClaw"] = register_openclaw()
```

- [ ] **Step 3: Add OpenClaw check to doctor**

In `campy/cli/doctor.py`, add to `check_plugin_status`:

```python
if clients.get("openclaw"):
    from campy.cli.register_openclaw import _find_openclaw_extensions_dir
    ext_dir = _find_openclaw_extensions_dir()
    plugin_config = ext_dir / "hippocampy" / "openclaw.plugin.json"
    if plugin_config.exists():
        self._pass("OpenClaw plugin registered")
    else:
        self._fail("OpenClaw plugin NOT registered — run: campy setup --target=openclaw")
        all_ok = False
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/ -v -k "openclaw or doctor"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/register.py campy/cli/main.py campy/cli/doctor.py
git commit -m "feat(B263): wire OpenClaw into CLI setup and doctor"
```

---

### Task 4: Verify Plugin Config Correctness

**Files:**
- Modify: `tests/cli/test_register_openclaw.py`

- [ ] **Step 1: Test plugin config has all required fields**

```python
import json
from pathlib import Path

def test_openclaw_plugin_config_valid():
    """openclaw.plugin.json should have all required fields."""
    repo_root = Path(__file__).parent.parent.parent
    config_path = repo_root / "extensions" / "hippocampy" / "openclaw.plugin.json"
    assert config_path.exists()
    
    config = json.loads(config_path.read_text())
    assert config["id"] == "hippocampy"
    assert config["kind"] == "memory"
    assert "autoCapture" in config["configSchema"]["properties"]
    assert "autoRecall" in config["configSchema"]["properties"]
    assert config["configSchema"]["properties"]["autoCapture"]["default"] is True
    assert config["configSchema"]["properties"]["autoRecall"]["default"] is True
```

- [ ] **Step 2: Run test**

Run: `pytest tests/cli/test_register_openclaw.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/cli/test_register_openclaw.py
git commit -m "test(B263): verify OpenClaw plugin config correctness"
```
