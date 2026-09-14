import asyncio
import logging
from datetime import datetime, timezone

from app.repositories.room_repository import RoomRepository
from app.services.dm_agent_service import DMAgentService
from app.services.dm_service import DMService
from app.services.game_service import GameService
from app.services.script_bundle import ScriptBundleLoader


logger = logging.getLogger(__name__)


class GameOrchestratorService:
    def __init__(
        self,
        room_repository: RoomRepository,
        bundle_loader: ScriptBundleLoader,
        game_service: GameService,
        dm_agent_service: DMAgentService,
        dm_service: DMService,
        connection_manager,
    ):
        self.room_repository = room_repository
        self.bundle_loader = bundle_loader
        self.game_service = game_service
        self.dm_agent_service = dm_agent_service
        self.dm_service = dm_service
        self.connection_manager = connection_manager
        self.tasks: dict[str, asyncio.Task] = {}
        self.announcement_tasks: set[asyncio.Task] = set()
        self.announcement_locks: dict[str, asyncio.Lock] = {}

    def start(self, room_id: str) -> None:
        previous_task = self.tasks.get(room_id)
        if previous_task and not previous_task.done():
            previous_task.cancel()

        task = asyncio.create_task(
            self._run_room(room_id),
            name=f"game-orchestrator:{room_id}",
        )
        self.tasks[room_id] = task
        task.add_done_callback(
            lambda completed, current_room_id=room_id: self._forget_task(
                current_room_id,
                completed,
            )
        )

    def stop(self, room_id: str) -> None:
        task = self.tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

        prefix = f"stage-announcement:{room_id}:"
        for announcement in list(self.announcement_tasks):
            if announcement.get_name().startswith(prefix) and not announcement.done():
                announcement.cancel()

        self.announcement_locks.pop(room_id, None)

    def _forget_task(self, room_id: str, task: asyncio.Task) -> None:
        if self.tasks.get(room_id) is task:
            self.tasks.pop(room_id, None)

    def _queue_announcement(self, room_id: str, event_type: str) -> None:
        task = asyncio.create_task(
            self._announce_stage(room_id, event_type),
            name=f"stage-announcement:{room_id}:{event_type}",
        )
        self.announcement_tasks.add(task)
        task.add_done_callback(self.announcement_tasks.discard)

    def _get_stage(self, room: dict) -> dict:
        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        stage_id = room.get("game", {}).get("stage_id")
        return next(
            (
                stage
                for stage in bundle.get("stages", [])
                if stage.get("id") == stage_id
            ),
            {},
        )

    async def _publish_message(self, room_id: str, content: str) -> None:
        message = self.dm_service.send_public(
            room_id=room_id,
            content=content,
        )
        await self.connection_manager.broadcast_room(
            room_id=room_id,
            event={
                "type": "PUBLIC_MESSAGE",
                "message": message,
            },
        )

    async def _release_initial_clues(self, room_id: str) -> None:
        released = self.game_service.release_initial_clues(room_id)
        for item in released:
            clue = item["clue"]
            clue_id = item["clue_id"]
            if item.get("target") == "all":
                message = self.dm_service.send_public(
                    room_id=room_id,
                    content=(
                        f"主持人将一张线索卡放在众人面前：《{clue.get('title', '未命名线索')}》。"
                        f"{clue.get('content', '')}"
                    ),
                    clue_ids=[clue_id],
                )
                await self.connection_manager.broadcast_room(
                    room_id=room_id,
                    event={
                        "type": "PUBLIC_MESSAGE",
                        "message": message,
                    },
                )
                continue

            message = self.dm_service.send_private(
                room_id=room_id,
                player_id=item["player_id"],
                content=(
                    f"主持人递来一张搜证前线索卡：《{clue.get('title', '未命名线索')}》。"
                    f"{clue.get('content', '')}"
                ),
                clue_ids=[clue_id],
            )
            await self.connection_manager.send_to_player(
                room_id=room_id,
                player_id=item["player_id"],
                event={
                    "type": "PRIVATE_MESSAGE",
                    "message": message,
                },
            )

    async def _announce_stage(self, room_id: str, event_type: str) -> None:
        lock = self.announcement_locks.setdefault(room_id, asyncio.Lock())

        async with lock:
            room = self.room_repository.get(room_id)
            if room is None or room.get("status") != "playing":
                return

            state = self.game_service.get_public_state(room_id)
            stage_id = state.get("stage_id")

            try:
                result = None
                last_error = None
                for attempt in range(2):
                    try:
                        result = await asyncio.to_thread(
                            self.dm_agent_service.handle_public_event,
                            room_id=room_id,
                            event_type=event_type,
                            event_payload=state,
                        )
                        break
                    except Exception as error:
                        last_error = error
                        if attempt == 0:
                            await asyncio.sleep(0.2)
                if result is None:
                    raise last_error or RuntimeError("AI 主持词生成失败")
                content = result.content.strip()
                if not content:
                    raise ValueError("AI 主持人返回了空的阶段主持词")
            except Exception:
                logger.exception(
                    "Failed to generate %s announcement for room %s",
                    event_type,
                    room_id,
                )
                # 主持词必须由 AI 生成；失败时不伪造固定主持词。
                return

            current_room = self.room_repository.get(room_id)
            if (
                current_room is None
                or current_room.get("status") != "playing"
                or current_room.get("game", {}).get("stage_id") != stage_id
            ):
                return

            await self._publish_message(room_id, content)

            if stage_id == "voting":
                current_room.setdefault("game", {})["vote_open"] = True
                self.room_repository.save(room_id)
                await self.connection_manager.broadcast_room(
                    room_id=room_id,
                    event={
                        "type": "VOTE_OPENED",
                        "game": self.game_service.get_public_state(room_id),
                    },
                )

            if stage_id == "ending":
                self.game_service.finish(room_id)
                await self.connection_manager.broadcast_room(
                    room_id=room_id,
                    event={
                        "type": "GAME_ENDED",
                        "game": self.game_service.get_public_state(room_id),
                    },
                )

    async def _broadcast_stage_changed(self, room_id: str) -> None:
        await self.connection_manager.broadcast_room(
            room_id=room_id,
            event={
                "type": "STAGE_CHANGED",
                "game": self.game_service.get_public_state(room_id),
            },
        )

    async def _run_room(self, room_id: str) -> None:
        try:
            self._queue_announcement(room_id, "game_started")

            while True:
                room = self.room_repository.get(room_id)
                if room is None or room.get("status") != "playing":
                    return

                stage = self._get_stage(room)
                game = room.get("game", {})
                deadline_text = game.get("stage_deadline")

                if stage.get("manual_transition", False) or not deadline_text:
                    return

                deadline = datetime.fromisoformat(deadline_text)
                wait_seconds = max(
                    0,
                    (deadline - datetime.now(timezone.utc)).total_seconds(),
                )
                await asyncio.sleep(wait_seconds)

                previous_stage_id = game.get("stage_id")
                next_game = self.game_service.refresh_stage(room_id)

                if next_game.get("stage_id") == previous_stage_id:
                    continue

                if next_game.get("stage_id") == "ending":
                    self.game_service.resolve_ending(room_id)

                await self._broadcast_stage_changed(room_id)
                if next_game.get("stage_id") == "investigation":
                    await self._release_initial_clues(room_id)
                self._queue_announcement(room_id, "stage_changed")

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Game orchestrator failed for room %s", room_id)
