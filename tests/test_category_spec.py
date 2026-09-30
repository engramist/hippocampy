"""B458 — save-gate category spec: loads, validates, resolves overlaps."""
import copy

import pytest
import yaml

from campy.brain.temporal_lobe.category_spec import (
    CATEGORIES, SPEC_PATH, CategorySpecError, load_spec, parse_spec,
)


def _raw():
    with open(SPEC_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_shipped_spec_loads_with_every_category():
    spec = load_spec()
    assert set(spec.categories) == set(CATEGORIES)
    for cat in spec.categories.values():
        assert cat.definition
        assert cat.include and cat.exclude


def test_near_miss_labels_are_known_categories():
    spec = load_spec()
    for cat in spec.categories.values():
        for item in cat.near_miss:
            assert item["label"] in CATEGORIES


def test_precedence_resolves_overlap_to_constraint():
    # "We decided we must never log prompt bodies" fits decision and constraint;
    # the standing rule is what later sessions need.
    assert load_spec().resolve({"decision", "constraint"}) == "constraint"
    assert load_spec().resolve({"requirement", "action_item"}) == "requirement"


def test_missing_category_rejected():
    raw = _raw()
    del raw["categories"]["requirement"]
    with pytest.raises(CategorySpecError, match="missing"):
        parse_spec(raw)


def test_unknown_category_rejected():
    raw = _raw()
    raw["categories"]["fact"] = copy.deepcopy(raw["categories"]["none"])
    with pytest.raises(CategorySpecError, match="unknown"):
        parse_spec(raw)


def test_precedence_must_cover_every_category():
    raw = _raw()
    raw["precedence"] = ["constraint", "decision"]
    with pytest.raises(CategorySpecError, match="precedence"):
        parse_spec(raw)


def test_near_miss_with_unknown_label_rejected():
    raw = _raw()
    raw["categories"]["decision"]["near_miss"].append(
        {"text": "x", "label": "opinion", "why": "y"})
    with pytest.raises(CategorySpecError, match="near_miss"):
        parse_spec(raw)


def test_empty_definition_rejected():
    raw = _raw()
    raw["categories"]["decision"]["definition"] = "  "
    with pytest.raises(CategorySpecError, match="definition"):
        parse_spec(raw)
