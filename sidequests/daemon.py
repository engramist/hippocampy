"""
sidequests/daemon.py — Brain Daemon entry point for installed package.

Delegates to brain_daemon.py at the project root.
This module exists so pyproject.toml can define:
  sidequests-daemon = "sidequests.daemon:main"
"""

from __future__ import annotations
import sys
from pathlib import Path


def main() -> None:
    """Start the Brain Daemon."""
    # Ensure the project root is in sys.path
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import brain_daemon
    brain_daemon.main()


if __name__ == "__main__":
    main()
