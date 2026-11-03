from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.graph import build_dm_graph
from app.schemas.dm_agent import AgentRequest


class AgentRuntime:
    """Own LangGraph invocation and recovery, not room business rules."""

    def __init__(self, checkpointer: BaseCheckpointSaver, tools):
        self.graph = build_dm_graph(checkpointer=checkpointer, tools=tools)

    def invoke(
        self,
        request: AgentRequest,
        *,
        recover_on_error: bool = False,
    ) -> dict:
        try:
            result = self.graph.invoke(
                request.model_dump(),
                config={"configurable": {"thread_id": request.thread_id}},
            )
            result["_runtime_recovered"] = False
            return result
        except Exception:
            if not recover_on_error:
                raise

            # Keep the same request_id so any side-effecting tool remains
            # idempotent when the recovery thread retries the graph.
            recovery_request = request.model_copy(
                update={
                    "thread_id": f"{request.thread_id}:retry:{uuid4().hex}",
                }
            )
            result = self.graph.invoke(
                recovery_request.model_dump(),
                config={
                    "configurable": {
                        "thread_id": recovery_request.thread_id,
                    }
                },
            )
            result["_runtime_recovered"] = True
            return result
