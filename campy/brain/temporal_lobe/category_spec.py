"""
B462 — Save-gate artifact category specification loader.

Loads and validates campy/data/artifact_categories.yaml: what each Step 4
artifact category (decision, constraint, requirement, action_item, none)
means, and which label wins when a statement fits more than one.

Static seed data, not agent state: nothing here is written at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "artifact_categories.yaml"

# The labels Step 4 can produce (classify_artifact's artifact_type values,
# with "noise" named "none" here).
CATEGORIES = ("decision", "constraint", "requirement", "action_item", "none")


class CategorySpecError(ValueError):
    """The category spec file is malformed."""


@dataclass(frozen=True)
class Category:
    name: str
    definition: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    near_miss: tuple[dict, ...]


@dataclass(frozen=True)
class CategorySpec:
    version: int
    precedence: tuple[str, ...]
    categories: dict[str, Category]
    open_questions: tuple[str, ...]

    def resolve(self, labels: set[str] | list[str]) -> str:
        """Pick the single label for a statement that fits several categories."""
        for name in self.precedence:
            if name in labels:
                return name
        raise CategorySpecError(f"no known category in {sorted(labels)!r}")


def parse_spec(raw: dict) -> CategorySpec:
    """Validate a parsed spec document and build a CategorySpec."""
    if not isinstance(raw, dict):
        raise CategorySpecError("spec must be a mapping")

    cats_raw = raw.get("categories")
    if not isinstance(cats_raw, dict):
        raise CategorySpecError("spec has no 'categories' mapping")

    missing = set(CATEGORIES) - set(cats_raw)
    unknown = set(cats_raw) - set(CATEGORIES)
    if missing or unknown:
        raise CategorySpecError(
            f"categories must be exactly {CATEGORIES}; "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )

    precedence = tuple(raw.get("precedence") or ())
    if sorted(precedence) != sorted(CATEGORIES):
        raise CategorySpecError(
            f"precedence must list every category exactly once, got {precedence!r}"
        )

    categories: dict[str, Category] = {}
    for name in CATEGORIES:
        body = cats_raw[name] or {}
        definition = (body.get("definition") or "").strip()
        if not definition:
            raise CategorySpecError(f"category {name!r} has no definition")
        near_miss = tuple(body.get("near_miss") or ())
        for item in near_miss:
            if not item.get("text") or item.get("label") not in CATEGORIES:
                raise CategorySpecError(
                    f"category {name!r} near_miss needs text and a known label: {item!r}"
                )
            if not item.get("why"):
                raise CategorySpecError(f"category {name!r} near_miss has no 'why': {item!r}")
        categories[name] = Category(
            name=name,
            definition=definition,
            include=tuple(body.get("include") or ()),
            exclude=tuple(body.get("exclude") or ()),
            near_miss=near_miss,
        )

    return CategorySpec(
        version=int(raw.get("version", 0)),
        precedence=precedence,
        categories=categories,
        open_questions=tuple(raw.get("open_questions") or ()),
    )


@lru_cache(maxsize=1)
def load_spec(path: str | None = None) -> CategorySpec:
    """Load and validate the category spec (cached; pass a path for tests)."""
    spec_path = Path(path) if path else SPEC_PATH
    with open(spec_path, encoding="utf-8") as fh:
        return parse_spec(yaml.safe_load(fh))
