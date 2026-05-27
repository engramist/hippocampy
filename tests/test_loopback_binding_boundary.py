from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("campy", "mcp_engine", "adapters", "web")
ALLOWED_PHRASES = ("never 0.0.0.0", "NEVER 0.0.0.0")


def iter_production_python_files() -> list[Path]:
    """Return the Python files that count as production code for this boundary."""

    files: list[Path] = []

    for relative_root in PRODUCTION_ROOTS:
        base = ROOT / relative_root
        if not base.exists():
            continue

        for path in base.rglob("*.py"):
            if should_skip(path):
                continue
            files.append(path)

    root_entry = ROOT / "brain_daemon.py"
    if root_entry.exists() and not should_skip(root_entry):
        files.append(root_entry)

    return sorted(dict.fromkeys(files))


def should_skip(path: Path) -> bool:
    """Skip non-production locations that are outside the boundary."""

    skipped_names = {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "env",
        "tests",
        "test",
        "docs",
    }

    return any(part.startswith(".") or part in skipped_names for part in path.parts)


def test_production_code_does_not_bind_to_0_0_0_0() -> None:
    """Keep local status surfaces loopback-only unless an explicit allowlist says otherwise."""

    violations: list[str] = []

    for path in iter_production_python_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "0.0.0.0" not in line:
                continue

            if any(phrase in line for phrase in ALLOWED_PHRASES):
                continue

            violations.append(f"{path}:{lineno}: {line.strip()}")

    assert not violations, (
        "Production code contains a 0.0.0.0 literal outside the tiny allowlist.\n"
        "Keep network/status surfaces bound to 127.0.0.1 only.\n"
        + "\n".join(violations)
    )
