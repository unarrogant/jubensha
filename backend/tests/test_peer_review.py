import pytest

from app.services.game_service import GameService


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
    def load(self, script_id, version):
        return {
            "characters": [
                {"id": "c1", "name": "Macbeth"},
                {"id": "c2", "name": "Banquo"},
                {"id": "c3", "name": "Malcolm"},
            ]
        }


@pytest.fixture
def service():
    room = {
        "id": "ROOM1",
        "script_id": "macbeth",
        "script_version": 1,
        "game": {"stage_id": "ending"},
        "players": [
            {"id": "p1", "name": "Alice", "character_id": "c1"},
            {"id": "p2", "name": "Bob", "character_id": "c2"},
            {"id": "p3", "name": "Carol", "character_id": "c3"},
        ],
        "peer_reviews": {},
    }
    return GameService(FakeRepository(room), FakeBundleLoader())


def test_peer_review_rejects_self_vote(service):
    with pytest.raises(ValueError, match="cannot vote for yourself"):
        service.submit_peer_review("ROOM1", "p1", "p1", "p2")


def test_peer_review_reveals_two_awards_after_every_player_votes(service):
    service.submit_peer_review("ROOM1", "p1", "p2", "p3")
    service.submit_peer_review("ROOM1", "p2", "p1", "p3")

    waiting = service.get_peer_review_status("ROOM1", "p1")
    assert waiting["results_revealed"] is False
    assert waiting["best_speakers"] == []
    assert waiting["best_reasoners"] == []

    service.submit_peer_review("ROOM1", "p3", "p2", "p1")
    result = service.get_peer_review_status("ROOM1", "p1")

    assert result["results_revealed"] is True
    assert result["submitted_count"] == 3
    assert result["best_speakers"] == [
        {
            "player_id": "p2",
            "player_name": "Bob",
            "character_name": "Banquo",
            "votes": 2,
        }
    ]
    assert result["best_reasoners"] == [
        {
            "player_id": "p3",
            "player_name": "Carol",
            "character_name": "Malcolm",
            "votes": 2,
        }
    ]

