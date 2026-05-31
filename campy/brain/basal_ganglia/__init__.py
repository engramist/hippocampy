"""Basal Ganglia — Procedural learning, action selection, reward prediction.

The basal ganglia handles:
- Frustration cluster detection → avoidance Procedures (no LLM)
- Enhanced Plan clustering → automation Procedures (LLM-assisted)
- Procedure maturity lifecycle (nascent → developing → mature → degraded → archived)
- Action selection / Go/No-Go gating based on accumulated graph evidence
- Reward prediction error tracking (predicted vs actual outcome delta)
- Exploration vs exploitation policy

Brain analogy: The basal ganglia is the brain's advisory gate for action
selection. It learns which actions are rewarded and which cause pain,
forming habits (Procedures) and avoidance patterns automatically.
"""
