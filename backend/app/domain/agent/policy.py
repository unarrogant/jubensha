from typing import Any


class PolicyService:
    """Central business-policy gate for Agent tool execution.

    Prompts may guide the model, but this service is the authoritative check
    before a tool can change or reveal game state.
    """

    _TOOL_ACTIONS = {
        "get_game_state": "view_game_state",
        "enter_location": "enter_location",
        "inspect_object": "inspect_object",
        "unlock_reasoning_rule": "submit_reasoning",
    }

    _DEFAULT_ALLOWED_STAGES = {
        "get_game_state": {"waiting", "role_selection", "intro", "investigation", "discussion", "voting", "ending"},
        "enter_location": {"investigation"},
        "inspect_object": {"investigation"},
        "unlock_reasoning_rule": {"investigation", "discussion"},
    }

    def current_stage_id(self, state: dict[str, Any]) -> str | None:
        context = state.get("context") or {}
        game_state = context.get("GAME_STATE") or {}
        if isinstance(game_state, dict) and game_state.get("stage_id"):
            return str(game_state["stage_id"])

        current_stage = context.get("CURRENT_STAGE") or {}
        if isinstance(current_stage, dict) and current_stage.get("id"):
            return str(current_stage["id"])
        return None

    def assert_tool_allowed(
        self,
        state: dict[str, Any],
        tool_name: str,
    ) -> None:
        """Reject invalid actor, request type, or stage before side effects."""
        if tool_name == "get_game_state":
            return

        if state.get("request_type") != "player_private":
            raise ValueError(f"{tool_name} 只能由玩家私聊请求调用")
        if not state.get("player_id"):
            raise ValueError(f"{tool_name} 缺少玩家身份")

        stage_id = self.current_stage_id(state)
        if stage_id is None:
            raise ValueError(f"当前阶段 unknown 不允许调用 {tool_name}")

        current_stage = (state.get("context") or {}).get("CURRENT_STAGE") or {}
        action = self._TOOL_ACTIONS.get(tool_name, tool_name)
        if isinstance(current_stage, dict):
            forbidden = current_stage.get("forbidden_actions") or []
            if action in forbidden or tool_name in forbidden:
                raise ValueError(f"当前阶段 {stage_id} 不允许调用 {tool_name}")

            allowed = current_stage.get("allowed_actions")
            if isinstance(allowed, list) and allowed and action not in allowed and tool_name not in allowed:
                raise ValueError(f"当前阶段 {stage_id} 不允许调用 {tool_name}")

        if stage_id not in self._DEFAULT_ALLOWED_STAGES.get(tool_name, set()):
            raise ValueError(f"当前阶段 {stage_id} 不允许调用 {tool_name}")

    def resolve_visibility(
        self,
        state: dict[str, Any],
        tool_name: str,
        result: dict[str, Any],
    ) -> str:
        """Resolve visibility from the trusted request and channel.

        Player-triggered tools are always private. A public channel is only
        accepted for a public event, so a model cannot leak a private result.

        ``tool_name`` is part of the policy boundary even though the current
        rules do not branch on it yet. Keeping it here allows individual tools
        to gain stricter visibility rules without changing the executor API.
        """
        if not tool_name:
            raise ValueError("工具名称不能为空")
        if state.get("request_type") == "player_private":
            return "private"
        if result.get("channel") == "PUBLIC_MESSAGE":
            return "public"
        return "private"
