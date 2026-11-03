from app.config import get_storage_config
from app.interfaces.ports import CheckpointFactoryPort
from langgraph.checkpoint.base import BaseCheckpointSaver


class RedisCheckpointFactory(CheckpointFactoryPort):
    """Build the production LangGraph checkpointer backed by Redis."""

    def build(self) -> BaseCheckpointSaver:
        try:
            from redis import Redis
            from langgraph.checkpoint.redis import RedisSaver
        except ImportError as error:
            raise RuntimeError(
                "Redis 持久化需要安装 redis 和 langgraph-checkpoint-redis"
            ) from error

        client = Redis.from_url(
            get_storage_config()["redis_url"],
            decode_responses=False,
        )
        checkpointer: BaseCheckpointSaver = RedisSaver(redis_client=client)
        checkpointer.setup()
        return checkpointer
