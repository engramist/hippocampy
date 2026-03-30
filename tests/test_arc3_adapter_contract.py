"""Contract tests for the ARC3Adapter bridging ARC episodes to SideQuests."""

from __future__ import annotations

from typing import Mapping, Sequence

import pytest

from benchmarks.arc3.adapter import ARC3Adapter, BrainClientProtocol


class _MockBrainClient(BrainClientProtocol):
    def __init__(self) -> None:
        self.notify_calls: list[Mapping[str, object]] = []
        self.truth_calls: list[Mapping[str, object]] = []

    async def notify_turn(self, *, role: str, content: str, session_id: str) -> Mapping[str, object]:
        self.notify_calls.append({"role": role, "content": content, "session_id": session_id})
        return {"status": "queued"}

    async def current_truth(
        self, *, query: str, session_id: str, scope: str, limit: int
    ) -> Mapping[str, object]:
        payload = {"query": query, "session_id": session_id, "scope": scope, "limit": limit}
        self.truth_calls.append(payload)
        return {"results": [], **payload}


def _sample_grid() -> Sequence[Sequence[int]]:
    return [
        [[1, 1], [0, 2]],
    ]


def _sample_obs() -> Mapping[str, object]:
    return {
        "game_id": "arc-game",
        "guid": "task-101",
        "episode": 2,
        "frame": _sample_grid(),
    }


def _sample_action() -> Mapping[str, object]:
    return {"action_id": "action6", "x": 4, "y": 2, "value": 9, "prev_value": 3, "rationale": "paint"}


def test_normalize_observation_colors_and_shapes() -> None:
    adapter = ARC3Adapter(brain_client=_MockBrainClient(), session_id="session-abc")
    normalized = adapter.normalize_observation(_sample_obs())

    assert normalized["dataset_id"] == "arc-game"
    assert normalized["task_id"] == "task-101"
    assert normalized["episode_num"] == 2
    assert normalized["step_num"] == 1
    expected_colors = [
        {"value": 0, "count": 1},
        {"value": 1, "count": 2},
        {"value": 2, "count": 1},
    ]
    assert normalized["colors"] == expected_colors
    expected_shapes = [
        {"color": 0, "size": 1, "coords": [(1, 0)]},
        {"color": 1, "size": 2, "coords": [(0, 0), (0, 1)]},
        {"color": 2, "size": 1, "coords": [(1, 1)]},
    ]
    assert normalized["shapes"] == expected_shapes
    # Default values for new fields when not provided in raw response
    assert normalized["available_actions"] == []
    assert normalized["state"] == "NOT_STARTED"


def test_normalize_observation_passes_through_available_actions_and_state() -> None:
    adapter = ARC3Adapter(brain_client=_MockBrainClient(), session_id="session-abc")
    raw = dict(_sample_obs())
    raw["available_actions"] = ["ACTION1", "ACTION3", "ACTION6"]
    raw["state"] = "NOT_FINISHED"
    normalized = adapter.normalize_observation(raw)
    assert normalized["available_actions"] == ["ACTION1", "ACTION3", "ACTION6"]
    assert normalized["state"] == "NOT_FINISHED"


def test_normalize_action_deterministic_id() -> None:
    adapter = ARC3Adapter(brain_client=_MockBrainClient(), session_id="session-def")
    normalized = adapter.normalize_action(_sample_action())

    assert normalized["action_type"] == "ACTION6"
    assert normalized["grid_change"]["coords"] == [2, 4]
    assert normalized["deterministic_id"] == "ACTION6|coords=2:4|new=9|prev=3"


@pytest.mark.asyncio
async def test_ingest_step_calls_notify_and_current_truth() -> None:
    client = _MockBrainClient()
    adapter = ARC3Adapter(brain_client=client, session_id="session-ingest")
    result = await adapter.ingest_step(
        _sample_obs(),
        _sample_action(),
        reward=0.5,
        recall_query="what happened",
    )

    assert client.truth_calls == [
        {"query": "what happened", "session_id": "session-ingest", "scope": "branch", "limit": 5}
    ]
    assert len(client.notify_calls) == 1
    narrative = client.notify_calls[0]["content"]
    assert "Episode 2" in narrative
    assert "reward 0.50" in narrative
    assert adapter.step_num == 1
    trace = adapter.get_telemetry_trace()
    assert trace[0]["action"]["deterministic_id"] == "ACTION6|coords=2:4|new=9|prev=3"
    assert result["narrative"] == narrative
    assert result["memory"]["query"] == "what happened"


def test_malformed_action_rejected() -> None:
    adapter = ARC3Adapter(brain_client=_MockBrainClient(), session_id="session-invalid")
    with pytest.raises(ValueError):
        adapter.normalize_action({})


@pytest.mark.asyncio
async def test_replay_trace_is_deterministic() -> None:
    client = _MockBrainClient()
    adapter = ARC3Adapter(brain_client=client, session_id="session-trace")
    await adapter.ingest_step(_sample_obs(), _sample_action(), reward=1.0)
    first_trace = adapter.get_telemetry_trace()
    second_trace = adapter.get_telemetry_trace()
    assert first_trace == second_trace


def test_energy_estimate_small_grid() -> None:
    """Small grids (no HUD) should return energy=1.0."""
    adapter = ARC3Adapter(brain_client=_MockBrainClient(), session_id="s")
    normalized = adapter.normalize_observation({"frame": [[[0, 1], [2, 0]]]})
    assert normalized["energy_estimate"] == 1.0
