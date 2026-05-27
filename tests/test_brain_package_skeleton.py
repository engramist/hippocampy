from importlib import import_module
from pathlib import Path

import pytest


PACKAGE_MODULES = [
    "campy.brain",
    "campy.brain.brainstem",
    "campy.brain.sensory_cortex",
    "campy.brain.temporal_lobe",
    "campy.brain.hippocampus",
    "campy.brain.thalamus",
]


@pytest.mark.parametrize("module_name", PACKAGE_MODULES)
def test_brain_package_modules_import(module_name: str) -> None:
    module = import_module(module_name)
    assert module is not None


@pytest.mark.parametrize(
    "readme_path",
    [
        Path("campy/brain/README.md"),
        Path("campy/brain/brainstem/README.md"),
        Path("campy/brain/sensory_cortex/README.md"),
        Path("campy/brain/temporal_lobe/README.md"),
        Path("campy/brain/hippocampus/README.md"),
        Path("campy/brain/thalamus/README.md"),
    ],
)
def test_brain_region_readmes_exist(readme_path: Path) -> None:
    assert readme_path.is_file(), f"missing README: {readme_path}"
