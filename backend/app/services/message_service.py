from datetime import datetime,timezone
from uuid import uuid4

from app.repositories.room_repository import RoomRepository
from app.services.script_bundle import ScriptBundleLoader

class MessageService:
    def __init__(
        self,
        room_repository:RoomRepository,
        bundle_loader:ScriptBundleLoader,
    ):
        self.room_repository=room_repository
        self.bundle_loader=bundle_loader

    @staticmethod
    def _get_player(
        room: dict,
        player_id: str,
    ) -> dict:
        for player in room["players"]:
            if player["id"] == player_id:
                return player

        raise ValueError("玩家不在这个房间中")

    def _check_private_message_allowed(self, room: dict) -> None:
        game=room.get("game",{})
        stage_id=game.get("stage_id")

        if not stage_id:
            raise ValueError("游戏尚未开始")

        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        current_stage=None

        for stage in bundle["stages"]:
            if stage.get("id") == stage_id:
                current_stage = stage
                break

        if current_stage is None:
            raise ValueError(f"找不到当前阶段：{stage_id}")

        allowed_actions = current_stage.get(
            "allowed_actions",
            [],
        )

        if "private_character_query" not in allowed_actions:
            raise ValueError("当前阶段不允许私聊主持人")

    def send_player_message(
            self,
            room_id:str,
            player_id:str,
            content:str,
    )->dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        if room["status"] != "playing":
            raise ValueError("游戏尚未开始")

        player = self._get_player(room, player_id)
        self._check_private_message_allowed(room)

        clean_content = content.strip()

        if not clean_content:
            raise ValueError("消息不能为空")

        message = {
            "id": uuid4().hex,
            "type": "PLAYER_PRIVATE_MESSAGE",
            "channel": "PRIVATE_MESSAGE",
            "player_id": player["id"],
            "player_name": player["name"],
            "content": clean_content,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        player.setdefault(
            "private_messages",
            [],
        ).append(message)

        self.room_repository.save(room_id)


        return message
    def list_messages(
        self,
        room_id: str,
        player_id:str,
    ) -> list[dict]:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        player = self._get_player(room, player_id)

        all_messages = [
            *room.get("messages", []),
            *player.get("private_messages", []),
        ]

        return sorted(
            all_messages,
            key=lambda message: message.get(
                "created_at",
                "",
            ),
        )
