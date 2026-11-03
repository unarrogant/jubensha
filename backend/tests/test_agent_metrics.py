from app.application.agent.metrics import AgentMetrics


class FakeRoomRepository:
    def __init__(self):
        self.room = {"id": "ROOM-1"}

    def get(self, room_id):
        return self.room if room_id == "ROOM-1" else None

    def save(self, room_id):
        return self.room


def test_metrics_aggregate_latency_tools_recovery_and_tokens():
    repository = FakeRoomRepository()
    metrics = AgentMetrics(repository)

    metrics.record_run(
        "ROOM-1",
        elapsed_ms=120.5,
        status="success",
        recovered=True,
        tool_status="success",
        clue_count=1,
        input_tokens=100,
        output_tokens=40,
    )
    metrics.record_run(
        "ROOM-1",
        elapsed_ms=79.5,
        status="success",
        tool_status="already_triggered",
    )

    assert repository.room["agent_metrics"] == {
        "run_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "recovered_count": 1,
        "total_latency_ms": 200.0,
        "avg_latency_ms": 100.0,
        "tool_success_count": 1,
        "tool_rejected_count": 0,
        "tool_duplicate_count": 1,
        "clue_release_count": 1,
        "input_tokens": 100,
        "output_tokens": 40,
    }


def test_metrics_reads_provider_usage_metadata():
    class Message:
        usage_metadata = {"input_tokens": 12, "output_tokens": 8}

    assert AgentMetrics.token_usage({"messages": [Message()]}) == (12, 8)
