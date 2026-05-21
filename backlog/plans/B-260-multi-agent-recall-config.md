# B260 - Codex, Gemini CLI, and VS Code Recall Config

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure recall behavior for Codex, Gemini CLI, and VS Code using each agent's native configuration mechanism.

**Architecture:** Codex gets an updated memory skill at `~/.codex/skills/campy-memory/SKILL.md`. Gemini CLI gets actual MCP registration (currently a no-op) plus `GEMINI.md` recall instructions. VS Code gets `.github/copilot-instructions.md` content. All derive from the same session-start protocol adapted per agent.

**Tech Stack:** Python, TOML (Codex config), Markdown (skill/instruction files), JSON (VS Code MCP config)

---

### Task 1: Create Universal Memory Skill Template

**Files:**
- Create: `campy/data/campy-memory/SKILL.md`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_recall_config.py
from pathlib import Path
from importlib import resources

def test_universal_skill_exists():
    """Universal memory skill template should exist in campy.data."""
    skill_path = Path("campy/data/campy-memory/SKILL.md")
    assert skill_path.exists()
    content = skill_path.read_text()
    assert "memory_decision" in content
    assert "MUST" in content or "ALWAYS" in content
    assert "current_truth" in content
    assert "compile_context" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_recall_config.py::test_universal_skill_exists -v`
Expected: FAIL — file doesn't exist

- [ ] **Step 3: Create the universal skill**

Create directory and file:

```bash
mkdir -p campy/data/campy-memory
```

Write `campy/data/campy-memory/SKILL.md`:

```markdown
# Campy Memory — Session Recall Protocol

You have access to a persistent AI memory system called Campy (HippoCampy). It remembers decisions, constraints, plans, and context across all your sessions.

## At Session Start — MANDATORY

**BEFORE doing any work, you MUST follow this protocol:**

1. Call `memory_decision` with the user's first message:
   ```
   memory_decision(query="<user's first message>", session_id="<session>")
   ```

2. Call the recommended tool from Step 1's response:
   - `current_truth` for single-topic recall
   - `compile_context` for broad context needs
   - `recall_procedures` for process questions
   - `recall_relevant_lessons` for past outcomes

3. If continuing existing work, call `diff_since` to see recent changes:
   ```
   diff_since(since_iso="<24 hours ago ISO>")
   ```

4. Present findings to the user before starting work.

## During the Session — Recall Triggers

| When You See This | You MUST Call This |
|---|---|
| Questions about past decisions | `current_truth(query="<topic>")` |
| Architecture or design questions | `current_truth(query="<topic>")` |
| Multi-entity or broad queries | `compile_context(query="<topic>")` |
| "Why did we choose X?" | `current_truth(query="decision about X")` |
| Process or procedure questions | `recall_procedures(query="<topic>")` |
| "What went wrong last time?" | `recall_relevant_lessons(query="<topic>")` |
| Not sure which tool | `memory_decision(query="<question>")` |

## After Every Response — MANDATORY

**AFTER every response, you MUST call `notify_turn`:**

```
notify_turn(role="assistant", content="<your full response>", session_id="<session>")
```

This is how the Brain captures knowledge. Never skip it.

## Available Tools

| Tool | Purpose |
|---|---|
| `memory_decision` | Ask the Brain which recall tool to use |
| `current_truth` | Semantic search for specific facts |
| `compile_context` | Multi-source bundle compilation |
| `recall_procedures` | Process and procedure knowledge |
| `recall_relevant_lessons` | Past outcomes and lessons learned |
| `reconstruct_timeline` | Temporal view of events |
| `diff_since` | Changes since a timestamp |
| `analogical_search` | Cross-project pattern matching |
| `notify_turn` | Capture your response in memory |
| `ingest_data` | Ingest files/data into memory |
```

- [ ] **Step 4: Run test**

Run: `pytest tests/cli/test_recall_config.py::test_universal_skill_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/data/campy-memory/SKILL.md tests/cli/test_recall_config.py
git commit -m "feat(B260): create universal memory skill template"
```

---

### Task 2: Update Codex Registration

**Files:**
- Modify: `campy/cli/register.py` (the `install_codex_memory_skill` and `register_codex` functions)

- [ ] **Step 1: Write the failing test**

Add to `tests/cli/test_recall_config.py`:

```python
import tempfile
from unittest.mock import patch
from pathlib import Path

def test_codex_skill_install_uses_universal_template(tmp_path):
    """install_codex_memory_skill should use the universal campy-memory skill."""
    from campy.cli.register import install_codex_memory_skill
    
    # Mock home dir so we don't write to real ~/.codex
    with patch("campy.cli.register.Path.home", return_value=tmp_path):
        repo_root = Path(__file__).parent.parent.parent
        result = install_codex_memory_skill(repo_root)
    
    assert result is not None
    content = result.read_text()
    assert "memory_decision" in content
    assert "MUST" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_recall_config.py::test_codex_skill_install_uses_universal_template -v`
Expected: FAIL or PASS depending on whether current skill has "memory_decision"

- [ ] **Step 3: Update install_codex_memory_skill**

In `campy/cli/register.py`, update the `install_codex_memory_skill` function to prefer the `campy-memory` skill:

```python
def install_codex_memory_skill(project_root: Path) -> Path | None:
    """Install the universal Campy memory skill for Codex."""
    # Priority: campy-memory universal skill > legacy skill
    source_candidates = [
        project_root / "campy" / "data" / "campy-memory" / "SKILL.md",
        project_root / "skills" / PRIMARY_SKILL_NAME / "SKILL.md",
    ]
    
    source_text = None
    for candidate in source_candidates:
        if candidate.exists():
            source_text = candidate.read_text()
            break
    
    if source_text is None:
        # Try importlib.resources fallback
        try:
            source_text = (
                resources.files("campy.data")
                .joinpath("campy-memory", "SKILL.md")
                .read_text()
            )
        except Exception:
            return None
    
    target = Path.home() / ".codex" / "skills" / "campy-memory" / "SKILL.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    
    if target.exists() and target.read_text() != source_text:
        target = target.with_suffix(target.suffix + ".new")
    
    target.write_text(source_text)
    return target
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/test_recall_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/register.py tests/cli/test_recall_config.py
git commit -m "feat(B260): update Codex registration to use universal memory skill"
```

---

### Task 3: Fix Gemini CLI Registration (Currently a No-Op)

**Files:**
- Modify: `campy/cli/register.py` (the `register_gemini_cli` function)

- [ ] **Step 1: Write the failing test**

Add to `tests/cli/test_recall_config.py`:

```python
def test_gemini_register_does_work():
    """register_gemini_cli should do more than just return True."""
    import inspect
    from campy.cli.register import register_gemini_cli
    source = inspect.getsource(register_gemini_cli)
    # Should contain actual registration logic, not just "return True"
    assert "GEMINI.md" in source or "gemini" in source.lower()
    assert len(source.split("\n")) > 5  # More than a trivial function
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_recall_config.py::test_gemini_register_does_work -v`
Expected: FAIL — current function is just `return True`

- [ ] **Step 3: Implement actual Gemini CLI registration**

Replace the `register_gemini_cli` function in `campy/cli/register.py`:

```python
def register_gemini_cli(adapter_path: str) -> bool:
    """Register Campy with Gemini CLI via GEMINI.md instructions."""
    try:
        repo_root = _repo_root_for_adapter(adapter_path)
        
        # Install universal memory skill content into GEMINI.md
        skill_source = repo_root / "campy" / "data" / "campy-memory" / "SKILL.md"
        if not skill_source.exists():
            logging.warning("Universal memory skill not found for Gemini CLI")
            return True  # Non-fatal — MCP server still works
        
        gemini_md = repo_root / "GEMINI.md"
        skill_content = skill_source.read_text()
        
        # Wrap in a Campy section
        campy_section = (
            "\n\n## Campy Memory Integration\n\n"
            "The Campy MCP server provides persistent AI memory. "
            "Follow the recall protocol below.\n\n"
            + skill_content
        )
        
        marker_start = "<!-- CAMPY-MEMORY-START -->"
        marker_end = "<!-- CAMPY-MEMORY-END -->"
        
        if gemini_md.exists():
            existing = gemini_md.read_text()
            if marker_start in existing:
                # Replace existing section
                import re
                pattern = re.compile(
                    f"{re.escape(marker_start)}.*?{re.escape(marker_end)}",
                    re.DOTALL,
                )
                updated = pattern.sub(
                    f"{marker_start}\n{campy_section}\n{marker_end}",
                    existing,
                )
            else:
                updated = existing + f"\n{marker_start}\n{campy_section}\n{marker_end}\n"
        else:
            updated = f"# Gemini CLI Instructions\n\n{marker_start}\n{campy_section}\n{marker_end}\n"
        
        gemini_md.write_text(updated)
        logging.info(f"Gemini CLI recall instructions written to {gemini_md}")
        return True
    except Exception as e:
        logging.error(f"Failed to register Gemini CLI: {e}")
        return False
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/test_recall_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/register.py tests/cli/test_recall_config.py
git commit -m "feat(B260): implement actual Gemini CLI registration with recall instructions"
```

---

### Task 4: Add VS Code Recall Instructions

**Files:**
- Modify: `campy/cli/register.py` (the `register_vscode` function)

- [ ] **Step 1: Write the failing test**

Add to `tests/cli/test_recall_config.py`:

```python
def test_vscode_register_adds_instructions(tmp_path):
    """register_vscode should add recall instructions to copilot-instructions."""
    from campy.cli.register import register_vscode
    
    # Create a mock .github/copilot-instructions.md
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    instructions = github_dir / "copilot-instructions.md"
    instructions.write_text("# Copilot Instructions\n\nExisting content.\n")
    
    # Mock the MCP config path to tmp_path
    mcp_config = tmp_path / "mcp.json"
    adapter_path = str(Path(__file__).parent.parent.parent / "adapters" / "codex" / "adapter.py")
    
    result = register_vscode(adapter_path, config_path=str(mcp_config))
    assert result is True
```

- [ ] **Step 2: Run test**

Run: `pytest tests/cli/test_recall_config.py::test_vscode_register_adds_instructions -v`
Expected: PASS (register_vscode already works for MCP config)

- [ ] **Step 3: Add copilot-instructions integration**

Add a helper function to `register.py` that's called from `register_vscode`:

```python
def _add_copilot_recall_instructions(repo_root: Path) -> None:
    """Add Campy recall instructions to .github/copilot-instructions.md."""
    instructions_path = repo_root / ".github" / "copilot-instructions.md"
    
    skill_source = repo_root / "campy" / "data" / "campy-memory" / "SKILL.md"
    if not skill_source.exists():
        return
    
    marker_start = "<!-- CAMPY-MEMORY-START -->"
    marker_end = "<!-- CAMPY-MEMORY-END -->"
    
    skill_content = skill_source.read_text()
    campy_block = f"{marker_start}\n## Campy Memory\n\n{skill_content}\n{marker_end}"
    
    if instructions_path.exists():
        existing = instructions_path.read_text()
        if marker_start in existing:
            import re
            pattern = re.compile(f"{re.escape(marker_start)}.*?{re.escape(marker_end)}", re.DOTALL)
            updated = pattern.sub(campy_block, existing)
        else:
            updated = existing + "\n\n" + campy_block + "\n"
        instructions_path.write_text(updated)
    # Don't create the file if .github/ doesn't exist — not our responsibility
```

Call from `register_vscode`:

```python
def register_vscode(adapter_path: str, config_path: str | None = None) -> bool:
    # ... existing MCP config logic ...
    
    # Also add recall instructions to copilot-instructions.md if .github exists
    repo_root = _repo_root_for_adapter(adapter_path)
    if (repo_root / ".github").is_dir():
        _add_copilot_recall_instructions(repo_root)
    
    return True
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/cli/test_recall_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/register.py tests/cli/test_recall_config.py
git commit -m "feat(B260): add VS Code copilot-instructions.md recall integration"
```

---

### Task 5: Verification

- [ ] **Step 1: Verify all 3 agents get recall config**

```bash
pytest tests/cli/test_recall_config.py -v
```
Expected: All tests PASS

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat(B260): complete — Codex, Gemini CLI, VS Code recall config"
```
