"""Room-level operational metrics for Agent runs."""

from typing import Any

from app.interfaces.ports import RoomRepositoryPort


class AgentMetrics:
    """Persist compact Agent counters without duplicating conversation logs."""

    def __init__(self, room_repository: RoomRepositoryPort):
        self.room_repository = room_repository

    def record_run(
        self,
        room_id: str,
        *,
        elapsed_ms: float,
        status: str,
        recovered: bool = False,
        tool_status: str | None = None,
        clue_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_code: str | None = None,
    ) -> None:
        room = self.room_repository.get(room_id)
        if room is None:
            return

        metrics = room.setdefault("agent_metrics", {})
        metrics.setdefault("run_count", 0)
        metrics.setdefault("success_count", 0)
        metrics.setdefault("failure_count", 0)
        metrics.setdefault("recovered_count", 0)
        metrics.setdefault("total_latency_ms", 0.0)
        metrics.setdefault("tool_success_count", 0)
        metrics.setdefault("tool_rejected_count", 0)
        metrics.setdefault("tool_duplicate_count", 0)
        metrics.setdefault("clue_release_count", 0)
        metrics.setdefault("input_tokens", 0)
        metrics.setdefault("output_tokens", 0)

        metrics["run_count"] += 1
        metrics["total_latency_ms"] += round(max(0.0, elapsed_ms), 2)
        if status == "success":
            metrics["success_count"] += 1
        else:
            metrics["failure_count"] += 1
        if recovered:
            metrics["recovered_count"] += 1
        if status != "success" and error_code:
            error_counts = metrics.setdefault("error_counts", {})
            error_counts[error_code] = error_counts.get(error_code, 0) + 1

        if tool_status in {"success", "completed"}:
            metrics["tool_success_count"] += 1
        elif tool_status in {"forbidden", "invalid_argument", "error"}:
            metrics["tool_rejected_count"] += 1
        elif tool_status == "already_triggered":
            metrics["tool_duplicate_count"] += 1

        metrics["clue_release_count"] += max(0, clue_count)
        metrics["input_tokens"] += max(0, input_tokens)
        metrics["output_tokens"] += max(0, output_tokens)
        metrics["avg_latency_ms"] = round(
            metrics["total_latency_ms"] / metrics["run_count"],
            2,
        )
        self.room_repository.save(room_id)

    @staticmethod
    def token_usage(result: dict[str, Any]) -> tuple[int, int]:
        """Extract provider usage metadata when the model exposes it."""
        input_tokens = 0
        output_tokens = 0
        for message in result.get("messages", []) or []:
            usage = getattr(message, "usage_metadata", None) or {}
            if not isinstance(usage, dict):
                continue
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
        return input_tokens, output_tokens
