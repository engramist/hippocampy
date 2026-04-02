"""ARC3 prompt constants — Layer 4 (Prompt & Knowledge).

All prompt templates used by the orchestrator and solver live here.
Imported by runtime modules; never defined inline.
"""

# orchestrator.py build_action_packet() — SYSTEM block
SYSTEM_PROMPT = (
    "SYSTEM: You are an ARC puzzle solver. "
    "Treat action ids as opaque operators until this puzzle provides evidence about their effects. "
    "Available actions: {available_actions}. "
    "If you choose ACTION6, you must also return integer x and y coordinates."
)

# orchestrator.py build_action_packet() — INSTRUCTION block
INSTRUCTION_TEMPLATE = (
    "INSTRUCTION: {effect_summary}"
    "What should you try next? "
    "Choose the next valid action based on observed effects. "
    "Start in an exploration phase: until each available action has at least one observed effect, prefer untested actions. "
    "Prefer actions with strong_progress or tentative_progress evidence. "
    "Treat no_progress evidence as a reason to switch actions unless reward improved. "
    "Use an UNTESTED action when repeated actions are low-value or looped. "
    "If the top tested actions both decay into low_value or no_progress, broaden exploration instead of bouncing between them. "
    "After 2 consecutive zero-reward tentative steps on the same action, require stronger evidence than before or switch. "
    "Do not let a memory-only first move override the current observation unless the memory clearly matches this puzzle. "
    "Do not invent human labels for actions beyond the observed effects. "
    "If you choose ACTION6, include integer x and y fields targeting a salient cell. "
    "Respond with JSON {{\"action_id\":..., \"rationale\":..., \"x\":..., \"y\":...}}, and make the rationale cite one observed effect label or say UNTESTED."
)

# orchestrator.py _mental_sandbox_loop() — sandbox instruction appended to prompt
SANDBOX_INSTRUCTION = (
    "\n\nMENTAL SANDBOX: You can use the 'sandbox_thought' tool to peek at the consequences of an action "
    "based on known facts and plans before you commit. Respond with: "
    "{{\"thought\": \"I want to test ACTIONX\", \"sandbox_thought\": \"ACTIONX\"}} "
    "to use the tool, or provide your final choice as JSON {{\"action_id\":..., \"rationale\":..., \"x\":..., \"y\":...}}."
)

# B123: REPL Sandbox instruction
REPL_SANDBOX_INSTRUCTION = (
    "\n\nREPL SANDBOX: You can also use the 'repl_test' tool to verify grid logic or hypotheses with Python. "
    "Accepts a short snippet (numpy, math, collections, itertools are available). "
    "Respond with: {{\"thought\": \"logic to test\", \"repl_test\": \"print(grid_rotate(g))\"}} "
    "to use the REPL. Results appear in your next turn. No file/network allowed. 2s timeout."
)

# orchestrator.py _mental_sandbox_loop() / _query_llm() — system messages
SANDBOX_SYSTEM_MESSAGE = "You are an ARC reasoning assistant with a mental sandbox."
QUERY_LLM_SYSTEM_MESSAGE = "You are an ARC reasoning assistant."

# solver.py VictoryHypothesizer — hypothesis prompt
VICTORY_HYPOTHESIS_TEMPLATE = """You are analyzing an unknown game. Based on the evidence below,
hypothesize what the WINNING CONDITION is.

Game archetype: {archetype}

Object roles detected:
{object_roles}

Past successful plans with similar goals:
{past_plans}

Known game lessons:
{lessons}

Observed progress signals: {reward_summary}

Respond with EXACTLY this JSON format (no other text):
{{
  "condition_type": "<reach_goal|collect_all|survive|score_threshold|eliminate>",
  "description": "<one sentence describing the win condition>",
  "target_color_id": <integer color id or null>,
  "confidence": <0.0-1.0>
}}"""

# B126: Verification sub-agent — adversarial check after action proposal
VERIFIER_SYSTEM_PROMPT = "You are a critical verifier for ARC action decisions. Your job is to find flaws, not to agree."

VERIFIER_PROMPT_TEMPLATE = """ACTION VERIFICATION

Proposed action: {action_id}
Rationale: {rationale}

Current observation:
- State: {state}
- Colors: {colors}
- Shapes: {shapes}

Recent action history (last 3):
{recent_history}

Mental sandbox result (if available):
{sandbox_result}

Hypothesis context:
- Loop detected: {loop_detected}
- Top action facts: {action_facts_summary}

Your task: Identify ONE critical reason why this action might fail or be suboptimal RIGHT NOW.

If the action is sound, respond with EXACTLY: {{"approved": true}}

If the action has a critical issue, respond with EXACTLY: {{"approved": false, "reason": "ONE sentence reason why this fails"}}

Be adversarial. Find the flaw."""
