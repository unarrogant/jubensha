"""Redis-backed lock for cross-process room workflow transitions."""

from uuid import uuid4

from app.config import get_storage_config
from app.interfaces.ports import RoomExecutionLockPort


class RedisRoomExecutionLock(RoomExecutionLockPort):
    """Prevent two workers from advancing the same room at the same time."""

    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, redis_url: str | None = None):
        try:
            from redis import Redis
        except ImportError as error:
            raise RuntimeError("房间编排锁需要安装 redis") from error

        url = redis_url or get_storage_config()["redis_url"]
        self._client = Redis.from_url(url, decode_responses=True)

    @staticmethod
    def _key(room_id: str, purpose: str) -> str:
        return f"script-kill:room-lock:{room_id}:{purpose}"

    def acquire(
        self,
        room_id: str,
        purpose: str,
        ttl_seconds: int = 60,
    ) -> str | None:
        token = uuid4().hex
        acquired = self._client.set(
            self._key(room_id, purpose),
            token,
            nx=True,
            ex=max(1, int(ttl_seconds)),
        )
        return token if acquired else None

    def release(
        self,
        room_id: str,
        purpose: str,
        token: str,
    ) -> None:
        self._client.eval(
            self._RELEASE_SCRIPT,
            1,
            self._key(room_id, purpose),
            token,
        )


__all__ = ["RedisRoomExecutionLock"]
