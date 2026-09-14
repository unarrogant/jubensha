from typing import Annotated

from langgraph.prebuilt import InjectedState
from langchain_core.tools import tool

from app.agent.state import DMState
from app.repositories.room_repository import RoomRepository
from app.services.investigation_service import InvestigationService
from app.services.reasoning_service import ReasoningService


def _current_stage_id(state: DMState) -> str | None:
    """从图状态读取当前阶段；权限判断不能依赖模型自己声明的阶段。"""
    game_state = state.get("context", {}).get("GAME_STATE", {})
    if isinstance(game_state, dict) and game_state.get("stage_id"):
        return str(game_state["stage_id"])

    current_stage = state.get("context", {}).get("CURRENT_STAGE", {})
    if isinstance(current_stage, dict):
        value = current_stage.get("id")
        return str(value) if value else None
    return None


def _assert_player_tool_allowed(state: DMState, tool_name: str) -> None:
    """工具层的硬权限检查，提示词失效时也不能越过游戏规则。"""
    if state.get("request_type") != "player_private":
        raise ValueError(f"{tool_name} 只能由玩家私聊请求调用")
    if not state.get("player_id"):
        raise ValueError(f"{tool_name} 缺少玩家身份")

    stage_id = _current_stage_id(state)
    if stage_id in {None, "intro", "voting", "ending"}:
        raise ValueError(f"当前阶段 {stage_id or 'unknown'} 不允许调用 {tool_name}")


def build_dm_tools(
    room_repository: RoomRepository,
    investigation_service: InvestigationService,
    reasoning_service:ReasoningService,
):
    @tool
    def get_game_state(
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """读取当前房间状态。"""
        room_id = state["room_id"]
        room = room_repository.get(room_id)

        if room is None:
            raise ValueError("房间不存在")

        return {
            "room_id": room["id"],
            "status": room["status"],
            "game": room.get("game", {}),
            "public_clue_ids": room.get(
                "public_clue_ids",
                [],
            ),
        }
    
    @tool
    def enter_location(
        location_id: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """进入指定地点并获得私密环境描述。"""
        _assert_player_tool_allowed(state, "enter_location")
        if _current_stage_id(state) != "investigation":
            raise ValueError("只有搜证阶段可以进入地点")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能执行玩家搜证")

        return investigation_service.enter_location(
            room_id=room_id,
            player_id=player_id,
            location_id=location_id,
        )

    @tool
    def inspect_object(
        location_id: str,
        object_text: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """检查当前玩家指定地点中的物品。"""
        _assert_player_tool_allowed(state, "inspect_object")
        if _current_stage_id(state) != "investigation":
            raise ValueError("只有搜证阶段可以检查物品")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能执行玩家搜证")

        return investigation_service.inspect_object(
            room_id=room_id,
            player_id=player_id,
            location_id=location_id,
            object_text=object_text,
        )

    @tool
    def unlock_reasoning_rule(
        rule_id: str,
        reasoning: str,
        state: Annotated[DMState, InjectedState],
    ) -> dict:
        """提交玩家推理并尝试触发一条已有规则。"""
        _assert_player_tool_allowed(state, "unlock_reasoning_rule")

        room_id = state["room_id"]
        player_id = state.get("player_id")

        if not player_id:
            raise ValueError("公共事件不能提交玩家推理")

        return reasoning_service.unlock_rule(
            room_id=room_id,
            player_id=player_id,
            rule_id=rule_id,
            reasoning=reasoning,
        )

    return [
        get_game_state,
        enter_location,
        inspect_object,
        unlock_reasoning_rule,
    ]
