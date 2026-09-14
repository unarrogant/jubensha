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

        thread_id = f"{room_id}:{player_id}"

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
            recovery_thread_id = f"{room_id}:{player_id}:retry:{uuid4().hex}"
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
                "主持人暂时没有更多信息。",
            ),
            clue_ids=result.get("clue_ids",[]),
        )

        return self._validate_player_result(
            agent_result,
        )

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
        return DMAgentResult(
            visibility="public",
            content=result.get(
                "response",
                "当前发生了一些变化。",
            ),
            clue_ids=[],
        )
