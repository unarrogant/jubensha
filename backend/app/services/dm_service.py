from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.room_repository import RoomRepository

class DMService:
    def __init__(
            self,
            room_repository:RoomRepository,
    ):
        self.room_repository=room_repository

    def _get_room(self,room_id:str)->dict:
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        if room["status"] != "playing":
            raise ValueError("游戏尚未开始")

        return room

    @staticmethod
    def _get_player(
        room: dict,
        player_id: str,
    ) -> dict:
        for player in room["players"]:
            if player["id"] == player_id:
                return player

        raise ValueError("玩家不在这个房间中")
    @staticmethod
    def _new_message(
        channel:str,
        content:str,
        clue_ids:list[str] | None = None,
    )->dict:
        message = {
            "id": uuid4().hex,
            "type": "DM_MESSAGE",
            "channel": channel,
            "content": content.strip(),
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        if clue_ids:
            message["clue_ids"] = list(clue_ids or [])

        return message

    def send_public(
        self,
        room_id:str,
        content:str,
        clue_ids: list[str] | None = None,
    )->dict:
        room=self._get_room(room_id)

        if not content.strip():
            raise ValueError("消息不能为空")

        message = self._new_message(
            channel="PUBLIC_MESSAGE",
            content=content,
            clue_ids=clue_ids,
        )

        room.setdefault("messages", []).append(message)
        self.room_repository.save(room_id)

        return message

    def send_private(
        self,
        room_id:str,
        player_id:str,
        content:str,
        clue_ids: list[str] | None = None,
    )->dict:
        room=self._get_room(room_id)
        player=self._get_player(room,player_id)

        if not content.strip():
            raise ValueError("消息不能为空")

        message = self._new_message(
            channel="PRIVATE_MESSAGE",
            content=content,
            clue_ids=clue_ids,
        )

        player.setdefault(
            "private_messages",
            [],
        ).append(message)
        self.room_repository.save(room_id)

        return message

    def list_private_message(
        self,
        room_id:str,
        player_id:str,
    )->list[dict]:
        room = self._get_room(room_id)
        player = self._get_player(room, player_id)

        return player.get(
            "private_messages",
            [],
        )
