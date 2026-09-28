from datetime import datetime, timezone

import pytest

from app.services.investigation_service import InvestigationService
from app.services.reasoning_service import ReasoningService


class FakeRepository:
    def __init__(self, room):
        self.room = room
        self.save_count = 0

    def get(self, room_id):
        return self.room if room_id == self.room["id"] else None

    def save(self, room_id):
        self.save_count += 1
        return self.room


class FakeBundleLoader:
    def __init__(self, bundle):
        self.bundle = bundle

    def load(self, script_id, version):
        return self.bundle


@pytest.fixture
def room():
    return {
        "id": "ROOM1",
        "status": "playing",
        "script_id": "macbeth",
        "script_version": 1,
        "players": [{"id": "PLAYER1", "clue_ids": []}],
        "game": {"stage_id": "investigation"},
    }


@pytest.fixture
def bundle():
    return {
        "locations": {
            "locations": [
                {
                    "id": "crime_scene",
                    "entry_narration": "壁炉灰烬尚温。",
                    "searchable_objects": [
                        {
                            "name": "壁炉灰烬",
                            "aliases": ["灰烬"],
                            "result": {
                                "type": "clue",
                                "clue_id": "clue_10",
                                "message": "你发现一枚戒指。",
                            },
                        },
                        {
                            "name": "酒杯",
                            "result": {
                                "type": "text",
                                "message": "没有更多发现。",
                            },
                        },
                    ],
                }
            ],
            "ambient_locations": [{"id": "hall", "description": "大厅空旷。"}],
        },
        "unlock_rules": [
            {
                "id": "rule_1",
                "allowed_stages": ["investigation"],
                "once": True,
                "unlock_clues": ["clue_5"],
                "private_message": "你拼出了新的线索。",
            }
        ],
    }


def test_investigation_location_and_object_are_stage_bound(room, bundle):
    repository = FakeRepository(room)
    service = InvestigationService(repository, FakeBundleLoader(bundle))

    entry = service.enter_location("ROOM1", "PLAYER1", "crime_scene")
    assert entry["channel"] == "PRIVATE_MESSAGE"

    found = service.inspect_object("ROOM1", "PLAYER1", "crime_scene", "灰烬")
    assert found["clue_id"] == "clue_10"
    assert room["players"][0]["clue_ids"] == ["clue_10"]

    repeated = service.inspect_object("ROOM1", "PLAYER1", "crime_scene", "壁炉灰烬")
    assert repeated["clue_id"] is None
    assert "已经被" in repeated["message"]


def test_ambient_location_never_releases_clue(room, bundle):
    repository = FakeRepository(room)
    service = InvestigationService(repository, FakeBundleLoader(bundle))

    result = service.inspect_object("ROOM1", "PLAYER1", "hall", "墙壁")
    assert result["clue_id"] is None
    assert result["message"] == "没有更多发现。"


def test_reasoning_rule_is_idempotent(room, bundle):
    repository = FakeRepository(room)
    service = ReasoningService(repository, FakeBundleLoader(bundle))

    first = service.unlock_rule("ROOM1", "PLAYER1", "rule_1", "合理推理")
    assert first["clue_ids"] == ["clue_5"]
    assert room["players"][0]["clue_ids"] == ["clue_5"]

    second = service.unlock_rule("ROOM1", "PLAYER1", "rule_1", "再次提交")
    assert second["status"] == "already_triggered"
    assert room["players"][0]["clue_ids"] == ["clue_5"]


def test_reasoning_rule_rejects_wrong_stage(room, bundle):
    room["game"]["stage_id"] = "voting"
    service = ReasoningService(FakeRepository(room), FakeBundleLoader(bundle))

    with pytest.raises(ValueError, match="not allowed"):
        service.unlock_rule("ROOM1", "PLAYER1", "rule_1", "推理")
