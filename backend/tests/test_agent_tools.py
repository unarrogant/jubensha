import pytest
from pydantic import ValidationError

from app.agent.tools import _agent_tool_result, _assert_player_tool_allowed, build_dm_tools
from app.schemas.dm_agent import (
    AgentToolResult,
    EnterLocationArgs,
    InspectObjectArgs,
    UnlockReasoningArgs,
)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (EnterLocationArgs, {"location_id": ""}),
        (EnterLocationArgs, {"location_id": "x" * 101}),
        (InspectObjectArgs, {"location_id": "crime_scene", "object_text": ""}),
        (
            InspectObjectArgs,
            {"location_id": "crime_scene", "object_text": "x" * 101},
        ),
        (UnlockReasoningArgs, {"rule_id": "rule_1", "reasoning": ""}),
        (
            UnlockReasoningArgs,
            {"rule_id": "rule_1", "reasoning": "x" * 2001},
        ),
    ],
)
def test_tool_argument_schemas_reject_invalid_values(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_tool_schemas_hide_injected_state_from_model():
    tools = build_dm_tools(
        room_repository=object(),
        investigation_service=object(),
        reasoning_service=object(),
    )
    schemas = {tool.name: tool.args_schema.model_fields for tool in tools}

    assert list(schemas["get_game_state"]) == []
    assert list(schemas["enter_location"]) == ["location_id"]
    assert list(schemas["inspect_object"]) == ["location_id", "object_text"]
    assert list(schemas["unlock_reasoning_rule"]) == ["rule_id", "reasoning"]
    assert all("state" not in schema for schema in schemas.values())


@pytest.mark.parametrize(
    ("state", "tool_name"),
    [
        ({"request_type": "public_event", "player_id": "p"}, "inspect_object"),
        ({"request_type": "player_private"}, "inspect_object"),
        (
            {
                "request_type": "player_private",
                "player_id": "p",
                "context": {"GAME_STATE": {"stage_id": "voting"}},
            },
            "inspect_object",
        ),
        (
            {
                "request_type": "player_private",
                "player_id": "p",
                "context": {"GAME_STATE": {"stage_id": "intro"}},
            },
            "enter_location",
        ),
    ],
)
def test_tool_permission_guard_rejects_invalid_request(state, tool_name):
    with pytest.raises(ValueError):
        _assert_player_tool_allowed(state, tool_name)


def test_tool_permission_guard_allows_player_in_investigation():
    state = {
        "request_type": "player_private",
        "player_id": "p",
        "context": {"GAME_STATE": {"stage_id": "investigation"}},
    }

    _assert_player_tool_allowed(state, "inspect_object")


def test_tool_result_uses_stable_schema_and_normalizes_clue_id():
    result = _agent_tool_result(
        {
            "channel": "PRIVATE_MESSAGE",
            "message": "找到戒指",
            "clue_id": "clue_10",
            "rule_id": "rule_1",
            "delivery": "triggering_player",
        }
    )

    parsed = AgentToolResult.model_validate(result)
    assert parsed.status == "success"
    assert parsed.visibility == "private"
    assert parsed.message == "找到戒指"
    assert parsed.clue_ids == ["clue_10"]
    assert parsed.data == {
        "rule_id": "rule_1",
        "delivery": "triggering_player",
    }


def test_already_triggered_tool_result_preserves_status():
    result = _agent_tool_result(
        {
            "channel": "PRIVATE_MESSAGE",
            "status": "already_triggered",
            "message": None,
            "clue_ids": [],
        }
    )

    assert AgentToolResult.model_validate(result).status == "already_triggered"
