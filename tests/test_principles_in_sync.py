"""B497: the principles have one source (PRINCIPLES.md). CLAUDE.md and GEMINI.md
import it with @PRINCIPLES.md; AGENTS.md and the Copilot instructions (no import
support) carry verbatim copies between markers. Fail if any copy drifts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- principles:begin (copy of PRINCIPLES.md; edit that file) -->"
END = "<!-- principles:end -->"


def _source_body() -> str:
    text = (ROOT / "PRINCIPLES.md").read_text()
    body = text.split("-->", 1)[1]  # after the header comment
    return body.strip()


def _copy(path: str) -> str:
    text = (ROOT / path).read_text()
    assert BEGIN in text and END in text, f"{path}: principles markers missing"
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip()


def test_copies_match_source():
    src = _source_body()
    assert "The benchmark score is the measure" in src
    for path in ("AGENTS.md", ".github/copilot-instructions.md"):
        assert _copy(path) == src, f"{path} principles differ from PRINCIPLES.md"


def test_claude_and_gemini_import_the_source():
    for path in ("CLAUDE.md", "GEMINI.md"):
        head = "\n".join((ROOT / path).read_text().splitlines()[:8])
        assert "@PRINCIPLES.md" in head, f"{path} must import @PRINCIPLES.md near the top"
