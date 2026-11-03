import json

from app.infrastructure.agent.idempotency import IdempotencyService


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


def test_repeated_command_returns_first_result_without_reexecution():
    service = IdempotencyService.__new__(IdempotencyService)
    service._client = FakeRedis()
    calls = []

    def operation():
        calls.append("executed")
        return {"status": "success", "clue_ids": ["clue_10"]}

    first = service.execute("command-1", operation)
    second = service.execute("command-1", operation)

    assert first == second
    assert calls == ["executed"]
    record = json.loads(service._client.get(service._key("command-1")))
    assert record["status"] == "completed"


def test_failed_command_can_be_retried():
    service = IdempotencyService.__new__(IdempotencyService)
    service._client = FakeRedis()
    attempts = []

    def failing_operation():
        attempts.append("failed")
        raise RuntimeError("temporary failure")

    try:
        service.execute("command-2", failing_operation)
    except RuntimeError:
        pass

    assert service._client.get(service._key("command-2")) is None
