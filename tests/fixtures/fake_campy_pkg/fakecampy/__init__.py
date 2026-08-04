"""Minimal stand-in `campy` console script for bootstrap.sh integration tests.

Prints its own version and argv, then exits 0 for every invocation. Real
enough that `campy --help`, `campy install`, `campy doctor --repair`, and
`campy start` all succeed (or at least never crash bootstrap.sh's `|| warn`
fallbacks) without needing hippocampy's actual heavy dependencies installed.
"""
import sys


def main() -> None:
    print(f"fakecampy 0.1.0 called with args: {sys.argv[1:]}")
    sys.exit(0)
