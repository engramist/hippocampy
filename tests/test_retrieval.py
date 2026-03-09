"""
Tests for current_truth retrieval (M2+).

  - test_current_truth_basic: query returns ranked results
  - test_current_truth_branch_scope: only returns nodes from current quest
  - test_current_truth_global_scope: includes GlobalConstraint nodes
  - test_current_truth_excludes_archived: archived nodes never surface
  - test_current_truth_confidence_low_ranks_lower: tentative nodes rank below confirmed
  - test_vector_search_multi_table: UNION ALL returns results across artifact types
"""
