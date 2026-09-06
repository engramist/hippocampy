"""
tests/test_no_torch_dependency.py — B400 regression guard.

torch is not a required dependency of this project — `thinc` (spaCy's ML
backend) only lists it behind an opt-in extra (`thinc[torch]`); a plain
`spacy` install never requests it. But `thinc.compat` unconditionally
attempts `import torch` at import time purely for backend auto-detection
(`has_torch`), regardless of whether anything actually uses it for
computation. So the instant *anything else* in the environment has a hard
dependency on torch (historically `sentence-transformers`, replaced by
`fastembed` in B355 — see backlog/B355.md), `import spacy` alone silently
pulls torch into `sys.modules` and costs ~150-160MB of resident memory for
a backend that `en_core_web_md` (entirely CNN-based: tok2vec, tagger,
parser, attribute_ruler, lemmatizer, ner — no transformer component) never
touches. See backlog/B400.md and
docs/superpowers/specs/2026-09-05-entity-candidate-generation-design.md §1.

This test is the tripwire for that regression class: it exercises the real
ingestion path (Step 1 NER + Step 1b relation extraction, the same code
Step 1/1b of the Loop calls in production) and asserts torch never enters
sys.modules as a result. It will fail the day something reintroduces a
hard torch dependency (e.g. `sentence-transformers`, `spacy[transformers]`,
`thinc[torch]`), which is the intended signal.

Skips when spaCy itself isn't loadable — see tests/conftest.py: spaCy's
pydantic.v1 compat is broken on Python 3.14. CI runs Python 3.12.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))  # make conftest importable

try:
    from conftest import SPACY_AVAILABLE
except ImportError:
    SPACY_AVAILABLE = False

_needs_spacy = pytest.mark.skipif(
    not SPACY_AVAILABLE,
    reason="spaCy not compatible with this Python version",
)


@_needs_spacy
def test_torch_absent_after_full_ingestion_path():
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations

    # A handful of turns exercising NER, the noun-chunk fallback, and the
    # dependency-parse relation extractor together — the full candidate-
    # generation surface that Step 1/1b of the Loop runs per turn.
    turns = [
        "ARC-AGI-3 requires ACTION1.",
        "SideQuests uses Kuzu, PostgreSQL, and React for its memory layer.",
        "Kubernetes deprecates Docker Swarm and overrides the old scheduler.",
    ]

    produced_any_entity = False
    produced_any_relation = False
    for text in turns:
        doc, entities = extract_entities(text)
        relations = extract_relations(doc, entities)
        produced_any_entity = produced_any_entity or bool(entities)
        produced_any_relation = produced_any_relation or bool(relations)

    # Sanity: prove the real model actually ran (not silently no-op'd) —
    # a torch-absence assertion is meaningless if the pipeline never fired.
    assert produced_any_entity, "extract_entities produced no entities at all — pipeline didn't run"
    assert produced_any_relation, "extract_relations produced no relations at all — pipeline didn't run"

    torch_modules = [m for m in sys.modules if m == "torch" or m.startswith("torch.")]
    assert not torch_modules, (
        "torch was imported into sys.modules by the spaCy ingestion path "
        f"(found: {torch_modules}). thinc.compat auto-imports torch whenever "
        "it is importable, even though en_core_web_md never uses it for "
        "computation (NumpyOps backend, CNN-only pipeline) — see "
        "backlog/B400.md. This means something in the installed environment "
        "now has a hard dependency on torch again (check for "
        "sentence-transformers, spacy[transformers], or thinc[torch])."
    )
