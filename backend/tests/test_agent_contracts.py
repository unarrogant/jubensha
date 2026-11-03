from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.dm_agent import (
    AgentDecision,
    AgentRequest,
    AgentRun,
    AuditEvent,
    ToolCommand,
    ToolResult,
)


def test_agent_request_requires_a_valid_boundary():
    request = AgentRequest(
        room_id="ROOM-1",
        player_id="PLAYER-1",
        request_type="player_private",
        thread_id="ROOM-1:PLAYER-1:v2",
        player_message="我想检查壁炉。",
        context={"CURRENT_STAGE": {"id": "investigation"}},
    )

    assert request.request_type == "player_private"
    assert request.context["CURRENT_STAGE"]["id"] == "investigation"


def test_agent_request_rejects_unknown_request_type():
    with pytest.raises(ValidationError):
        AgentRequest(
            room_id="ROOM-1",
            request_type="unknown",
            thread_id="ROOM-1:public",
        )


def test_tool_result_and_decision_have_stable_shapes():
    tool_result = ToolResult(
        status="success",
        visibility="private",
        clue_ids=["clue_10"],
        data={"location_id": "crime_scene"},
    )
    decision = AgentDecision(
        visibility="private",
        response="你在灰烬中发现了一枚戒指。",
        clue_ids=tool_result.clue_ids,
        tool_used=True,
        tool_name="inspect_object",
        tool_status=tool_result.status,
        tool_data=tool_result.data,
    )

    assert decision.response
    assert decision.tool_data["location_id"] == "crime_scene"


def test_agent_run_and_audit_event_can_be_persisted():
    now = datetime.now(timezone.utc)
    run = AgentRun(
        run_id="run-1",
        room_id="ROOM-1",
        request_type="public_event",
        started_at=now,
    )
    event = AuditEvent(
        event_id="event-1",
        run_id=run.run_id,
        room_id=run.room_id,
        event_type="AGENT_DECISION",
        created_at=now,
        payload={"tool_used": False},
    )

    assert event.run_id == run.run_id
    assert run.status == "running"


def test_tool_command_has_optional_idempotency_key():
    command = ToolCommand(
        name="release_clue",
        arguments={"clue_id": "clue_10"},
        command_id="command-1",
    )

    assert command.command_id == "command-1"
