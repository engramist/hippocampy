"""
Tests for MCP adapters (M2+).

  - test_notify_turn_returns_immediately: response is always {"status": "queued"}
  - test_notify_turn_queued_on_daemon_down: local queue written when socket unavailable
  - test_hook_user_turn_forwarded: UserPromptSubmit hook sends correct payload
  - test_current_truth_mcp_schema: tool response matches JSON Schema
  - test_degraded_mode_offline_fragment: injected fragment changes when daemon down
"""
