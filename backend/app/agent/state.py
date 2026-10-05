from typing import Any, Literal, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


RequestType = Literal["player_private", "public_event"]
Visibility = Literal["private", "public"]
AgentAction = Literal["tool_call", "respond"]


class ToolResult(TypedDict, total=False):
    name: str | None
    status: str
    visibility: Visibility
    message: str | None
    content: str | None
    clue_ids: list[str]
    data: dict[str, Any]


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
    history_summary: str
    history_summarized_until: int
    request_type: RequestType
    messages: Annotated[
        list[AnyMessage],
        add_messages
    ]
    event_type: str
    event_payload: dict[str, Any]
    agent_action: AgentAction
    tool_called_this_turn: bool
