from app.schemas.dm_agent import DMAgentResult
from app.application.agent.audit import AuditRecorder


class FakeRoomRepository:
    def __init__(self):
        self.room = {
            "id": "ROOM-1",
            "script_id": "macbeth",
            "script_version": "v1",
            "players": [
                {"id": "PLAYER-1", "name": "玩家一", "character_id": "macbeth"}
            ],
            "game": {"stage_id": "investigation"},
        }
        self.events = []

    def get(self, room_id):
        return self.room if room_id == self.room["id"] else None

    def save(self, room_id):
        return self.room

    def record_event(self, room_id, event_type, **kwargs):
        self.events.append((event_type, kwargs))


def test_audit_recorder_persists_exchange_and_side_effect_events():
    repository = FakeRoomRepository()
    result = DMAgentResult(
        visibility="private",
        response="你发现了一枚戒指。",
        clue_ids=["clue_10"],
        tool_used=True,
        tool_name="inspect_object",
        tool_status="success",
        tool_data={"location_id": "crime_scene"},
    )

    AuditRecorder(repository).record_player_exchange(
        room_id="ROOM-1",
        player_id="PLAYER-1",
        question="检查灰烬",
        result=result,
    )

    assert repository.room["agent_audit_log"][0]["question"] == "检查灰烬"
    assert [event[0] for event in repository.events] == [
        "DM_RESPONSE",
        "TOOL_CALLED",
        "CLUE_RELEASED",
    ]
