"""
Whether a real, working spaCy (with en_core_web_md) is available to tests.

Test modules gate spaCy-dependent tests with:

    from tests._spacy import SPACY_AVAILABLE

Do NOT `from conftest import SPACY_AVAILABLE`: in a full `pytest tests/` run
the bare module name `conftest` resolves to tests/patent_claims/conftest.py
(that directory is not a package, so pytest puts it on sys.path), the import
fails, and every spaCy test is silently skipped even though spaCy works.

tests/conftest.py imports this module first and installs its `spacy` stub
when SPACY_AVAILABLE is False.
"""

SPACY_AVAILABLE = False
try:
    import spacy as _real_spacy
    # Import alone isn't enough — spaCy 3.x loads on Python 3.14 but
    # pydantic v1 compat is broken, so spacy.load() fails at runtime.
    _real_spacy.load("en_core_web_md")
    SPACY_AVAILABLE = True
except Exception:
    pass
