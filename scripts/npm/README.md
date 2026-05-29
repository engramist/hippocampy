# HippoCampy npm Wrapper

This package is a thin wrapper around the main HippoCampy installer.

## What It Does

- Downloads and runs `scripts/install.sh` from the main HippoCampy repository
- Installs the Python engine through the supported installer path
- Runs `campy setup` so detected AI agents are registered automatically

## Usage

```bash
npx hippocampy
```

Or install globally:

```bash
npm install -g hippocampy
hippocampy
```

## Notes

- Windows is not supported yet; use WSL.
- The real installation logic lives in `scripts/install.sh`.
- If installation fails, fall back to `pip install hippocampy && campy setup`.