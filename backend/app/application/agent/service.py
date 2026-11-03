import re
from time import perf_counter
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.interfaces.ports import (
    CheckpointFactoryPort,
    IdempotencyPort,
    RoomRepositoryPort,
    ScriptBundlePort,
)
from app.schemas.dm_agent import AgentRequest, DMAgentResult
from app.agent.tools import build_dm_tools
from app.application.investigation.service import InvestigationService
from app.application.agent.runtime import AgentRuntime
from app.application.agent.metrics import AgentMetrics
from app.application.agent.audit import AuditRecorder
from app.application.agent.context import ContextAssembler
from app.domain.agent.policy import PolicyService
from app.services.reasoning_service import ReasoningService
from app.application.agent.rendering import ResponseRenderer

class DMAgentService:
    AGENT_THREAD_VERSION = "v2"
    def __init__(
        self,
        room_repository: RoomRepositoryPort,
        bundle_loader: ScriptBundlePort,
        investigation_service:InvestigationService,
        reasoning_service:ReasoningService,
        idempotency_service: IdempotencyPort,
        checkpoint_factory: CheckpointFactoryPort,
        policy_service: PolicyService | None = None,
    ):
        self.room_repository = room_repository
        self.bundle_loader = bundle_loader
        self.policy_service = policy_service or PolicyService()
        self.response_renderer = ResponseRenderer()
        self.audit_recorder = AuditRecorder(room_repository)
        self.agent_metrics = AgentMetrics(room_repository)
        self.idempotency_service = idempotency_service
        self.context_assembler = ContextAssembler(
            room_repository=room_repository,
            bundle_loader=bundle_loader,
        )
        self.tools = build_dm_tools(
            room_repository=room_repository,
            investigation_service=investigation_service,
            reasoning_service=reasoning_service,
            policy_service=self.policy_service,
            idempotency_service=self.idempotency_service,
        )

        self.checkpointer: BaseCheckpointSaver = checkpoint_factory.build()

        self.agent_runtime = AgentRuntime(
            checkpointer=self.checkpointer,
            tools=self.tools,
        )
        # Kept as a compatibility attribute for diagnostics and old callers.
        self.graph = self.agent_runtime.graph

        self.reasoning_service=reasoning_service

    def build_context(
        self,
        room_id: str,
        player_id: str,
        content: str,
    ) -> dict:
        return self.context_assembler.build_player_context(
            room_id=room_id,
            player_id=player_id,
            content=content,
        )

    def _validate_player_result(
        self,
        result: DMAgentResult,
    ) -> DMAgentResult:
        return DMAgentResult(
            visibility=result.visibility,
            response=(
                self.response_renderer.render_player_response(result.response)
                or "主持人暂时没有更多可以补充的信息。"
            ),
            clue_ids=result.clue_ids,
            tool_used=result.tool_used,
            tool_name=result.tool_name,
            tool_status=result.tool_status,
            tool_data=result.tool_data,
        )

    def _record_agent_metrics(
        self,
        room_id: str,
        result: dict,
        elapsed_ms: float,
        *,
        status: str = "success",
        error_code: str | None = None,
    ) -> None:
        input_tokens, output_tokens = AgentMetrics.token_usage(result)
        self.agent_metrics.record_run(
            room_id,
            elapsed_ms=elapsed_ms,
            status=status,
            recovered=bool(result.get("_runtime_recovered", False)),
            tool_status=result.get("tool_status"),
            clue_count=len(result.get("clue_ids", []) or []),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_code=error_code,
        )

    @staticmethod
    def _classify_error(error: Exception) -> str:
        """Map infrastructure/model failures to stable operational codes."""
        message = str(error).lower()
        error_name = type(error).__name__.lower()
        if "agent_protocol_error" in message:
            return "agent_protocol_error"
        if "timeout" in message or "timeout" in error_name:
            return "model_timeout"
        if "checkpoint" in message or "redis" in message:
            return "checkpoint_error"
        if "tool" in message or "argument" in message:
            return "tool_error"
        if "不允许" in str(error) or "forbidden" in message or "permission" in message:
            return "policy_denied"
        if isinstance(error, ValueError):
            return "invalid_request"
        if "model" in message or "llm" in message:
            return "model_error"
        return "runtime_error"

    @staticmethod
    def _stage_id(context: dict) -> str | None:
        game_state = context.get("GAME_STATE") or {}
        current_stage = context.get("CURRENT_STAGE") or {}
        if isinstance(game_state, dict) and game_state.get("stage_id"):
            return str(game_state["stage_id"])
        if isinstance(current_stage, dict) and current_stage.get("id"):
            return str(current_stage["id"])
        return None

    @staticmethod
    def _build_agent_result(
        result: dict,
        *,
        default_visibility: str,
    ) -> DMAgentResult:
        """Validate the graph boundary before any response is persisted."""
        if not isinstance(result, dict):
            raise ValueError("agent_protocol_error: graph result must be an object")

        payload = {
            "visibility": result.get("visibility", default_visibility),
            "response": result.get("response", ""),
            "clue_ids": result.get("clue_ids", []),
            "tool_used": bool(result.get("tool_used", False)),
            "tool_name": result.get("tool_name"),
            "tool_status": result.get("tool_status"),
            "tool_data": result.get("tool_data", {}),
        }
        try:
            return DMAgentResult.model_validate(payload)
        except Exception as error:
            raise ValueError(f"agent_protocol_error: {error}") from error

    def handle_player_message(
        self,
        room_id: str,
        player_id: str,
        content: str,
    ) -> DMAgentResult:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        player_exists = any(
            player.get("id") == player_id
            for player in room.get("players", [])
        )

        if not player_exists:
            raise ValueError("玩家不在这个房间")

        context = self.build_context(
            room_id=room_id,
            player_id=player_id,
            content=content,
        )

        # v2 skips checkpoints created by the old tool schema, which could
        # contain an assistant tool call without its matching ToolMessage.
        thread_id = f"{room_id}:{player_id}:{self.AGENT_THREAD_VERSION}"

        request = AgentRequest(
            room_id=room_id,
            player_id=player_id,
            request_type="player_private",
            thread_id=thread_id,
            request_id=uuid4().hex,
            player_message=content,
            context=context,
        )
        started_at = perf_counter()
        try:
            result = self.agent_runtime.invoke(request, recover_on_error=True)
        except Exception as error:
            elapsed_ms = (perf_counter() - started_at) * 1000
            error_code = self._classify_error(error)
            self.agent_metrics.record_run(
                room_id,
                elapsed_ms=elapsed_ms,
                status="failure",
                error_code=error_code,
            )
            self.audit_recorder.record_agent_run(
                room_id,
                run_id=request.request_id,
                request_type=request.request_type,
                player_id=player_id,
                stage_id=self._stage_id(context),
                status="failed",
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )
            raise

        elapsed_ms = (perf_counter() - started_at) * 1000
        try:
            agent_result = self._build_agent_result(
                result,
                default_visibility="private",
            )
            validated = self._validate_player_result(agent_result)
        except Exception as error:
            error_code = self._classify_error(error)
            self.agent_metrics.record_run(
                room_id,
                elapsed_ms=elapsed_ms,
                status="failure",
                error_code=error_code,
            )
            self.audit_recorder.record_agent_run(
                room_id,
                run_id=request.request_id,
                request_type=request.request_type,
                player_id=player_id,
                stage_id=self._stage_id(context),
                status="failed",
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )
            raise

        self._record_agent_metrics(room_id, result, elapsed_ms)
        input_tokens, output_tokens = AgentMetrics.token_usage(result)
        self.audit_recorder.record_agent_run(
            room_id,
            run_id=request.request_id,
            request_type=request.request_type,
            player_id=player_id,
            stage_id=self._stage_id(context),
            status="succeeded",
            elapsed_ms=elapsed_ms,
            recovered=bool(result.get("_runtime_recovered", False)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self.audit_recorder.record_player_exchange(
            room_id=room_id,
            player_id=player_id,
            question=content,
            result=validated,
        )
        return validated

    def build_public_context(
        self,
        room_id: str,
        event_type: str,
        event_payload: dict | None = None,
    ) -> dict:
        return self.context_assembler.build_public_context(
            room_id=room_id,
            event_type=event_type,
            event_payload=event_payload,
        )

    @staticmethod
    def _polish_ending_content(content: str) -> str:
        # Deprecated internal entry point; keep old callers on the new renderer.
        return ResponseRenderer().render_ending(content)

        """Keep the public ending as one readable host narration.

        The model is instructed to write prose, but a small normalization step
        prevents occasional Markdown headings or list markers from leaking into
        the player-facing chat.
        """
        if not isinstance(content, str):
            return ""

        polished_lines = []
        for raw_line in content.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            plain_line = line.strip("* ")
            if plain_line.rstrip("：:") in {
                "完整真相",
                "角色命运",
                "本局结局",
                "案件真相与结局",
            }:
                continue

            line = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)、]\s+)", "", line)
            line = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", line)
            line = re.sub(
                r"</?(?:ds_system|ds_tool_call|tool_call)[^>]*>",
                "",
                line,
                flags=re.IGNORECASE,
            )
            line = line.replace("```", "").strip()
            polished_lines.append(line.strip())

        return "".join(polished_lines).strip()

    def handle_public_event(
        self,
        room_id: str,
        event_type: str,
        event_payload: dict | None = None,
    ) -> DMAgentResult:
        public_context = self.build_public_context(
            room_id=room_id,
            event_type=event_type,
            event_payload=event_payload,
        )

        # 公共主持词按阶段隔离线程。否则 intro 阶段的 AI 历史会被
        # investigation/discussion 继续复用，模型可能沿用旧阶段口吻或内容。
        payload = event_payload or {}
        game_state = public_context.get("GAME_STATE", {})
        stage_id = (
            payload.get("stage_id")
            or game_state.get("stage_id")
            or "unknown"
        )
        stage_started_at = (
            payload.get("stage_started_at")
            or game_state.get("stage_started_at")
            or "unknown"
        )
        thread_id = f"{room_id}:public:{stage_id}:{stage_started_at}"
        request = AgentRequest(
            room_id=room_id,
            request_type="public_event",
            thread_id=thread_id,
            request_id=uuid4().hex,
            event_type=event_type,
            event_payload=event_payload or {},
            context=public_context,
        )
        started_at = perf_counter()
        try:
            result = self.agent_runtime.invoke(request)
        except Exception as error:
            elapsed_ms = (perf_counter() - started_at) * 1000
            error_code = self._classify_error(error)
            self.agent_metrics.record_run(
                room_id,
                elapsed_ms=elapsed_ms,
                status="failure",
                error_code=error_code,
            )
            self.audit_recorder.record_agent_run(
                room_id,
                run_id=request.request_id,
                request_type=request.request_type,
                player_id=None,
                stage_id=stage_id,
                status="failed",
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )
            raise

        elapsed_ms = (perf_counter() - started_at) * 1000
        try:
            agent_result = self._build_agent_result(
                result,
                default_visibility="public",
            )
        except Exception as error:
            error_code = self._classify_error(error)
            self.agent_metrics.record_run(
                room_id,
                elapsed_ms=elapsed_ms,
                status="failure",
                error_code=error_code,
            )
            self.audit_recorder.record_agent_run(
                room_id,
                run_id=request.request_id,
                request_type=request.request_type,
                player_id=None,
                stage_id=stage_id,
                status="failed",
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )
            raise

        self._record_agent_metrics(room_id, result, elapsed_ms)
        input_tokens, output_tokens = AgentMetrics.token_usage(result)
        self.audit_recorder.record_agent_run(
            room_id,
            run_id=request.request_id,
            request_type=request.request_type,
            player_id=None,
            stage_id=stage_id,
            status="succeeded",
            elapsed_ms=elapsed_ms,
            recovered=bool(result.get("_runtime_recovered", False)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        content = agent_result.response
        if stage_id == "ending":
            content = self.response_renderer.render_ending(content)
            if not content:
                content = "The final truth is ready to be revealed, along with the fate of every character."
        else:
            content = self.response_renderer.render_player_response(content)
        return DMAgentResult(
            visibility="public",
            response=content,
            clue_ids=[],
        )
