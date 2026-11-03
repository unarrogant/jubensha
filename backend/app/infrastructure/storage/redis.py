import json
from typing import Any


class RedisRoomStore:
    """Realtime room snapshots backed by Redis JSON values."""

    PREFIX = "script-kill:room:"

    def __init__(self, redis_url: str):
        try:
            import redis
        except ImportError as error:
            raise RuntimeError(
                "启用 Redis 前请安装 redis Python 客户端"
            ) from error

        self._client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
        )
        try:
            self._client.ping()
        except redis.RedisError as error:
            raise RuntimeError(
                "Redis 连接失败，请检查 REDIS_URL 和 Redis 服务状态"
            ) from error

    def _key(self, room_id: str) -> str:
        return f"{self.PREFIX}{room_id}"

    def save(self, room: dict[str, Any]) -> None:
        self._client.set(
            self._key(room["id"]),
            json.dumps(room, ensure_ascii=False, default=str),
        )

    def get(self, room_id: str) -> dict[str, Any] | None:
        value = self._client.get(self._key(room_id))
        return json.loads(value) if value else None

    def list_all(self) -> list[dict[str, Any]]:
        keys = self._client.scan_iter(match=f"{self.PREFIX}*")
        values = self._client.mget(list(keys))
        return [json.loads(value) for value in values if value]

    def delete(self, room_id: str) -> None:
        self._client.delete(self._key(room_id))

    def ping(self) -> bool:
        return bool(self._client.ping())
