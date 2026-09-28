import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.state import DMState
from app.config import get_deepseek_config


def build_dm_graph(checkpointer=None, tools=None):
    # Keep the latest turns verbatim and summarize only older turns. The
    # checkpoint still retains the full audit history; this limit is for the
    # model request so token usage does not grow with the whole session.
    RECENT_MESSAGES_TO_KEEP = 10
    SUMMARY_TRIGGER_MESSAGES = 16
    SUMMARY_INPUT_MAX_CHARS = 14000
    SUMMARY_OUTPUT_MAX_CHARS = 6000

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

    def _message_text(message) -> str:
        """Convert a LangChain message into compact, safe summary text."""
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            content = f"{content}\n工具调用：{json.dumps(tool_calls, ensure_ascii=False, default=str)}"

        return content.strip()

    def _summary_transcript(messages: list) -> str:
        lines = []
        for message in messages:
            message_type = getattr(message, "type", "message")
            if message_type == "system":
                # The current DM_SYSTEM is injected on every model request;
                # storing it in the conversation summary only wastes tokens.
                continue

            content = _message_text(message)
            if not content:
                continue

            role = {
                "human": "玩家",
                "ai": "主持人",
                "tool": "工具结果",
            }.get(message_type, message_type)
            lines.append(f"{role}：{content[:1800]}")

        transcript = "\n".join(lines)
        return transcript[:SUMMARY_INPUT_MAX_CHARS]

    def compact_history_node(state: DMState) -> dict:
        """Summarize old thread messages once the session grows large."""
        messages = list(state.get("messages", []))
        if len(messages) < SUMMARY_TRIGGER_MESSAGES:
            return {}

        summarized_until = state.get("history_summarized_until", 0)
        if not isinstance(summarized_until, int) or summarized_until < 0:
            summarized_until = 0

        keep_from = max(0, len(messages) - RECENT_MESSAGES_TO_KEEP)
        if keep_from <= summarized_until:
            return {}

        transcript = _summary_transcript(messages[summarized_until:keep_from])
        if not transcript:
            return {"history_summarized_until": keep_from}

        previous_summary = state.get("history_summary", "")
        summary_prompt = (
            "你是剧本杀 Agent 的上下文压缩器。请把旧的对话压缩成一段简洁、"
            "事实准确的中文摘要，供同一个玩家线程继续使用。只保留已经发生的事实、"
            "玩家提出的关键判断、主持人已经给出的结果、工具调用结果和未完成的调查方向。"
            "不要新增推理，不要把不确定内容写成事实，不要输出标题、JSON 或项目符号。"
            "当前房间的角色、线索、阶段和规则以最新业务上下文为准，不要在摘要中重新定义它们。\n\n"
            f"已有摘要：{previous_summary or '无'}\n\n"
            f"需要压缩的旧消息：\n{transcript}"
        )

        try:
            response = llm.invoke([
                SystemMessage(content="你只负责压缩 Agent 对话历史，不负责主持游戏。"),
                HumanMessage(content=summary_prompt),
            ])
            summary = _message_text(response)[:SUMMARY_OUTPUT_MAX_CHARS]
        except Exception:
            # Compression is an optimization. If it fails, retain the full
            # history for this request instead of breaking the player's turn.
            return {}

        if not summary:
            return {}

        return {
            "history_summary": summary,
            "history_summarized_until": keep_from,
        }

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

        full_messages = list(state.get("messages", []))
        history_summary = state.get("history_summary", "")
        summarized_until = state.get("history_summarized_until", 0)
        summary_covers_old_messages = (
            bool(history_summary)
            and isinstance(summarized_until, int)
            and summarized_until >= max(
                0,
                len(full_messages) - RECENT_MESSAGES_TO_KEEP,
            )
        )
        if summary_covers_old_messages:
            recent_messages = [
                message
                for message in full_messages[-RECENT_MESSAGES_TO_KEEP:]
                if getattr(message, "type", "") != "system"
            ]
            messages = [
                SystemMessage(
                    content=(
                        f"{system_prompt}\n\n"
                        "以下是该线程较早对话的压缩摘要，只能作为历史参考；"
                        "当前阶段和线索以本次上下文为准：\n"
                        f"{history_summary}"
                    )
                ),
                *recent_messages,
            ]
        else:
            messages = full_messages

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
                if (state.get("event_payload") or {}).get("stage_id") == "ending":
                    behavior_prompt += (
                        "\n结局复盘必须写成连续、完整的中文主持人口述，不得使用项目符号、编号、"
                        "Markdown 加粗、分栏标题、字段名、JSON 或英文内部标记。请按时间顺序还原 "
                        "EVENT_PAYLOAD.ending 中的案件经过，交代人物动机、关键行动、现场如何被伪造、"
                        "调查如何揭开真相，以及投票之后发生的结局。必须覆盖 truth_reveal 中的全部事实，"
                        "但要把事实自然融入故事，不要逐条照抄。故事结束后，再用连贯的叙述自然交代每位主要角色"
                        "最后的命运，不要另起“角色命运”清单。语言要沉浸、克制、完整，避免奇怪符号和内部系统词。"
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

        elif getattr(messages[-1], "type", "") == "tool":
            # 工具只返回事实和内部状态；必须再让模型把结果改写成主持人口吻。
            messages.append(
                HumanMessage(
                    content=(
                        "请把刚才工具返回的结果改写成自然、沉浸式的主持人回复。"
                        "不要输出 JSON、工具名、rule_id、status、字段名或英文内部提示。"
                        "如果结果表示该推理已经触发过，只委婉说明暂时没有新的发现，"
                        "不要提到系统拒绝、重复触发或内部规则。"
                    ),
                )
            )
        else:
            messages.append(
                HumanMessage(
                    content=request_content,
                )
            )

        after_tool_result = bool(
            len(messages) >= 2
            and getattr(messages[-2], "type", "") == "tool"
            and getattr(messages[-1], "type", "") == "human"
        )
        response = (
            llm.invoke(messages)
            if is_public_event or after_tool_result
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
            tool_data = data.get("data", {})
            if not isinstance(tool_data, dict):
                tool_data = {}

            clue_ids = data.get("clue_ids", [])
            if not isinstance(clue_ids, list):
                clue_ids = []
            else:
                clue_ids = list(clue_ids)

            clue_id = data.get("clue_id")
            if clue_id and clue_id not in clue_ids:
                clue_ids.append(clue_id)

            status = data.get("status")

            if not channel and not tool_message and not clue_ids and not status:
                break

            return {
                "visibility": (
                    "public"
                    if channel == "PUBLIC_MESSAGE"
                    else "private"
                ),
                "content": tool_message,
                "clue_ids": clue_ids,
                "status": status,
                "data": tool_data,
            }

        if saw_tool_message:
            return {
                "visibility": "private",
                "content": None,
                "clue_ids": [],
                "status": None,
                "data": {},
            }

        return {
            "visibility": "private",
            "content": None,
            "clue_ids": [],
            "data": {},
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
                "status": tool_result.get("status"),
                "data": tool_result.get("data", {}),
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

        messages = state.get("messages", [])
        response_content = (
            getattr(messages[-1], "content", "")
            if messages
            else ""
        )

        if not isinstance(response_content, str):
            response_content = str(response_content)

        if not response_content.strip():
            if tool_result.get("status") == "already_triggered":
                response_content = (
                    "你的思路已经触及过这条线索，但眼下没有新的发现。"
                    "可以结合手中的证据，从另一个角度继续梳理。"
                )
            else:
                response_content = tool_result.get("content") or "主持人暂时没有更多信息。"

        return {
            "response": (
                response_content.strip()
                or "主持人暂时没有更多信息。"
            ),
            "visibility": tool_result.get("visibility", "private"),
            "clue_ids": tool_result.get("clue_ids", []),
        }
    
    graph = StateGraph(DMState)

    graph.add_node("validate_request", validate_request_node)
    graph.add_node("compact_history", compact_history_node)
    graph.add_node("decide", decide_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("apply_tool_result", apply_tool_result_node)
    graph.add_node("render", final_node)

    graph.add_edge(START, "validate_request")
    graph.add_edge("validate_request", "compact_history")
    graph.add_edge("compact_history", "decide")

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
