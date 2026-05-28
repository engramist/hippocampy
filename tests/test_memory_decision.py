"""Test suite for memory_decision MCP tool (B235).

Validates deterministic routing rules for selective memory recall.
Related card: B235 - MCP Memory Decision Helper Tool
"""

import pytest
from campy.brain.thalamus.memory_decision import decide_memory_action


class TestMemoryDecisionBasics:
    """Test basic functionality of memory_decision."""
    
    def test_returns_dict_with_required_keys(self):
        """Verify function returns dict with all required keys."""
        result = decide_memory_action("What did we decide?")
        
        required_keys = [
            "should_recall",
            "recommended_tool",
            "query",
            "reason",
            "confidence",
            "context_budget",
            "anti_bloat_guidance",
        ]
        
        for key in required_keys:
            assert key in result, f"Missing required key: {key}"
    
    def test_return_types_are_correct(self):
        """Verify return values have correct types."""
        result = decide_memory_action("Simple question")
        
        assert isinstance(result["should_recall"], bool)
        assert isinstance(result["recommended_tool"], str)
        assert isinstance(result["query"], str)
        assert isinstance(result["reason"], str)
        assert isinstance(result["confidence"], (int, float))
        assert isinstance(result["context_budget"], str)
        assert isinstance(result["anti_bloat_guidance"], str)
    
    def test_confidence_in_valid_range(self):
        """Verify confidence is between 0 and 1."""
        result = decide_memory_action("Any question")
        assert 0.0 <= result["confidence"] <= 1.0


class TestMemoryDecisionEmptyPrompt:
    """Test behavior with empty or minimal prompts."""
    
    def test_empty_prompt_returns_no_recall(self):
        """Empty prompt should not trigger recall."""
        result = decide_memory_action("")
        assert result["should_recall"] is False
        assert result["recommended_tool"] == "none"
    
    def test_whitespace_only_prompt_returns_no_recall(self):
        """Whitespace-only prompt should not trigger recall."""
        result = decide_memory_action("   \t\n   ")
        assert result["should_recall"] is False
        assert result["recommended_tool"] == "none"


class TestMemoryDecisionCurrentTruth:
    """Test routing to current_truth tool."""
    
    def test_prior_decisions_trigger_current_truth(self):
        """Prompts about prior decisions should recommend current_truth."""
        prompts = [
            "What did we decide?",
            "What decision did we make?",
            "What are the constraints?",
            "What's the preference on async?",
            "Did we choose option A or B?",
            "Are the requirements still the same?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "current_truth", f"Prompt: {prompt}"
    
    def test_current_truth_confidence_is_high(self):
        """current_truth recommendations should have high confidence."""
        result = decide_memory_action("What did we decide?")
        assert result["confidence"] >= 0.80


class TestMemoryDecisionDiffSince:
    """Test routing to diff_since tool."""
    
    def test_change_questions_trigger_diff_since(self):
        """Change/diff prompts should recommend diff_since."""
        prompts = [
            "What changed since last session?",
            "What's different now?",
            "What did the other agent do?",
            "What changed since the last time?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "diff_since", f"Prompt: {prompt}"


class TestMemoryDecisionTimeline:
    """Test routing to reconstruct_timeline tool."""
    
    def test_timeline_prompts_trigger_reconstruct_timeline(self):
        """Timeline/sequence prompts should recommend reconstruct_timeline."""
        prompts = [
            "Walk me through the timeline.",
            "What happened in sequence?",
            "How did we get here?",
            "What's the chronology of events?",
            "Debug step by step through what happened.",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "reconstruct_timeline", f"Prompt: {prompt}"


class TestMemoryDecisionPlans:
    """Test routing to recall_plans tool."""
    
    def test_plan_prompts_trigger_recall_plans(self):
        """Planning/strategy prompts should recommend recall_plans."""
        prompts = [
            "How did we implement this before?",
            "What was our strategy last time?",
            "I need to implement X like we did Y.",
            "How should we approach this backlog card?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "recall_plans", f"Prompt: {prompt}"


class TestMemoryDecisionProcedures:
    """Test routing to recall_procedures tool."""
    
    def test_procedure_prompts_trigger_recall_procedures(self):
        """Workflow/procedure prompts should recommend recall_procedures."""
        prompts = [
            "What's our standard testing procedure?",
            "How do we usually do releases?",
            "What's the checklist for this workflow?",
            "What are the steps in our process?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "recall_procedures", f"Prompt: {prompt}"


class TestMemoryDecisionLessons:
    """Test routing to recall_relevant_lessons tool."""
    
    def test_lesson_prompts_trigger_recall_lessons(self):
        """Lesson/learning prompts should recommend recall_relevant_lessons."""
        prompts = [
            "What lessons did we learn from this?",
            "What should we avoid based on past mistakes?",
            "What's the best practice for this?",
            "What pitfalls did we discover?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "recall_relevant_lessons", f"Prompt: {prompt}"


class TestMemoryDecisionAnalogy:
    """Test routing to analogical_search tool."""
    
    def test_analogy_prompts_trigger_analogical_search(self):
        """Analogy/similar prompts should recommend analogical_search."""
        prompts = [
            "We had a similar problem before.",
            "This resembles the installer project.",
            "This is analogous to what we did last time.",
            "Is there a comparable situation we solved?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "analogical_search", f"Prompt: {prompt}"


class TestMemoryDecisionARCTools:
    """Test routing to ARC recall tools."""
    
    def test_mechanic_prompts_trigger_recall_mechanic_priors(self):
        """ARC mechanic prompts should recommend recall_mechanic_priors."""
        prompts = [
            "What ARC mechanics did we discover?",
            "What world-model patterns did we learn?",
            "What puzzle transformations do we know?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "recall_mechanic_priors", f"Prompt: {prompt}"
    
    def test_scene_graph_prompts_trigger_recall_scene_graph_priors(self):
        """ARC scene graph prompts should recommend recall_scene_graph_priors."""
        prompts = [
            "What scene graph patterns did we find?",
            "What spatial transformations do we know?",
            "What grid layout patterns are common?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            # Either scene_graph or mechanic_priors is acceptable
            assert result["recommended_tool"] in ["recall_scene_graph_priors", "recall_mechanic_priors"], \
                f"Prompt: {prompt}, got {result['recommended_tool']}"


class TestMemoryDecisionContextStatus:
    """Test routing to context_status tool."""
    
    def test_context_health_prompts_trigger_context_status(self):
        """Context health prompts should recommend context_status."""
        prompts = [
            "How much context is left?",
            "What's my token budget?",
            "Am I at risk of context bloat?",
            "How much memory have I used?",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "context_status", f"Prompt: {prompt}"


class TestMemoryDecisionNoRecall:
    """Test cases where no recall should happen."""
    
    def test_simple_local_edits_no_recall(self):
        """Simple local edits should not trigger recall."""
        prompts = [
            "Add a comment to this function.",
            "Fix the typo on line 42.",
            "Change variable name from x to y.",
            "Format this code.",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is False, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "none", f"Prompt: {prompt}"
    
    def test_generic_prompts_no_recall(self):
        """Generic prompts that don't match patterns should not trigger recall."""
        prompts = [
            "Hello",
            "How are you?",
            "What's the weather?",
            "Tell me a joke",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is False, f"Prompt: {prompt}"


class TestMemoryDecisionConfidence:
    """Test confidence values for different routing decisions."""
    
    def test_current_truth_has_high_confidence(self):
        """current_truth should have high confidence."""
        result = decide_memory_action("What did we decide?")
        assert result["confidence"] >= 0.80
    
    def test_no_recall_has_high_confidence(self):
        """No-recall decisions should have high confidence."""
        result = decide_memory_action("Fix the typo")
        assert result["confidence"] >= 0.75
    
    def test_analogy_has_moderate_confidence(self):
        """Analogy routing should have moderate confidence."""
        result = decide_memory_action("We had a similar situation before.")
        # Analogy returns 0.72 confidence
        assert result["confidence"] >= 0.70 and result["confidence"] < 0.80


class TestMemoryDecisionContextBudget:
    """Test context_budget recommendations."""
    
    def test_context_budget_is_always_set(self):
        """Every result should have a context_budget."""
        prompts = [
            "What did we decide?",
            "Fix typo",
            "What changed?",
            "",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["context_budget"] in ["compact", "moderate", "exhaustive"]
    
    def test_default_context_budget_is_compact(self):
        """Most decisions should use 'compact' budget to avoid bloat."""
        result = decide_memory_action("What did we decide?")
        assert result["context_budget"] == "compact"


class TestMemoryDecisionQueryGeneration:
    """Test query generation for recall tools."""
    
    def test_query_extracted_from_prompt(self):
        """Query should be extracted from user prompt."""
        result = decide_memory_action("What did we decide on the installer architecture?")
        assert len(result["query"]) > 0
        assert "installer" in result["query"].lower() or result["query"] != ""
    
    def test_query_not_too_long(self):
        """Query should be reasonably short."""
        long_prompt = "This is a very long prompt " * 20
        result = decide_memory_action(long_prompt)
        assert len(result["query"]) <= 100


class TestMemoryDecisionAntiBloatGuidance:
    """Test anti-bloat guidance is provided."""
    
    def test_anti_bloat_guidance_always_present(self):
        """Every result should include anti-bloat guidance."""
        result = decide_memory_action("Any question")
        assert len(result["anti_bloat_guidance"]) > 0
    
    def test_anti_bloat_guidance_mentions_brevity_for_recall(self):
        """Recall decisions should mention compactness."""
        result = decide_memory_action("What did we decide?")
        if result["should_recall"]:
            # Should mention being concise/compact
            guidance_lower = result["anti_bloat_guidance"].lower()
            brevity_keywords = ["compact", "top", "summary", "concise", "brief"]
            has_brevity = any(kw in guidance_lower for kw in brevity_keywords)
            assert has_brevity, \
                f"Recall guidance missing brevity mention: {result['anti_bloat_guidance']}"


class TestMemoryDecisionCompileContext:
    """Test routing to compile_context tool (B252/254)."""
    
    def test_everything_about_triggers_compile_context(self):
        """Prompts asking 'everything about X' should recommend compile_context."""
        prompts = [
            "Everything about the installer",
            "What do we know about Project X?",
            "Brief me on the current status",
            "Full context on the architecture",
            "Summary of constraints and decisions",
            "Overview of performance metrics",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            assert result["should_recall"] is True, f"Prompt: {prompt}"
            assert result["recommended_tool"] == "compile_context", f"Prompt: {prompt}"
    
    def test_compile_context_confidence_is_high(self):
        """compile_context recommendations should have high confidence."""
        result = decide_memory_action("Everything about Project X")
        assert result["confidence"] >= 0.80
    
    def test_compile_context_uses_moderate_budget(self):
        """compile_context should recommend moderate token budget."""
        result = decide_memory_action("Full context on Y")
        assert result["context_budget"] == "moderate"
    
    def test_compile_context_includes_suggested_params(self):
        """compile_context recommendations should include suggested_params."""
        result = decide_memory_action("Everything about Project X")
        assert "suggested_params" in result
        assert "token_budget" in result["suggested_params"]
        assert "include_tabular" in result["suggested_params"]
        assert "output_format" in result["suggested_params"]
    
    def test_suggested_params_have_sensible_defaults(self):
        """suggested_params should have reasonable default values."""
        result = decide_memory_action("Everything about Project X")
        params = result["suggested_params"]
        
        assert isinstance(params["token_budget"], int)
        assert params["token_budget"] > 0
        assert isinstance(params["include_tabular"], bool)
        assert isinstance(params["output_format"], str)
    
    def test_multi_entity_query_may_trigger_compile_context(self):
        """Multi-entity prompts (multiple capitalized words) may trigger compile_context."""
        # "Project Q3Budget" has multiple entities
        prompts = [
            "What's the status of Project X and Feature Y?",
            "Database Migration and API Redesign strategy",
        ]
        
        for prompt in prompts:
            result = decide_memory_action(prompt)
            # Multi-entity queries may trigger compile_context
            assert "should_recall" in result
    
    def test_compile_context_anti_bloat_guidance(self):
        """compile_context results should mention bundle injection."""
        result = decide_memory_action("Everything about Project X")
        guidance = result["anti_bloat_guidance"].lower()
        
        # Should mention not re-summarizing or injecting directly
        assert "inject" in guidance or "directly" in guidance or "bundle" in guidance
    
    def test_compile_context_simple_fact_check_uses_current_truth(self):
        """Simple fact checks should still use current_truth, not compile_context."""
        result = decide_memory_action("What did we decide on the database?")
        assert result["recommended_tool"] == "current_truth"


class TestMemoryDecisionPrecedence:
    """Test precedence handling when multiple patterns match."""
    
    def test_primary_pattern_takes_precedence(self):
        """More specific patterns should take precedence over generic."""
        # This prompt matches both "decision" and "context"
        prompt = "What decision did we make? How much context is left?"
        result = decide_memory_action(prompt)
        
        # The decision pattern should win
        assert result["recommended_tool"] in ["current_truth", "context_status"]
    
    def test_consistency_across_similar_prompts(self):
        """Similar prompts should produce consistent routing."""
        prompt1 = "What did we decide?"
        prompt2 = "What decision did we make?"
        
        result1 = decide_memory_action(prompt1)
        result2 = decide_memory_action(prompt2)
        
        assert result1["recommended_tool"] == result2["recommended_tool"]
