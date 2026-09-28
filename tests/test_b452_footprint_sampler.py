"""tests/test_b452_footprint_sampler.py -- B452 proof.

The footprint watchdog (B354) sampled `vmmap -summary` (a full memory-map
text dump) on every check. Confirmed live during B451's 43GB blowup: it
repeatedly exceeded its own 10s timeout under load ("vmmap check failed ...
skipping this check", logged for hours) -- exactly when the watchdog most
needs a real sample. `_footprint_parsed()` reads the same kernel-reported
physical footprint via the `footprint -j` tool instead, confirmed ~17x
faster at idle and still fast when tested directly against the real 46GB
blowup process during this investigation.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from campy.brain_daemon import _footprint_parsed

# `footprint`/`vmmap` are macOS-only diagnostic tools this watchdog is built
# around (see _periodic_footprint_watchdog's own docstring on why RSS/psutil
# are unsuitable here); CI runs on ubuntu-latest, where they don't exist.
# These tests prove the real subprocess/JSON-parsing path works, which a
# mocked-_footprint_parsed test (see test_auth_context.py's watchdog tests,
# which do run on every platform) cannot -- so skip here instead of mocking
# away the exact thing being verified.
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="footprint/vmmap are macOS-only tools"
)


def test_footprint_parsed_reads_own_process():
    """AC: a real call against this test's own process returns a sane,
    positive footprint in MB -- proves the JSON parsing path end to end,
    not just against a mock."""
    result = _footprint_parsed(os.getpid())
    assert result["error"] is None
    assert result["footprint_mb"] is not None
    assert result["footprint_mb"] > 1.0  # any live Python process is well over 1MB


def test_footprint_parsed_is_fast():
    """AC: the whole point of B452 -- this must stay well under vmmap's 10s
    timeout even though it shells out to a real subprocess."""
    t0 = time.perf_counter()
    result = _footprint_parsed(os.getpid())
    elapsed = time.perf_counter() - t0
    assert result["footprint_mb"] is not None
    assert elapsed < 3.0


def test_footprint_parsed_fails_gracefully_on_unknown_pid():
    """AC: an invalid target never raises -- degrades to the same error-dict
    contract the watchdog's failure path already handles."""
    result = _footprint_parsed(999_999_999)
    assert result["footprint_mb"] is None
    assert result["error"] is not None


def test_footprint_parsed_return_shape_matches_vmmap_parsed_contract():
    """AC: drop-in replacement -- same dict keys as _vmmap_parsed(), so the
    watchdog's existing comparison/logging code needed zero changes beyond
    the function name."""
    from campy.brain_daemon import _vmmap_parsed

    fp = _footprint_parsed(os.getpid())
    vm = _vmmap_parsed(os.getpid())
    assert set(fp.keys()) == set(vm.keys()) == {
        "footprint_mb", "footprint_raw", "small_resident", "small_swapped", "error",
    }
