import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.state import DMState
from app.config import get_deepseek_config


def build_dm_graph(checkpointer=None, tools=None):
    tools = tools or []
    config = get_deepseek_config()

    llm = ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        temperature=0,
        timeout=60,
        max_retries=1,
    )

    tool_llm = llm.bind_tools(tools)

    def validate_request_node(state: DMState) -> dict:
        """Validate the request boundary before spending an LLM call."""
        request_type = state.get("request_type")
        if request_type not in {"player_private", "public_event"}:
            raise ValueError("无效的 Agent 请求类型")

        if not state.get("room_id"):
            raise ValueError("Agent 请求缺少 room_id")

        if request_type == "player_private" and not state.get("player_id"):
            raise ValueError("玩家请求缺少 player_id")

        context = state.get("context")
        if not isinstance(context, dict):
            raise ValueError("Agent 请求缺少 context")

        # 每次新的外部请求都先清空上一次工具结果，避免旧线索
        # 被 render 节点误认为是本次请求的结果。
        return {
            "tool_result": {
                "visibility": "private",
                "content": None,
                "clue_ids": [],
            }
        }

    def decide_node(state: DMState) -> dict:
        """Ask the model for a direct response or a registered tool call."""
        context = state.get("context", {})
        system_prompt = context.get("DM_SYSTEM", "")
        is_public_event = state.get("request_type") == "public_event"

        messages = list(
            state.get("messages", [])
        )

        model_context = {
            key: value
            for key, value in context.items()
            if key != "DM_SYSTEM"
        }

        request_content = json.dumps(
            {
                "context": model_context,
                "player_message": state.get(
                    "player_message",
                    "",
                ),
                "event_type": state.get(
                    "event_type",
                    "",
                ),
                "event_payload": state.get(
                    "event_payload",
                    {},
                ),
            },
            ensure_ascii=False,
            default=str,
        )

        if not messages:
            if is_public_event:
                behavior_prompt = (
                    "\n你正在向全体玩家发布阶段主持词。"
                    "必须依据 CURRENT_STAGE 的名称、描述和 agent_instructions，"
                    "先明确宣布当前阶段，再用四至六句有画面感的自然叙述"
                    "说明本阶段目标、时间与限制。语气沉浸、克制而有悬念，"
                    "不要使用项目符号，不要输出 JSON、事件名或系统字段，"
                    "不得泄露角色私密信息，也不得编造剧本中不存在的线索。"
                    "如果当前阶段是 ending，必须依据 EVENT_PAYLOAD.ending 公布最终票型、"
                    "被指认结果、完整真相、胜方与主要角色命运，并在最后用一句话总结本局。"
                )
            else:
                behavior_prompt = "\n只使用提供的工具，不要编造工具结果。"

            messages = [
                SystemMessage(
                    content=system_prompt + behavior_prompt
                ),
                HumanMessage(
                    content=request_content,
                ),
            ]

        elif getattr(messages[-1], "type", "") != "tool":
            messages.append(
                HumanMessage(
                    content=request_content,
                )
            )

        response = (
            llm.invoke(messages)
            if is_public_event
            else tool_llm.invoke(messages)
        )

        if not state.get("messages"):
            return {
                "messages": [
                    *messages,
                    response,
                ],
                "agent_action": (
                    "tool_call"
                    if getattr(response, "tool_calls", None)
                    else "respond"
                ),
            }

        return {
            "messages": [response],
            "agent_action": (
                "tool_call"
                if getattr(response, "tool_calls", None)
                else "respond"
            ),
        }

    def route_after_decision(state: DMState) -> str:
        """Route only a real model tool call to ToolNode."""
        last_message = state["messages"][-1]

        if state.get("agent_action") == "tool_call" and getattr(
            last_message,
            "tool_calls",
            None,
        ):
            return "tools"

        return "final"

    def extract_tool_result(messages: list) -> dict:
        saw_tool_message = False

        for message in reversed(messages):
            if getattr(message, "type", "") != "tool":
                continue

            # 只解析本轮最后一个工具消息，不能回退到线程中更早的
            # 工具结果，否则普通发言可能重复返回旧线索。
            saw_tool_message = True

            content = message.content

            if isinstance(content, str):
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    break
            elif isinstance(content, dict):
                data = content
            else:
                break

            if not isinstance(data, dict):
                break

            channel = data.get("channel")
            tool_message = data.get("message")

            clue_ids = data.get("clue_ids", [])
            if not isinstance(clue_ids, list):
                clue_ids = []
            else:
                clue_ids = list(clue_ids)

            clue_id = data.get("clue_id")
            if clue_id and clue_id not in clue_ids:
                clue_ids.append(clue_id)

            if not channel and not tool_message and not clue_ids:
                break

            return {
                "visibility": (
                    "public"
                    if channel == "PUBLIC_MESSAGE"
                    else "private"
                ),
                "content": tool_message,
                "clue_ids": clue_ids,
            }

        if saw_tool_message:
            return {
                "visibility": "private",
                "content": None,
                "clue_ids": [],
            }

        return {
            "visibility": "private",
            "content": None,
            "clue_ids": [],
        }

    def apply_tool_result_node(state: DMState) -> dict:
        """Normalize the latest ToolNode result before rendering it."""
        tool_result = extract_tool_result(state.get("messages", []))

        visibility = tool_result.get("visibility")
        if visibility not in {"private", "public"}:
            raise ValueError("工具返回了无效的消息可见性")

        clue_ids = tool_result.get("clue_ids", [])
        if not isinstance(clue_ids, list) or not all(
            isinstance(clue_id, str) and clue_id.strip()
            for clue_id in clue_ids
        ):
            raise ValueError("工具返回了无效的 clue_ids")

        return {
            "tool_result": {
                "visibility": visibility,
                "content": tool_result.get("content"),
                "clue_ids": clue_ids,
            }
        }

    def final_node(state: DMState) -> dict:
        tool_result = state.get(
            "tool_result",
            {
                "visibility": "private",
                "content": None,
                "clue_ids": [],
            },
        )

        # 搜证和推理服务已经生成了剧本规定的描述，
        # 不需要再让模型重写一次。
        if tool_result.get("content"):
            return {
                "response": tool_result["content"],
                "visibility": tool_result.get("visibility", "private"),
                "clue_ids": tool_result.get("clue_ids", []),
            }

        messages = state.get("messages", [])
        response_content = (
            getattr(messages[-1], "content", "")
            if messages
            else ""
        )

        if not isinstance(response_content, str):
            response_content = str(response_content)

        return {
            "response": (
                response_content.strip()
                or "主持人暂时没有更多信息。"
            ),
            "visibility": "private",
            "clue_ids": [],
        }
    
    graph = StateGraph(DMState)

    graph.add_node("validate_request", validate_request_node)
    graph.add_node("decide", decide_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("apply_tool_result", apply_tool_result_node)
    graph.add_node("render", final_node)

    graph.add_edge(START, "validate_request")
    graph.add_edge("validate_request", "decide")

    graph.add_conditional_edges(
        "decide",
        route_after_decision,
        {
            "tools": "tools",
            "final": "render",
        },
    )

    graph.add_edge("tools", "apply_tool_result")
    graph.add_edge("apply_tool_result", "decide")
    graph.add_edge("render", END)

    return graph.compile(checkpointer=checkpointer)
