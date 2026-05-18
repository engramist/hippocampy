"""
tests/fixtures/__init__.py — Test fixtures
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent

sample_budget_path = FIXTURES_DIR / "sample_budget.csv"
sample_data_path = FIXTURES_DIR / "sample_data.tsv"
sample_contacts_path = FIXTURES_DIR / "sample_contacts.xlsx"

__all__ = [
    "FIXTURES_DIR",
    "sample_budget_path",
    "sample_data_path",
    "sample_contacts_path",
]
