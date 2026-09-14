from typing import Any, Literal, TypedDict, Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


RequestType = Literal["player_private", "public_event"]
Visibility = Literal["private", "public"]
AgentAction = Literal["tool_call", "respond"]


class ToolResult(TypedDict, total=False):
    visibility: Visibility
    content: str | None
    clue_ids: list[str]


class DMState(TypedDict, total=False):
    room_id: str
    player_id: str
    thread_id: str
    player_message: str
    context: dict[str, Any]
    visibility: Visibility
    response: str
    clue_ids: list[str]
    tool_result: ToolResult
    request_type: RequestType
    messages: Annotated[
        list[AnyMessage],
        add_messages
    ]
    event_type: str
    event_payload: dict[str, Any]
    agent_action: AgentAction
