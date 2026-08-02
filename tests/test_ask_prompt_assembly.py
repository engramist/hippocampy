"""B303 — ask prompt-assembly tests.

The synthesis LLM was answering "my memory is empty" even with a non-empty
plans section, for two stacked reasons: (1) the prompt gave no explanation of
what a "plans" section IS, and (2) _bundle_to_prompt only knew how to render
items carrying compact/toon/text/source keys — plan items carry goal/status/
valence/steps instead, so plan content was silently dropped from the prompt
entirely. These tests pin both fixes at the prompt-assembly layer, with no
LLM or DB involved.
"""

from __future__ import annotations

from campy.brain.thalamus.ask import _bundle_to_prompt
from campy.brain.thalamus.bundle_compiler import BundleSection, ContextBundle


def _bundle_with_plan_section() -> ContextBundle:
    plan_item = {
        "plan_id": "plan-b292",
        "goal": "Implement B292 by splitting tools/__init__.py into focused modules",
        "status": "completed",
        "valence": 0.8,
        "pathway_strength": 0.9,
        "similarity": 0.42,
        "steps": [
            {"step_number": 1, "description": "Split tools into modules", "valence": 0.8},
        ],
    }
    section = BundleSection(
        section_type="plans",
        content=[plan_item],
        token_estimate=150,
        source_node_ids=["plan-b292"],
    )
    return ContextBundle(
        query="What work did the agent do on B292?",
        sections=[section],
        total_token_estimate=150,
        token_budget=32000,
        truncated=False,
    )


def test_plan_goal_text_survives_into_the_prompt():
    bundle = _bundle_with_plan_section()
    prompt = _bundle_to_prompt(bundle, bundle.query)
    assert "Implement B292 by splitting tools/__init__.py into focused modules" in prompt


def test_plans_section_explanation_is_present():
    bundle = _bundle_with_plan_section()
    prompt = _bundle_to_prompt(bundle, bundle.query)
    assert "plans" in prompt.lower()
    # The section explanation from the card's own wording.
    assert "per-step outcomes" in prompt


def test_nonempty_bundle_states_memory_is_not_empty():
    bundle = _bundle_with_plan_section()
    prompt = _bundle_to_prompt(bundle, bundle.query)
    assert "not empty" in prompt.lower() or "do not" in prompt.lower()


def test_empty_bundle_has_no_memory_exists_claim():
    bundle = ContextBundle(
        query="anything",
        sections=[],
        total_token_estimate=0,
        token_budget=32000,
        truncated=False,
    )
    prompt = _bundle_to_prompt(bundle, bundle.query)
    assert "not empty" not in prompt.lower()


def test_empty_bundle_tells_model_no_relevant_context_was_found():
    """B305: an empty bundle must instruct the model plainly to say so rather
    than guess — the B303 hardening only covered the non-empty case."""
    bundle = ContextBundle(
        query="anything",
        sections=[],
        total_token_estimate=0,
        token_budget=32000,
        truncated=False,
    )
    prompt = _bundle_to_prompt(bundle, bundle.query)
    lowered = prompt.lower()
    assert "no relevant context" in lowered or "no relevant memory" in lowered
    assert "do not guess" in lowered or "do not fabricate" in lowered or "say so" in lowered
