"""B545: the pipeline profile switch.

`main` (default) is today's config; `principled` sets the declared member flags. Precedence for one flag:
its env var > an explicit value in the user's config file > the profile > the built-in default. Each
member is checked through the helper the pipeline really calls, on a key-less user config (the B514
convention reads a missing key as off, so the profile has to put the key there).
"""

from __future__ import annotations

import copy

import pytest

from campy.brain.brainstem import config as cfgmod
from campy.brain.brainstem.config import (
    _DEFAULT_CONFIG, ENV_OVERRIDES, PROFILE_ENV, PROFILES, load_config, profile_report,
)
from campy.brain.hippocampus import kinds, observations as obs
from campy.brain.hippocampus.concept_links import graph_linking_limit
from campy.brain.temporal_lobe.observations import evidence_entities as evid
from campy.brain.temporal_lobe.steward import steward_enabled
from campy.brain.thalamus.graph_count import graph_count_enabled
from campy.brain.thalamus.question_analysis import question_analysis_enabled


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in list(ENV_OVERRIDES) + [PROFILE_ENV]:
        monkeypatch.delenv(var, raising=False)


def write(tmp_path, text: str = "[llm]\nprovider = \"ollama\"\n"):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return str(path)


# helper per member: (section, key) -> callable(config) -> value the pipeline sees
MEMBERS = {
    ("observations", "object_roles"): obs.object_roles_enabled,          # B522
    ("observations", "ownership_rule"): obs.ownership_rule_enabled,      # B523
    ("retrieval", "graph_count"): graph_count_enabled,                   # B524
    ("observations", "kind_hygiene"): kinds.kind_hygiene_enabled,        # B525
    ("observations", "wordnet_kinds"): kinds.wordnet_kinds_enabled,      # B534
    ("observations", "vocab_steward"): steward_enabled,                  # B535
    ("retrieval", "graph_linking_limit"): graph_linking_limit,           # B503 walk
    ("retrieval", "question_analysis"): question_analysis_enabled,       # B547
    ("observations", "typed_objects"): obs.typed_objects_enabled,        # B546
    ("observations", "evidence_entity_links"): evid.evidence_entity_links_enabled,   # B554
    # B544 (PR #387): its helper is not on this base; the key is read from [loop] once it merges.
    ("loop", "entity_admission"): lambda c: bool(c["loop"].get("entity_admission", False)),
}


def test_every_profile_member_has_a_test_helper():
    declared = {(s, k) for s, items in PROFILES["principled"].items() for k in items}
    assert declared == set(MEMBERS)


def test_main_is_todays_config_exactly(tmp_path):
    path = write(tmp_path)
    cfg = load_config(path)
    expected = {"llm": {"provider": "ollama"}}
    cfgmod._merge_defaults(expected, _DEFAULT_CONFIG)
    meta = {k: cfg.pop(k) for k in ("_profile", "_profile_sources", "_config_path", "_env_overrides")}
    assert meta["_profile"] == "main" and meta["_profile_sources"] == {}
    assert cfg == expected
    assert PROFILES["main"] == {}


@pytest.mark.parametrize("member", sorted(MEMBERS))
def test_principled_turns_each_member_on_for_a_keyless_config(tmp_path, monkeypatch, member):
    monkeypatch.setenv(PROFILE_ENV, "principled")
    cfg = load_config(write(tmp_path))
    value = MEMBERS[member](cfg)
    if member == ("retrieval", "graph_linking_limit"):
        assert value == 12
    else:
        assert value is True
    # and main leaves it off
    monkeypatch.delenv(PROFILE_ENV)
    main_value = MEMBERS[member](load_config(write(tmp_path)))
    assert main_value in (False, 0)


def test_profile_from_the_config_file(tmp_path):
    cfg = load_config(write(tmp_path, '[pipeline]\nprofile = "principled"\n'))
    assert cfg["_profile"] == "principled" and obs.object_roles_enabled(cfg) is True


def test_env_profile_beats_the_file_profile(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "main")
    cfg = load_config(write(tmp_path, '[pipeline]\nprofile = "principled"\n'))
    assert cfg["_profile"] == "main" and obs.object_roles_enabled(cfg) is False


def test_per_flag_env_beats_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "principled")
    monkeypatch.setenv("CAMPY_KIND_HYGIENE", "0")
    monkeypatch.setenv("CAMPY_GRAPH_LINKING_LIMIT", "0")
    cfg = load_config(write(tmp_path))
    assert kinds.kind_hygiene_enabled(cfg) is False
    assert graph_linking_limit(cfg) == 0
    assert obs.object_roles_enabled(cfg) is True            # untouched members stay on
    report = profile_report(cfg)["flags"]
    assert report["observations.kind_hygiene"] == {"value": False, "source": "env"}
    assert report["observations.object_roles"]["source"] == "profile"


def test_every_member_with_an_env_var_can_be_turned_off_by_it(tmp_path, monkeypatch):
    by_key = {(sec, key): var for var, (sec, key, _p) in ENV_OVERRIDES.items()}
    monkeypatch.setenv(PROFILE_ENV, "principled")
    for (section, key), var in by_key.items():
        if key not in {k for items in PROFILES["principled"].values() for k in items} or key == "graph_linking_limit":
            continue
        monkeypatch.setenv(var, "0")
        assert load_config(write(tmp_path))[section][key] is False, var
        monkeypatch.delenv(var)


def test_file_value_beats_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "principled")
    cfg = load_config(write(tmp_path, "[observations]\nobject_roles = false\n[retrieval]\ngraph_linking_limit = 0\n"))
    assert obs.object_roles_enabled(cfg) is False and graph_linking_limit(cfg) == 0
    assert obs.ownership_rule_enabled(cfg) is True
    report = profile_report(cfg)["flags"]
    assert report["observations.object_roles"]["source"] == "file"
    assert report["retrieval.graph_linking_limit"]["source"] == "file"


def test_unknown_profile_fails_loudly_naming_the_choices(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "princpled")
    with pytest.raises(ValueError, match=r"CAMPY_PROFILE.*princpled.*main, principled"):
        load_config(write(tmp_path))
    monkeypatch.delenv(PROFILE_ENV)
    with pytest.raises(ValueError, match=r"\[pipeline\] profile"):
        load_config(write(tmp_path, '[pipeline]\nprofile = "nope"\n'))


def test_profile_does_not_change_the_defaults_table():
    before = copy.deepcopy(_DEFAULT_CONFIG)
    cfgmod.apply_profile({"pipeline": {"profile": "principled"}})
    assert _DEFAULT_CONFIG == before


def test_report_lists_members_and_stay_on_flags(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "principled")
    rep = profile_report(load_config(write(tmp_path)))
    assert rep["profile"] == "principled"
    assert rep["flags"]["retrieval.graph_linking_limit"] == {"value": 12, "source": "profile"}
    assert rep["flags"]["observations.turn_dates"] == {"value": True, "source": "default"}
    assert rep["flags"]["loop.entity_admission"]["value"] is True


# --- shipped templates and a fresh (benchmark --isolated style) home ------------------------

import shutil
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = [REPO / "campy.toml", REPO / "campy" / "data" / "config" / "campy.toml"]


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(REPO)))
def test_shipped_templates_set_no_profile_member(template):
    raw = tomllib.loads(template.read_text())
    for section, items in PROFILES["principled"].items():
        for key in items:
            assert key not in (raw.get(section) or {}), f"{template.name} pins {section}.{key}"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(REPO)))
def test_fresh_isolated_home_resolves_every_member_on(tmp_path, monkeypatch, template):
    """campy-benchmarks --isolated writes <CAMPY_HOME>/config.toml = the base config (a copy of a template or
    ~/.campy/config.toml) plus overrides for capture/daemon/web/server/activity keys, and the daemon
    loads only that file. Do the same here and require every member ON through its real helper."""
    home = tmp_path / "home"
    home.mkdir()
    cfg_text = template.read_text()
    raw = tomllib.loads(cfg_text)
    raw.setdefault("web", {})["port"] = 17999
    raw.setdefault("server", {})["bind_host"] = "127.0.0.1"
    raw.setdefault("capture", {})["enabled"] = False
    raw.setdefault("watchdog", {})["enabled"] = False
    lines = []
    for sec, vals in raw.items():
        if isinstance(vals, dict) and all(not isinstance(v, (dict, list)) for v in vals.values()):
            lines.append(f"[{sec}]")
            lines += [f"{k} = {_toml(v)}" for k, v in vals.items()]
    (home / "config.toml").write_text("\n".join(lines) + "\n")
    monkeypatch.setenv("CAMPY_HOME", str(home))
    monkeypatch.chdir(home)
    monkeypatch.setenv(PROFILE_ENV, "principled")
    cfg = load_config()
    assert cfg["_config_path"] == str(home / "config.toml")
    for member, helper in MEMBERS.items():
        value = helper(cfg)
        assert (value == 12) if member == ("retrieval", "graph_linking_limit") else (value is True), member
    assert all(v["source"] == "profile" for k, v in profile_report(cfg)["flags"].items()
               if tuple(k.split(".")) in MEMBERS)


def _toml(v):
    import json as _j
    return "true" if v is True else "false" if v is False else _j.dumps(v)


def test_main_effective_config_is_unchanged_by_the_template_edit(tmp_path):
    """Under profile main, the resolved flag values for a copy of the shipped template are the built-in defaults."""
    cfg = load_config(str(TEMPLATES[1]))
    assert cfg["_profile"] == "main"
    assert cfg["observations"]["object_roles"] is False and cfg["observations"]["ownership_rule"] is False
    assert cfg["retrieval"]["graph_count"] is False and cfg["retrieval"]["graph_linking_limit"] == 0
    for section, key in [("observations", "object_roles"), ("observations", "ownership_rule"),
                         ("retrieval", "graph_count"), ("retrieval", "graph_linking_limit")]:
        assert cfg[section][key] == _DEFAULT_CONFIG[section][key]
