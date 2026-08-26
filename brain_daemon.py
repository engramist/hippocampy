"""
brain_daemon.py — deprecated re-export shim.

The real implementation lives in `campy/brain_daemon.py` (import as
`campy.brain_daemon`). This file used to be an independent, drifted copy of
that module — see `backlog/B365.md` for the full incident: a connection-
handling fix (B362) landed here while the actual shipped/launchd-preferred
entry point, `campy/brain_daemon.py`, stayed unpatched for a full day,
because nothing made it obvious the two files were different code.

This file must never grow its own logic again. Every symbol below is a
straight re-export of `campy.brain_daemon`.

Kept as a file at this path only because several CLI code paths still
expect `brain_daemon.py` to exist at the repo root and import/exec it
directly:
  - `campy/cli/daemon_ctl.py` — bare `import brain_daemon` after a
    `sys.path` insert.
  - `campy/cli/launchd.py`'s `_daemon_script()` — prefers this exact path
    over the packaged `campy-daemon` console script whenever running from
    a git checkout (i.e. every dev environment).
  - `campy/cli/main.py`'s non-Darwin `start()`/`stop()` fallback and
    `campy/cli/install.py`'s daemon-script resolution — both reference
    this path directly.

Retiring this file entirely requires updating all of the above to import
`campy.brain_daemon`/invoke `campy-daemon` directly instead — tracked as
still-open scope in `backlog/B365.md`, not done here. Shimming first is the
lower-risk move: every one of those call sites keeps working unmodified,
and there is now only one real implementation underneath regardless of
which path someone runs.
"""

from campy.brain_daemon import *  # noqa: F401,F403 -- deprecated re-export shim
from campy.brain_daemon import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
