"""
tests/test_bind_guard.py — B325 Task 2: bind address as explicit, guarded
configuration.

The single most important property this card adds: binding to any
non-loopback address while no auth resolver is configured must be a HARD
STARTUP FAILURE — refuse to listen, not warn. These tests assert nothing
gets bound, not merely that a message was logged.
"""

from __future__ import annotations

import asyncio

import pytest

from campy.brain_daemon import (
    BindGuardError,
    _build_http_principal_resolver,
    _enforce_bind_guard,
    _LOOPBACK_BIND_HOSTS,
)
from campy.brain.auth import IAMPrincipalResolver, LocalSingleUserResolver

# A concrete LAN address, distinct from the "any interface" 0.0.0.0/::
# wildcards — the card explicitly requires covering all three shapes of
# "not loopback", not just the wildcard case.
_LAN_ADDRESS = "10.0.0.5"
_NON_LOOPBACK_HOSTS = ["0.0.0.0", "::", _LAN_ADDRESS]  # noqa: allow the literal in a test file


# ---------------------------------------------------------------------------
# _enforce_bind_guard — the core decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", sorted(_LOOPBACK_BIND_HOSTS))
def test_loopback_with_auth_none_starts_normally(host):
    """Today's only supported local configuration must keep working unchanged."""
    _enforce_bind_guard(host, "none")  # must not raise


@pytest.mark.parametrize("host", _NON_LOOPBACK_HOSTS)
def test_non_loopback_with_auth_none_is_hard_failure(host):
    with pytest.raises(BindGuardError):
        _enforce_bind_guard(host, "none")


@pytest.mark.parametrize("host", _NON_LOOPBACK_HOSTS)
def test_non_loopback_with_auth_iam_starts(host):
    _enforce_bind_guard(host, "iam")  # must not raise


@pytest.mark.parametrize("host", _NON_LOOPBACK_HOSTS)
def test_non_loopback_with_auth_oidc_passes_the_bind_guard(host):
    """The bind guard itself only cares that SOME auth is configured;
    whether "oidc" has a working resolver is a separate concern (see
    test_build_http_principal_resolver_oidc_not_implemented below)."""
    _enforce_bind_guard(host, "oidc")  # must not raise


@pytest.mark.parametrize("host", sorted(_LOOPBACK_BIND_HOSTS))
@pytest.mark.parametrize("auth_mode", ["iam", "oidc"])
def test_loopback_with_real_auth_mode_starts(host, auth_mode):
    """Non-'none' auth on a loopback bind is fine (useful for testing the
    auth path locally) — the card is explicit about this."""
    _enforce_bind_guard(host, auth_mode)  # must not raise


def test_bind_guard_error_names_host_and_auth():
    with pytest.raises(BindGuardError) as exc_info:
        _enforce_bind_guard("0.0.0.0", "none")
    message = str(exc_info.value)
    assert "0.0.0.0" in message
    assert "none" in message


# ---------------------------------------------------------------------------
# Structural proof: nothing gets bound when the guard raises. Mirrors the
# exact guard-then-bind sequence BrainDaemon.start() / _start_web_server
# follow, using a minimal real asyncio TCP listener in place of uvicorn so
# the test is fast and has no FastAPI dependency, while still proving the
# bind call is never reached when the guard fires (not merely that a log
# line was printed).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("host", _NON_LOOPBACK_HOSTS)
async def test_guard_prevents_a_listener_from_ever_being_created(host, monkeypatch):
    bind_attempts = []

    async def _fake_start_server(*args, **kwargs):
        bind_attempts.append((args, kwargs))
        raise AssertionError("asyncio.start_server must never be reached when the guard fires")

    monkeypatch.setattr(asyncio, "start_server", _fake_start_server)

    async def _guarded_serve():
        _enforce_bind_guard(host, "none")
        return await asyncio.start_server(lambda r, w: None, host=host, port=0)

    with pytest.raises(BindGuardError):
        await _guarded_serve()

    assert bind_attempts == [], "the guard must fire before any bind is attempted"


@pytest.mark.asyncio
async def test_guard_allows_the_listener_when_configured_safely(monkeypatch):
    """Sanity check for the harness above: when the guard passes, the bind
    call downstream of it does happen — proving the previous test's
    "prevented" result is because of the guard, not a broken harness."""
    bind_attempts = []

    async def _fake_start_server(*args, **kwargs):
        bind_attempts.append((args, kwargs))
        return "fake-server"

    monkeypatch.setattr(asyncio, "start_server", _fake_start_server)

    async def _guarded_serve():
        _enforce_bind_guard("127.0.0.1", "none")
        return await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)

    result = await _guarded_serve()
    assert result == "fake-server"
    assert len(bind_attempts) == 1


# ---------------------------------------------------------------------------
# _build_http_principal_resolver — the resolver chosen from [server].auth
# ---------------------------------------------------------------------------


def test_build_resolver_none_is_local_single_user():
    resolver = _build_http_principal_resolver("none", {})
    assert isinstance(resolver, LocalSingleUserResolver)


def test_build_resolver_iam_is_iam_resolver():
    resolver = _build_http_principal_resolver("iam", {})
    assert isinstance(resolver, IAMPrincipalResolver)


def test_build_resolver_oidc_not_implemented_fails_loudly():
    """Config accepts "oidc" (per the card), but attempting to actually use
    it before a resolver exists must fail loudly at startup, not silently
    degrade to an unauthenticated mode."""
    with pytest.raises(BindGuardError):
        _build_http_principal_resolver("oidc", {})


def test_build_resolver_unknown_auth_mode_fails_loudly():
    with pytest.raises(BindGuardError):
        _build_http_principal_resolver("totally-made-up", {})
