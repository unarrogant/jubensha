from typing import Any, Literal

from pydantic import BaseModel, Field


class DMAgentModelResult(BaseModel):
    content: str


ToolVisibility = Literal["private", "public"]
ToolStatus = Literal[
    "success",
    "already_triggered",
    "not_found",
    "forbidden",
    "invalid_argument",
    "error",
]


class EnterLocationArgs(BaseModel):
    location_id: str = Field(min_length=1, max_length=100)


class InspectObjectArgs(BaseModel):
    location_id: str = Field(min_length=1, max_length=100)
    object_text: str = Field(min_length=1, max_length=100)


class UnlockReasoningArgs(BaseModel):
    rule_id: str = Field(min_length=1, max_length=100)
    reasoning: str = Field(min_length=1, max_length=2000)


class EmptyToolArgs(BaseModel):
    """Explicit empty schema for tools that only receive InjectedState."""

    pass


class AgentToolResult(BaseModel):
    """Stable protocol between LangGraph tools and the rendering node."""

    status: ToolStatus
    visibility: ToolVisibility = "private"
    message: str | None = None
    clue_ids: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class DMAgentResult(BaseModel):
    visibility: Literal["private", "public"]
    content: str
    clue_ids: list[str] = Field(default_factory=list)
    tool_used: bool = False
    tool_name: str | None = None
    tool_status: str | None = None
    tool_data: dict[str, Any] = Field(default_factory=dict)
