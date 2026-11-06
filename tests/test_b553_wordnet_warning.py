"""B553: the principled profile warns (does not refuse) when WordNet is missing, and says which members degrade.

`campy status` and benchmark provenance read `profile_report`, which now carries WordNet's availability.
"""

from __future__ import annotations

import logging

import pytest

from campy.brain.brainstem import config as cfgmod
from campy.brain.brainstem.config import (
    ENV_OVERRIDES, PROFILE_ENV, PROFILE_NEEDS_WORDNET, PROFILES, load_config, profile_report,
    warn_if_wordnet_missing, wordnet_degraded,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in list(ENV_OVERRIDES) + [PROFILE_ENV]:
        monkeypatch.delenv(var, raising=False)


def _cfg(tmp_path, profile: str):
    path = tmp_path / "config.toml"
    path.write_text(f'[llm]\nprovider = "ollama"\n[pipeline]\nprofile = "{profile}"\n')
    return load_config(str(path))


def test_every_wordnet_member_is_a_principled_member():
    members = {(s, k) for s, items in PROFILES["principled"].items() for k in items}
    assert set(PROFILE_NEEDS_WORDNET) <= members


def test_principled_without_wordnet_names_the_degraded_members(tmp_path):
    cfg = _cfg(tmp_path, "principled")
    assert wordnet_degraded(cfg, available=False) == [f"{s}.{k}" for s, k in PROFILE_NEEDS_WORDNET]
    assert wordnet_degraded(cfg, available=True) == []


def test_main_without_wordnet_degrades_nothing(tmp_path):
    assert wordnet_degraded(_cfg(tmp_path, "main"), available=False) == []


def test_a_member_pinned_off_in_the_file_is_not_reported(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[pipeline]\nprofile = "principled"\n[observations]\ntyped_objects = false\n')
    degraded = wordnet_degraded(load_config(str(path)), available=False)
    assert "observations.typed_objects" not in degraded and "observations.wordnet_kinds" in degraded


def test_warning_is_logged_once_and_start_is_not_refused(tmp_path, caplog):
    cfg = _cfg(tmp_path, "principled")
    with caplog.at_level(logging.WARNING, logger=cfgmod.__name__):
        degraded = warn_if_wordnet_missing(cfg, available=False)
    records = [r for r in caplog.records if "WordNet is not installed" in r.getMessage()]
    assert len(records) == 1 and degraded
    assert all(name in records[0].getMessage() for name in degraded)


def test_no_warning_when_wordnet_is_present(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=cfgmod.__name__):
        assert warn_if_wordnet_missing(_cfg(tmp_path, "principled"), available=True) == []
    assert not [r for r in caplog.records if "WordNet" in r.getMessage()]


def test_profile_report_records_wordnet(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, "principled")
    monkeypatch.setattr(cfgmod, "wordnet_available", lambda: False)
    rep = profile_report(cfg)["wordnet"]
    assert rep["available"] is False and "observations.typed_objects" in rep["degraded"]
    monkeypatch.setattr(cfgmod, "wordnet_available", lambda: True)
    assert profile_report(cfg)["wordnet"] == {"available": True, "degraded": []}
