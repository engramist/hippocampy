from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, List

import httpx

__all__ = [
    "SweCiTask",
    "ensure_dataset_cached",
    "load_dataset",
    "DATASET_URL",
]

DATASET_URL = (
    "https://raw.githubusercontent.com/djs54/sidequests-brain/main/benchmarks/swe_ci/data/swe_ci_sample.json"
)
CACHE_SUBDIR = Path(__file__).parent / "cache"
CACHE_FILENAME = "swe_ci_dataset.json"
SAMPLE_FILE = Path(__file__).parent / "data" / "swe_ci_sample.json"


class SweCiTask:
    def __init__(self, task_id: str, description: str, constraints: Iterable[str], difficulty: float) -> None:
        self.task_id = task_id
        self.description = description
        self.constraints = list(constraints)
        self.difficulty = difficulty

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "constraints": self.constraints,
            "difficulty": self.difficulty,
        }


def ensure_dataset_cached(cache_root: Path | None = None) -> Path:
    root = Path(cache_root or CACHE_SUBDIR)
    root.mkdir(parents=True, exist_ok=True)
    cache_file = root / CACHE_FILENAME
    if cache_file.exists():
        return cache_file

    try:
        response = httpx.get(DATASET_URL, timeout=5)
        response.raise_for_status()
        cache_file.write_text(response.text)
    except Exception:
        if SAMPLE_FILE.exists():
            shutil.copyfile(SAMPLE_FILE, cache_file)
        else:
            cache_file.write_text("[]")
    return cache_file


def load_dataset(dataset_path: Path) -> List[SweCiTask]:
    raw = json.loads(dataset_path.read_text())
    tasks: List[SweCiTask] = []
    for entry in raw:
        tasks.append(
            SweCiTask(
                task_id=entry["task_id"],
                description=entry.get("description", ""),
                constraints=entry.get("constraints", []),
                difficulty=float(entry.get("difficulty", 0.5)),
            )
        )
    return tasks
