from app.infrastructure.agent.idempotency import IdempotencyService
from app.domain.agent.policy import PolicyService
from app.application.agent.tool_executor import ToolExecutor


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


def test_executor_applies_policy_and_deduplicates_side_effects():
    idempotency = IdempotencyService.__new__(IdempotencyService)
    idempotency._client = FakeRedis()
    executor = ToolExecutor(PolicyService(), idempotency)
    state = {
        "request_id": "request-1",
        "request_type": "player_private",
        "player_id": "player-1",
        "context": {"GAME_STATE": {"stage_id": "investigation"}},
    }
    calls = []

    def operation():
        calls.append("called")
        return {
            "channel": "PRIVATE_MESSAGE",
            "message": "发现戒指",
            "clue_id": "clue_10",
        }

    first = executor.execute(
        state,
        "inspect_object",
        {"location_id": "crime_scene", "object_text": "灰烬"},
        operation,
    )
    second = executor.execute(
        state,
        "inspect_object",
        {"location_id": "crime_scene", "object_text": "灰烬"},
        operation,
    )

    assert first == second
    assert calls == ["called"]
    assert first["visibility"] == "private"
    assert first["clue_ids"] == ["clue_10"]


def test_executor_rejects_forbidden_stage_before_operation():
    idempotency = IdempotencyService.__new__(IdempotencyService)
    idempotency._client = FakeRedis()
    executor = ToolExecutor(PolicyService(), idempotency)
    state = {
        "request_id": "request-2",
        "request_type": "player_private",
        "player_id": "player-1",
        "context": {"GAME_STATE": {"stage_id": "voting"}},
    }

    try:
        executor.execute(state, "inspect_object", {}, lambda: {})
    except ValueError as error:
        assert "不允许" in str(error)
    else:
        raise AssertionError("forbidden tool was executed")
