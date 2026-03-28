# SideQuests Brain Installation Instructions

## Quick Answer

Yes, for now you should clone the full repository on the test machine.

Why:
- PyPI publishing is still deferred.
- The installer currently runs from source and expects repository files to be present.

## Prerequisites

- macOS (recommended path)
- Python 3.12 or 3.13
- Git
- Optional but recommended: Codex Desktop installed before running install (so it is auto-detected)

Notes:
- Avoid Python 3.14 for now due to Kuzu build issues in clean environments.

## Install Steps (Recommended Test Path)

1. Clone the repository:

```bash
git clone git@github.com:djs54/sidequests-brain.git
cd sidequests-brain
```

2. Create a local bootstrap virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

3. Run the guided installer:

```bash
sidequests install
```

4. Choose your provider when prompted:
- Option 1: Ollama local (recommended for testing)
- Option 2: BYOK (OpenAI / Anthropic / Google)

5. Verify installation health:

```bash
sidequests status
```

If all checks are green, install is complete.

## Codex Desktop Notes

Codex Desktop is now included in installer auto-detection and registration.

On macOS, installer registration targets one of these config paths:
- ~/Library/Application Support/Codex/config.toml
- ~/Library/Application Support/com.openai.codex/config.toml
- fallback: ~/.codex/config.toml

After install:
1. Restart Codex Desktop.
2. Confirm SideQuests tools are visible/available in Codex.

## What the Installer Sets Up

- Creates runtime environment under ~/.sidequests
- Writes config at ~/.sidequests/config.toml
- Initializes Kuzu DB at ~/.sidequests/brain.db
- Configures daemon launch agent on macOS
- Registers detected AI clients (including Codex Desktop)
- Runs final smoke checks

## Troubleshooting

1. Check health:

```bash
sidequests status
```

2. Check daemon logs:

```bash
cat ~/.sidequests/daemon.log
```

3. Re-run installer safely (idempotent):

```bash
sidequests install
```
