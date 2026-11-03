from typing import Annotated, Any, Callable

from langgraph.prebuilt import InjectedState
from langchain_core.tools import tool

from app.agent.state import DMState
from app.interfaces.ports import IdempotencyPort, RoomRepositoryPort
from app.schemas.dm_agent import (
    EmptyToolArgs,
    EnterLocationArgs,
    InspectObjectArgs,
    UnlockReasoningArgs,
)
from app.application.investigation.service import InvestigationService
from app.domain.agent.policy import PolicyService
from app.services.reasoning_service import ReasoningService
from app.application.agent.tool_executor import ToolExecutor

def _execute_idempotent(
    state: DMState,
    tool_name: str,
    arguments: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
    tool_executor: ToolExecutor,
) -> dict:
    return tool_executor.execute(
        state,
        tool_name,
        arguments,
        operation,
    )


def build_dm_tools(
    room_repository: RoomRepositoryPort,
    investigation_service: InvestigationService,
    reasoning_service:ReasoningService,
    idempotency_service: IdempotencyPort,
    policy_service: PolicyService | None = None,
):
    policy_service = policy_service or PolicyService()
    tool_executor = ToolExecutor(policy_service, idempotency_service)
    # Let LangChain infer the schema from the function signature.  InjectedState
    # is intentionally hidden from the model and populated by ToolNode.
    @tool(args_schema=EmptyToolArgs)
    def get_game_state(
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """读取当前房间状态。"""
        room_id = state["room_id"]
        room = room_repository.get(room_id)

        if room is None:
            raise ValueError("房间不存在")

        return tool_executor.read_only(
            state,
            "get_game_state",
            lambda: {
                "status": "success",
                "data": {
                    "room_id": room["id"],
                    "room_status": room["status"],
                    "game": room.get("game", {}),
                    "public_clue_ids": room.get("public_clue_ids", []),
                },
            },
        )
    
    @tool(args_schema=EnterLocationArgs)
    def enter_location(
        location_id: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """进入指定地点并获得私密环境描述。"""
        policy_service.assert_tool_allowed(state, "enter_location")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能执行玩家搜证")

        return _execute_idempotent(
            state,
            "enter_location",
            {"location_id": location_id},
            lambda: investigation_service.enter_location(
                room_id=room_id,
                player_id=player_id,
                location_id=location_id,
            ),
            tool_executor=tool_executor,
        )

    @tool(args_schema=InspectObjectArgs)
    def inspect_object(
        location_id: str,
        object_text: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """检查当前玩家指定地点中的物品。"""
        policy_service.assert_tool_allowed(state, "inspect_object")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能执行玩家搜证")

        return _execute_idempotent(
            state,
            "inspect_object",
            {"location_id": location_id, "object_text": object_text},
            lambda: investigation_service.inspect_object(
                room_id=room_id,
                player_id=player_id,
                location_id=location_id,
                object_text=object_text,
            ),
            tool_executor=tool_executor,
        )

    @tool(args_schema=UnlockReasoningArgs)
    def unlock_reasoning_rule(
        rule_id: str,
        reasoning: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """提交玩家推理并尝试触发一条已有规则。"""
        policy_service.assert_tool_allowed(state, "unlock_reasoning_rule")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能提交玩家推理")

        return _execute_idempotent(
            state,
            "unlock_reasoning_rule",
            {"rule_id": rule_id, "reasoning": reasoning},
            lambda: reasoning_service.unlock_rule(
                room_id=room_id,
                player_id=player_id,
                rule_id=rule_id,
                reasoning=reasoning,
            ),
            tool_executor=tool_executor,
        )

    return [
        get_game_state,
        enter_location,
        inspect_object,
        unlock_reasoning_rule,
    ]
