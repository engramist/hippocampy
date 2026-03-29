from pathlib import Path

EXTENSION_SRC = (
    Path(__file__).parent.parent
    / "extensions"
    / "sidequests-brain"
    / "src"
    / "index.ts"
)


def _source() -> str:
    return EXTENSION_SRC.read_text()


def test_contract_exists_in_source():
    src = _source()
    assert "const OPENCLAW_EVENT_CONTRACT =" in src


def test_contract_includes_expected_events():
    src = _source()
    assert 'userTurnEvent: "llm_input"' in src
    assert 'assistantTurnEvent: "llm_output"' in src
    assert 'preAgentEvent: "before_agent_start"' in src


def test_normalize_prompt_payload_exists():
    src = _source()
    assert "function normalizePromptPayload" in src


def test_normalize_assistant_payload_exists():
    src = _source()
    assert "function normalizeAssistantPayload" in src


def test_summarize_event_shape_exists():
    src = _source()
    assert "function summarizeEventShape" in src


def test_user_capture_uses_contract_constant():
    src = _source()
    # Should use OPENCLAW_EVENT_CONTRACT.userTurnEvent
    assert "api.on(OPENCLAW_EVENT_CONTRACT.userTurnEvent" in src
    # Should NOT use raw string for registration
    assert 'api.on("llm_input"' not in src


def test_assistant_capture_uses_contract_constant():
    src = _source()
    # Should use OPENCLAW_EVENT_CONTRACT.assistantTurnEvent
    assert "api.on(OPENCLAW_EVENT_CONTRACT.assistantTurnEvent" in src
    # Should NOT use raw string for registration
    assert 'api.on("llm_output"' not in src


def test_auto_recall_uses_contract_constant():
    src = _source()
    # Should use OPENCLAW_EVENT_CONTRACT.preAgentEvent
    assert "api.on(OPENCLAW_EVENT_CONTRACT.preAgentEvent" in src
    # Should NOT use raw string for registration
    assert 'api.on("before_agent_start"' not in src


def test_user_capture_calls_notify_turn_with_user_role():
    src = _source()
    # Find the block for userTurnEvent and verify it calls notify_turn with role "user"
    user_block = src[src.find("api.on(OPENCLAW_EVENT_CONTRACT.userTurnEvent"):]
    user_block = user_block[:user_block.find("});", user_block.find("brain.callTool"))]
    assert 'role: "user"' in user_block
    assert 'brain.callTool("notify_turn"' in user_block


def test_assistant_capture_calls_notify_turn_with_assistant_role():
    src = _source()
    # Find the block for assistantTurnEvent and verify it calls notify_turn with role "assistant"
    assistant_block = src[src.find("api.on(OPENCLAW_EVENT_CONTRACT.assistantTurnEvent"):]
    assistant_block = assistant_block[:assistant_block.find("});", assistant_block.find("brain.callTool"))]
    assert 'role: "assistant"' in assistant_block
    assert 'brain.callTool("notify_turn"' in assistant_block


def test_auto_recall_calls_current_truth():
    src = _source()
    # Find the block for preAgentEvent and verify it calls current_truth
    # We look for the start of the handler and search for current_truth within a reasonable window
    start_idx = src.find("api.on(OPENCLAW_EVENT_CONTRACT.preAgentEvent")
    assert start_idx != -1
    recall_block = src[start_idx : start_idx + 2000] # search next 2000 chars
    assert 'brain.callTool("current_truth"' in recall_block


def test_diagnostic_logging_mentions_event_firing_or_skips():
    src = _source()
    assert "fired (${summarizeEventShape(event)})" in src
    assert "produced no usable content" in src


def test_explicit_fallback_for_unusable_prompt_payload():
    src = _source()
    # normalizePromptPayload returns null if prompt is missing or empty
    assert "if (prompt === undefined || prompt === null) return null" in src
    assert "normalized.trim().length > 0 ? normalized : null" in src
    # Hooks handle null by logging warning
    assert "console.warn(" in src
    assert "produced no usable content" in src


def test_explicit_fallback_for_unusable_assistant_payload():
    src = _source()
    # normalizeAssistantPayload returns null if texts is missing or empty
    assert "if (texts === undefined || texts === null) return null" in src
    assert "normalized.trim().length > 0 ? normalized : null" in src
    # Hooks handle null by logging warning
    assert "console.warn(" in src
    assert "produced no usable content" in src
