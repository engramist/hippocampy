# Campy Release Publish Checklist

## Pre-Release

- [ ] Version bumped in `pyproject.toml` (no `-rc` suffix for release)
- [ ] CHANGELOG updated (if maintained)
- [ ] All tests pass: `pytest tests/ -q`
- [ ] Public release audit passes: `bash scripts/audit_public_release.sh --release`
- [ ] No private data in wheel: `pytest tests/test_public_release_manifest.py -v`

## Build

```bash
bash scripts/release_build.sh
```

This cleans `dist/`, runs the audit, builds wheel+sdist, and runs `twine check`.

## TestPyPI Dry Run

```bash
bash scripts/release_build.sh --testpypi
```

Then test install from TestPyPI:

```bash
python -m venv /tmp/campy-test
/tmp/campy-test/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ hippocampy
/tmp/campy-test/bin/campy --help
/tmp/campy-test/bin/campy doctor --help
```

## Publish to PyPI

```bash
bash scripts/release_build.sh --publish
```

Requires typing "publish" to confirm. **PyPI releases cannot be overwritten** — if something is wrong, publish a new version.

## Post-Publish Verification

```bash
pip install hippocampy
campy --help
campy doctor
```

## Rollback

PyPI does not allow overwriting files. If a bad release is published:
1. Yank the release: `pip install twine && twine yank hippocampy==X.Y.Z`
2. Publish a fixed version with incremented patch number
3. Yanked versions still install with `pip install hippocampy==X.Y.Z` but won't be the default

## Patent-Pending Notice

Ensure `README.md` and package description include patent-pending notice per B233 guidelines.
