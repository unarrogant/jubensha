"""Persistence boundary for Agent audit records."""

from datetime import datetime, timezone
from uuid import uuid4

from app.interfaces.ports import RoomRepositoryPort
from app.schemas.dm_agent import DMAgentResult


class AuditRecorder:
    """Record player/Agent exchanges and tool side effects for admins."""

    def __init__(self, room_repository: RoomRepositoryPort):
        self.room_repository = room_repository

    def record_player_exchange(
        self,
        room_id: str,
        player_id: str,
        question: str,
        result: DMAgentResult,
    ) -> None:
        room = self.room_repository.get(room_id)
        if room is None:
            return

        player = next(
            (item for item in room.get("players", []) if item.get("id") == player_id),
            {},
        )
        room.setdefault("agent_audit_log", []).append({
            "id": uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "player_id": player_id,
            "player_name": player.get("name"),
            "character_id": player.get("character_id"),
            "question": question,
            "answer": result.content,
            "visibility": result.visibility,
            "clue_ids": result.clue_ids,
            "tool_used": result.tool_used,
            "tool_name": result.tool_name,
            "tool_status": result.tool_status,
            "tool_data": result.tool_data,
        })
        self.room_repository.save(room_id)
        self.room_repository.record_event(
            room_id,
            "DM_RESPONSE",
            actor_player_id=player_id,
            payload={
                "question": question,
                "answer": result.content,
                "visibility": result.visibility,
                "clue_ids": result.clue_ids,
                "tool_used": result.tool_used,
                "tool_name": result.tool_name,
                "tool_status": result.tool_status,
                "tool_data": result.tool_data,
            },
        )

        if result.tool_used:
            self.room_repository.record_event(
                room_id,
                "TOOL_CALLED",
                actor_player_id=player_id,
                payload={
                    "tool_name": result.tool_name,
                    "tool_status": result.tool_status,
                    "tool_data": result.tool_data,
                },
            )

        for clue_id in result.clue_ids:
            self.room_repository.record_event(
                room_id,
                "CLUE_RELEASED",
                actor_player_id=player_id,
                target_player_id=player_id,
                payload={
                    "clue_id": clue_id,
                    "source": result.tool_name or "agent_response",
                },
            )

    def record_agent_run(
        self,
        room_id: str,
        *,
        run_id: str,
        request_type: str,
        player_id: str | None,
        stage_id: str | None,
        status: str,
        elapsed_ms: float,
        error_code: str | None = None,
        recovered: bool = False,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Persist operational metadata without duplicating LangGraph messages."""
        room = self.room_repository.get(room_id)
        if room is None:
            return

        run = {
            "run_id": run_id,
            "request_type": request_type,
            "player_id": player_id,
            "stage_id": stage_id,
            "status": status,
            "elapsed_ms": round(max(0.0, elapsed_ms), 2),
            "error_code": error_code,
            "recovered": recovered,
            "input_tokens": max(0, input_tokens),
            "output_tokens": max(0, output_tokens),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        room.setdefault("agent_runs", []).append(run)
        self.room_repository.save(room_id)
        self.room_repository.record_event(
            room_id,
            "AGENT_RUN",
            actor_player_id=player_id,
            payload=run,
            visibility="admin",
        )
