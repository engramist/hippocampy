"""
sidequests/daemon.py — Brain Daemon entry point for installed package.

Delegates to sidequests/brain_daemon.py within the package.
This module exists so pyproject.toml can define:
  sidequests-daemon = "sidequests.daemon:main"
"""

from __future__ import annotations


def main() -> None:
    """Start the Brain Daemon."""
    from sidequests import brain_daemon
    brain_daemon.main()


if __name__ == "__main__":
    main()
