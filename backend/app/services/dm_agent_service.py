import re
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.room_repository import RoomRepository
from app.schemas.dm_agent import DMAgentResult
from app.services.script_bundle import ScriptBundleLoader
from app.agent.graph import build_dm_graph
from app.agent.tools import build_dm_tools
from app.services.investigation_service import InvestigationService
from app.services.reasoning_service import ReasoningService
from app.config import get_storage_config

class DMAgentService:
    AGENT_THREAD_VERSION = "v2"
    def __init__(
        self,
        room_repository: RoomRepository,
        bundle_loader: ScriptBundleLoader,
        investigation_service:InvestigationService,
        reasoning_service:ReasoningService,
    ):
        self.room_repository = room_repository
        self.bundle_loader = bundle_loader
        self.tools = build_dm_tools(
            room_repository=room_repository,
            investigation_service=investigation_service,
            reasoning_service=reasoning_service,
        )

        self.checkpointer = self._build_checkpointer()

        self.graph = build_dm_graph(
            checkpointer=self.checkpointer,
            tools=self.tools,
        )

        self.reasoning_service=reasoning_service

    @staticmethod
    def _build_checkpointer():
        """Use the shared Redis checkpoint store for every Agent thread."""
        storage = get_storage_config()

        try:
            from redis import Redis
            from langgraph.checkpoint.redis import RedisSaver
        except ImportError as error:
            raise RuntimeError(
                "Redis 持久化需要安装 redis 和 langgraph-checkpoint-redis"
            ) from error

        # RedisSaver expects bytes rather than decoded strings.
        client = Redis.from_url(
            storage["redis_url"],
            decode_responses=False,
        )
        checkpointer = RedisSaver(redis_client=client)
        checkpointer.setup()
        return checkpointer

    def build_context(
        self,
        room_id: str,
        player_id: str,
        content: str,
    ) -> dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        player = None

        for item in room.get("players", []):
            if item.get("id") == player_id:
                player = item
                break

        if player is None:
            raise ValueError("玩家不在这个房间")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        game = room.get("game", {})
        stage_id = game.get("stage_id")

        current_stage = None

        for stage in bundle.get("stages", []):
            if stage.get("id") == stage_id:
                current_stage = stage
                break

        character = None

        for item in bundle.get("characters", []):
            if item.get("id") == player.get("character_id"):
                character = item
                break

        if character is None:
            raise ValueError("玩家角色尚未分配")

        character_map = {
            item.get("id"): item.get("name")
            for item in bundle.get("characters", [])
        }

        player_list = [
            {
                "name": item.get("name"),
                "character_name": character_map.get(
                    item.get("character_id")
                ),
            }
            for item in room.get("players", [])
        ]

        discovered_ids = room.get(
            "investigation",
            {},
        ).get(
            "discovered_clue_ids",
            [],
        )

        discovered_clues = [
            clue
            for clue in bundle.get("clues", [])
            if clue.get("id") in discovered_ids
        ]

        player_clues = [
            clue
            for clue in discovered_clues
            if clue.get("id") in player.get("clue_ids", [])
        ]

        return {
            "DM_SYSTEM": bundle.get("dm_system", ""),
            "SCRIPT_MANIFEST": bundle.get("manifest", {}),
            "CURRENT_STAGE": current_stage,
            "GAME_STATE": game,
            "PLAYER_LIST": player_list,
            "CURRENT_PLAYER": {
                "id": player["id"],
                "name": player["name"],
            },
            "CHARACTER_CONTEXT": character,
            "LOCATION_CONTEXT": bundle.get("locations", {}),
            "CLUE_CONTEXT": {
                "player_clues": player_clues,
                "discovered_clues": discovered_clues,
            },
            "UNLOCK_RULE_CONTEXT": bundle.get(
                "unlock_rules",
                [],
            ),
            "EVENT_HISTORY": [
                *room.get("messages", []),
                *player.get("private_messages", []),
            ],
            "PLAYER_MESSAGE": content,
        }

    def _validate_player_result(
        self,
        result: DMAgentResult,
    ) -> DMAgentResult:
        return DMAgentResult(
            visibility=result.visibility,
            content=result.content.strip(),
            clue_ids=result.clue_ids,
            tool_used=result.tool_used,
            tool_name=result.tool_name,
            tool_status=result.tool_status,
            tool_data=result.tool_data,
        )

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

        payload = {
            "room_id": room_id,
            "player_id": player_id,
            "request_type": "player_private",
            "thread_id": thread_id,
            "player_message": content,
            "context": context,
        }
        try:
            result = self.graph.invoke(
                payload,
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception:
            # 旧线程可能残留不兼容的供应商字段（例如 reasoning_content）。
            # 用全新线程重试一次，仍由同一个 AI 生成回复。
            recovery_thread_id = f"{room_id}:{player_id}:{self.AGENT_THREAD_VERSION}:retry:{uuid4().hex}"
            payload["thread_id"] = recovery_thread_id
            result = self.graph.invoke(
                payload,
                config={
                    "configurable": {
                        "thread_id": recovery_thread_id,
                    }
                },
            )

        agent_result = DMAgentResult(
            visibility=result.get(
                "visibility",
                "private",
            ),
            content=result.get(
                "response",
                "主持人暂时没有更多可以补充的信息。",
            ),
            clue_ids=result.get("clue_ids",[]),
            tool_used=bool(result.get("tool_used", False)),
            tool_name=result.get("tool_name"),
            tool_status=result.get("tool_status"),
            tool_data=result.get("tool_data", {}),
        )
        validated = self._validate_player_result(agent_result)
        refreshed_room = self.room_repository.get(room_id)
        if refreshed_room is not None:
            player = next(
                (item for item in refreshed_room.get("players", []) if item.get("id") == player_id),
                {},
            )
            refreshed_room.setdefault("agent_audit_log", []).append({
                "id": uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "player_id": player_id,
                "player_name": player.get("name"),
                "character_id": player.get("character_id"),
                "question": content,
                "answer": validated.content,
                "visibility": validated.visibility,
                "clue_ids": validated.clue_ids,
                "tool_used": validated.tool_used,
                "tool_name": validated.tool_name,
                "tool_status": validated.tool_status,
                "tool_data": validated.tool_data,
            })
            self.room_repository.save(room_id)
            self.room_repository.record_event(
                room_id,
                "DM_RESPONSE",
                actor_player_id=player_id,
                payload={
                    "question": content,
                    "answer": validated.content,
                    "visibility": validated.visibility,
                    "clue_ids": validated.clue_ids,
                    "tool_used": validated.tool_used,
                    "tool_name": validated.tool_name,
                    "tool_status": validated.tool_status,
                    "tool_data": validated.tool_data,
                },
            )
            if validated.tool_used:
                self.room_repository.record_event(
                    room_id,
                    "TOOL_CALLED",
                    actor_player_id=player_id,
                    payload={
                        "tool_name": validated.tool_name,
                        "tool_status": validated.tool_status,
                        "tool_data": validated.tool_data,
                    },
                )
            for clue_id in validated.clue_ids:
                self.room_repository.record_event(
                    room_id,
                    "CLUE_RELEASED",
                    actor_player_id=player_id,
                    target_player_id=player_id,
                    payload={
                        "clue_id": clue_id,
                        "source": validated.tool_name or "agent_response",
                    },
                )
        return validated

    def build_public_context(
        self,
        room_id: str,
        event_type: str,
        event_payload: dict | None = None,
    ) -> dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        game = room.get("game", {})
        stage_id = game.get("stage_id")
        current_stage = next(
            (
                stage
                for stage in bundle.get("stages", [])
                if stage.get("id") == stage_id
            ),
            None,
        )

        character_map = {
            character.get("id"): character.get("name")
            for character in bundle.get("characters", [])
        }
        player_list = [
            {
                "name": player.get("name"),
                "character_name": character_map.get(
                    player.get("character_id")
                ),
            }
            for player in room.get("players", [])
        ]

        public_clue_ids = room.get("public_clue_ids", [])
        public_clues = [
            clue
            for clue in bundle.get("clues", [])
            if clue.get("id") in public_clue_ids
        ]

        return {
            "DM_SYSTEM": bundle.get("dm_system", ""),
            "SCRIPT_MANIFEST": bundle.get("manifest", {}),
            "CURRENT_STAGE": current_stage,
            "GAME_STATE": game,
            "PLAYER_LIST": player_list,
            "PUBLIC_CLUES": public_clues,
            "EVENT_TYPE": event_type,
            "EVENT_PAYLOAD": event_payload or {},
        }

    @staticmethod
    def _polish_ending_content(content: str) -> str:
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
        result = self.graph.invoke(
            {
                "room_id": room_id,
                "request_type": "public_event",
                "event_type": event_type,
                "event_payload": event_payload or {},
                "context": public_context,
            },
            config={
                "configurable": {
                    "thread_id": thread_id,
                }
            },
        )
        content = result.get(
            "response",
            "The game has moved into a new phase.",
        )
        if stage_id == "ending":
            content = self._polish_ending_content(content)
            if not content:
                content = "The final truth is ready to be revealed, along with the fate of every character."
        return DMAgentResult(
            visibility="public",
            content=content,
            clue_ids=[],
        )
