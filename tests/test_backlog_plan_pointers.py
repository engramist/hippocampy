"""Test the backlog `Plan:` pointer guard (scripts/check_backlog_plan_pointers.py)."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_backlog_plan_pointers.py")


def _run(root: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)]
    if root is not None:
        cmd += ["--root", str(root)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _card(root: Path, name: str, plan_line: str) -> None:
    (root / "backlog").mkdir(parents=True, exist_ok=True)
    (root / "backlog" / f"{name}.md").write_text(f"# {name}\n\n{plan_line}\n", encoding="utf-8")


def test_real_backlog_has_no_dangling_plan_pointers():
    """The repo's own backlog must not point at plan files that don't exist."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_plan_file_fails(tmp_path):
    """A pointer at a nonexistent plan file is reported and exits non-zero."""
    _card(tmp_path, "B901", "Plan: backlog/plans/B-901-missing.md")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "B901.md" in result.stdout
    assert "B-901-missing.md" in result.stdout


def test_existing_plan_file_passes(tmp_path):
    """A pointer at a plan file that exists is fine."""
    _card(tmp_path, "B900", "Plan: backlog/plans/B-900-real.md")
    plans = tmp_path / "backlog" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "B-900-real.md").write_text("# plan\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_inline_and_none_yet_plans_are_ignored(tmp_path):
    """The self-contained and no-plan-yet styles must not trip the check."""
    _card(tmp_path, "B902", "Plan: (inline — this card is self-contained)")
    _card(tmp_path, "B903", "Plan: none yet — needs a design pass first.")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_plan_path_without_backlog_prefix_is_resolved(tmp_path):
    """`plans/B-x.md` (no `backlog/` prefix) still resolves under backlog/."""
    _card(tmp_path, "B904", "Plan: `plans/B-904-no-prefix.md`")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "B-904-no-prefix.md" in result.stdout
