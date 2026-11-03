import pytest

from app.domain.agent.policy import PolicyService


def player_state(stage_id: str, **stage_fields):
    return {
        "request_type": "player_private",
        "player_id": "player-1",
        "context": {
            "GAME_STATE": {"stage_id": stage_id},
            "CURRENT_STAGE": {"id": stage_id, **stage_fields},
        },
    }


def test_investigation_allows_search_tools():
    policy = PolicyService()
    state = player_state("investigation")

    policy.assert_tool_allowed(state, "enter_location")
    policy.assert_tool_allowed(state, "inspect_object")
    policy.assert_tool_allowed(state, "unlock_reasoning_rule")


def test_voting_rejects_search_and_reasoning():
    policy = PolicyService()
    state = player_state("voting")

    for tool_name in ("enter_location", "inspect_object", "unlock_reasoning_rule"):
        with pytest.raises(ValueError):
            policy.assert_tool_allowed(state, tool_name)


def test_stage_forbidden_action_wins_over_default_allowlist():
    policy = PolicyService()
    state = player_state(
        "investigation",
        forbidden_actions=["inspect_object"],
    )

    with pytest.raises(ValueError):
        policy.assert_tool_allowed(state, "inspect_object")


def test_player_tool_results_cannot_become_public():
    policy = PolicyService()
    state = player_state("investigation")

    assert policy.resolve_visibility(
        state,
        "inspect_object",
        {"channel": "PUBLIC_MESSAGE"},
    ) == "private"


def test_public_event_can_publish_only_explicit_public_channel():
    policy = PolicyService()
    state = {"request_type": "public_event"}

    assert policy.resolve_visibility(
        state,
        "stage_change",
        {"channel": "PUBLIC_MESSAGE"},
    ) == "public"
    assert policy.resolve_visibility(
        state,
        "stage_change",
        {"channel": "PRIVATE_MESSAGE"},
    ) == "private"
