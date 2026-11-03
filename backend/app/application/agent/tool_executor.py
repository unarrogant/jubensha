import hashlib
import json
from typing import Any, Callable

from app.agent.state import DMState
from app.schemas.dm_agent import AgentToolResult, ToolCommand
from app.domain.agent.policy import PolicyService
from app.interfaces.ports import IdempotencyPort


class ToolExecutor:
    """Execute Agent tools through one policy, visibility, and idempotency gate."""

    def __init__(
        self,
        policy_service: PolicyService,
        idempotency_service: IdempotencyPort,
    ):
        self.policy_service = policy_service
        self.idempotency_service = idempotency_service

    @staticmethod
    def command_id(
        state: DMState,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        request_id = state.get("request_id") or state.get("thread_id") or "legacy"
        digest = hashlib.sha256(
            json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:16]
        return f"{request_id}:{tool_name}:{digest}"

    def normalize_result(
        self,
        state: DMState,
        tool_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        channel = result.get("channel")
        visibility = self.policy_service.resolve_visibility(
            state,
            tool_name,
            result,
        )
        if visibility not in {"private", "public"}:
            visibility = "public" if channel == "PUBLIC_MESSAGE" else "private"

        clue_ids = result.get("clue_ids", [])
        if not isinstance(clue_ids, list):
            clue_ids = []
        clue_id = result.get("clue_id")
        if clue_id and clue_id not in clue_ids:
            clue_ids = [*clue_ids, clue_id]

        data = {
            key: value
            for key, value in result.items()
            if key not in {
                "channel",
                "message",
                "clue_id",
                "clue_ids",
                "status",
                "visibility",
                "data",
            }
        }
        if isinstance(result.get("data"), dict):
            data = {**result["data"], **data}

        return AgentToolResult(
            status=result.get("status") or "success",
            visibility=visibility,
            message=result.get("message"),
            clue_ids=clue_ids,
            data=data,
        ).model_dump()

    def execute(
        self,
        state: DMState,
        tool_name: str,
        arguments: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        self.policy_service.assert_tool_allowed(state, tool_name)
        command = ToolCommand(
            name=tool_name,
            arguments=arguments,
            command_id=self.command_id(state, tool_name, arguments),
        )
        return self.idempotency_service.execute(
            command.command_id,
            lambda: self.normalize_result(state, tool_name, operation()),
        )

    def read_only(
        self,
        state: DMState,
        tool_name: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        self.policy_service.assert_tool_allowed(state, tool_name)
        return self.normalize_result(state, tool_name, operation())
