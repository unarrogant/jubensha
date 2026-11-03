"""Application-facing abstractions used for dependency inversion.

These protocols describe capabilities, not implementations. The application
layer depends on them; infrastructure adapters explicitly implement them.
"""

from collections.abc import Callable
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver


class RoomRepositoryPort(Protocol):
    """Room snapshot and immutable event persistence capabilities."""

    def get(self, room_id: str) -> dict[str, Any] | None: ...

    def save(self, room_id: str) -> dict[str, Any] | None: ...

    def record_event(
        self,
        room_id: str,
        event_type: str,
        *,
        actor_player_id: str | None = None,
        target_player_id: str | None = None,
        payload: dict[str, Any] | None = None,
        visibility: str = "admin",
    ) -> dict[str, Any] | None: ...


class ScriptBundlePort(Protocol):
    """Read-only access to a versioned script bundle."""

    def load(self, script_id: str, version: int | None = None) -> dict[str, Any]: ...


class IdempotencyPort(Protocol):
    """Execute a side effect at most once for a command identifier."""

    def execute(
        self,
        command_id: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]: ...


class EventPublisherPort(Protocol):
    """Publish a domain/application event to connected clients."""

    async def broadcast_room(
        self,
        room_id: str,
        event: dict[str, Any],
        exclude_player_id: str | None = None,
    ) -> None: ...

    async def send_to_player(
        self,
        room_id: str,
        player_id: str,
        event: dict[str, Any],
    ) -> None: ...


class CheckpointFactoryPort(Protocol):
    """Create the LangGraph checkpoint store used by AgentRuntime."""

    def build(self) -> BaseCheckpointSaver: ...


class RoomExecutionLockPort(Protocol):
    """Distributed mutex for one room workflow transition."""

    def acquire(
        self,
        room_id: str,
        purpose: str,
        ttl_seconds: int = 60,
    ) -> str | None: ...

    def release(
        self,
        room_id: str,
        purpose: str,
        token: str,
    ) -> None: ...


__all__ = [
    "CheckpointFactoryPort",
    "EventPublisherPort",
    "IdempotencyPort",
    "RoomRepositoryPort",
    "RoomExecutionLockPort",
    "ScriptBundlePort",
]
