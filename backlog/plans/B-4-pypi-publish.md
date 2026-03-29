# B-4-pypi-publish — Publish to PyPI

**Card:** B4 | **Priority:** P2 | **Depends on:** B1 (setup CLI complete)

## Summary
Prepare and publish `sidequests-brain` to PyPI, making it installable via `pip install sidequests-brain` and `uvx sidequests-brain`. This is the standard distribution channel for Python packages and enables one-command setup.

## Technical Approach

### pyproject.toml Structure
```toml
[project]
name = "sidequests-brain"
version = "0.1.0"  # read from __version__ in __init__.py
description = "Local AI memory system with gated consolidation loop and graph-native Kùzu database"
readme = "README.md"
license = { text = "Apache-2.0" }  # or appropriate license
authors = [{ name = "...", email = "..." }]
keywords = ["ai", "memory", "graph-database", "mcp"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]

requires-python = ">=3.12,<3.14"
dependencies = [
    "kuzu==0.11.3",
    "sentence-transformers>=2.2.0",
    "spacy>=3.7.0",
    "typer>=0.9.0",
    "httpx>=0.24.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "black", "ruff"]
ollama = ["ollama-python>=0.1.0"]  # optional LLM provider

[project.scripts]
sidequests = "sidequests.cli.main:app"

[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"
```

### Version Management
- Read version from `sidequests/__init__.py` in pyproject.toml using dynamic versioning
- Set version to 0.1.0-rc1 for initial publication

### Distribution Artifacts
- Build wheel: `python -m build --wheel`
- Build sdist: `python -m build --sdist`
- Both must pass `twine check`

### PyPI Credentials
- Use token-based auth (not password)
- Store token in `~/.pypirc` or environment variable
- Test: `twine upload dist/* --repository=testpypi` first

### Testing Installation
- In clean venv: `pip install dist/sidequests_brain-0.1.0-py3-none-any.whl`
- Verify `sidequests --help` works
- Verify `sidequests setup --help` shows setup command
- Test `uvx sidequests-brain setup` in fresh environment

## Files to Create/Modify

- `pyproject.toml` — complete with all metadata and entry points
- `sidequests/__init__.py` — add `__version__ = "0.1.0"`
- `README.md` — update with PyPI summary and installation instructions
- `.github/workflows/release.yml` — CI/CD for building and publishing
- `LICENSE` — if not already present

## Acceptance Criteria

1. `pyproject.toml` has all required fields (name, version, description, readme, dependencies, entry points)
2. `python -m build` generates wheel and sdist without warnings or errors
3. `twine check` passes on both wheel and sdist
4. `pip install dist/sidequests_brain-*.whl` works in clean venv
5. `uvx sidequests-brain setup --help` runs end-to-end
6. Package publishes to PyPI and is searchable within 5 minutes
7. Python 3.14+ limitation is documented in README

## Security Notes

- Only publish after provisional patent is filed (per IP protection policy in CLAUDE.md)
- Verify no sensitive credentials are in git history
- Check for no hardcoded API keys or paths in code
