"""
Tests for Gated Consolidation Loop steps 1–7.

M3 tests:
  - test_step1_ner: spaCy extracts expected entity types
  - test_step1b_verb_patterns: verb pattern matching for all 5 types
  - test_step2_system1: high-similarity concept → correct gist class, no LLM call
  - test_step2_system2: ambiguous concept → LLM fallback triggered
  - test_step2_noise: low-similarity concept → noise exit
  - test_step3_routing: gist class → correct schema.org type + properties
  - test_step3b_semantic: Ollama extracts CHOSEN_OVER from typed entities
  - test_step4_confidence_gates: noise/confidence_low/hard-lock thresholds

M4 tests:
  - test_step5_branch_scope: retrieval finds existing node in same quest
  - test_step5_global_scope: falls through to GlobalConstraint
  - test_step6_additive: gray-zone arbitration returns additive
  - test_step6_contradiction: gray-zone arbitration returns contradiction
  - test_step7_strengthen: pathway_strength increments correctly
  - test_step7_deprecated_by: contradiction creates new node + edge
  - test_step7_merge_event: rollback delta pointers are correct
  - test_step7_co_occurs_with: edges written for all concept pairs
"""
