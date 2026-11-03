from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class DMAgentModelResult(BaseModel):
    content: str


ToolVisibility = Literal["private", "public"]
AgentRequestType = Literal["player_private", "public_event"]
ToolStatus = Literal[
    "success",
    "already_triggered",
    "not_found",
    "forbidden",
    "invalid_argument",
    "error",
]
AgentFailureCode = Literal[
    "invalid_request",
    "policy_denied",
    "model_timeout",
    "model_error",
    "checkpoint_error",
    "tool_error",
    "agent_protocol_error",
    "runtime_error",
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


class AgentRequest(BaseModel):
    """Validated boundary object entering the Agent runtime."""

    room_id: str = Field(min_length=1, max_length=100)
    player_id: str | None = Field(default=None, min_length=1, max_length=100)
    request_type: AgentRequestType
    thread_id: str = Field(min_length=1, max_length=300)
    request_id: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=1,
        max_length=100,
    )
    player_message: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)
    event_type: str = Field(default="", max_length=100)
    event_payload: dict[str, Any] = Field(default_factory=dict)


class ToolCommand(BaseModel):
    """Normalized description of a tool action selected by the Agent."""

    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    command_id: str | None = Field(default=None, max_length=200)


class ToolResult(BaseModel):
    """Stable protocol between a tool and the Agent rendering layer."""

    status: ToolStatus
    visibility: ToolVisibility = "private"
    message: str | None = None
    clue_ids: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """Validated result returned by the Agent runtime."""

    visibility: Literal["private", "public"]
    response: str = Field(min_length=1)
    clue_ids: list[str] = Field(default_factory=list)
    tool_used: bool = False
    tool_name: str | None = None
    tool_status: str | None = None
    tool_data: dict[str, Any] = Field(default_factory=dict)


class DMAgentResult(AgentDecision):
    """Backward-compatible player-facing result name."""

    @property
    def content(self) -> str:
        return self.response


class AgentRun(BaseModel):
    """One complete Agent invocation, suitable for audit and metrics."""

    run_id: str = Field(min_length=1, max_length=100)
    room_id: str = Field(min_length=1, max_length=100)
    player_id: str | None = None
    request_type: AgentRequestType
    stage_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "succeeded", "failed"] = "running"
    retry_count: int = Field(default=0, ge=0)
    error_code: AgentFailureCode | None = None
    elapsed_ms: float | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    recovered: bool = False


class AuditEvent(BaseModel):
    """A durable event emitted during one AgentRun."""

    event_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    room_id: str = Field(min_length=1, max_length=100)
    event_type: str = Field(min_length=1, max_length=100)
    created_at: datetime
    player_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# Existing tool code imports this name. Keep it as a compatibility wrapper
# while the rest of the code migrates to the generic ToolResult contract.
class AgentToolResult(ToolResult):
    pass
