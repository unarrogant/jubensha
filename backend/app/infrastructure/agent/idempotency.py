import json
from collections.abc import Callable
from typing import Any

from app.config import get_storage_config
from app.interfaces.ports import IdempotencyPort


class IdempotencyService(IdempotencyPort):
    """Deduplicate Agent commands and return the first completed result."""

    CLAIM_TTL_SECONDS = 300
    RESULT_TTL_SECONDS = 24 * 60 * 60

    def __init__(self, redis_url: str | None = None):
        try:
            from redis import Redis
        except ImportError as error:
            raise RuntimeError("工具幂等性需要安装 redis 客户端") from error

        self._client = Redis.from_url(
            redis_url or get_storage_config()["redis_url"],
            decode_responses=True,
        )

    @staticmethod
    def _key(command_id: str) -> str:
        return f"script-kill:agent-command:{command_id}"

    def execute(
        self,
        command_id: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        key = self._key(command_id)
        existing = self._client.get(key)
        if existing:
            record = json.loads(existing)
            if record.get("status") == "completed":
                result = record.get("result")
                if isinstance(result, dict):
                    return result
            raise ValueError("相同工具命令正在执行，请勿重复提交")

        claimed = self._client.set(
            key,
            json.dumps({"status": "running"}, ensure_ascii=False),
            nx=True,
            ex=self.CLAIM_TTL_SECONDS,
        )
        if not claimed:
            existing = self._client.get(key)
            if existing:
                record = json.loads(existing)
                if record.get("status") == "completed" and isinstance(record.get("result"), dict):
                    return record["result"]
            raise ValueError("相同工具命令正在执行，请勿重复提交")

        try:
            result = operation()
            self._client.set(
                key,
                json.dumps(
                    {"status": "completed", "result": result},
                    ensure_ascii=False,
                    default=str,
                ),
                ex=self.RESULT_TTL_SECONDS,
            )
            return result
        except Exception:
            # If no side effect completed, allow a later request to retry.
            self._client.delete(key)
            raise
