import random

from app.repositories.room_repository import RoomRepository
from app.services.script_bundle import ScriptBundleLoader

class RoleService:
    def __init__(
            self,
            room_repository:RoomRepository,
            bundle_loader:ScriptBundleLoader|None=None,
    ):
        self.room_repository=room_repository
        self.bundle_loader=bundle_loader or ScriptBundleLoader()

    def assign_roles(self,room_id:str)->list[dict]:
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        if room["status"]!="waiting":
            raise ValueError("只能在等待状态分配角色")

        if room["player_count"]!=room["required_players"]:
            raise ValueError(
                f"需要正好{room["required_players"]}名玩家才能分配角色"
            )

        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        characters=bundle["characters"]

        if not isinstance(characters,list):
            raise ValueError("character.json必须是数组")

        if len(characters)!=room["player_count"]:
            raise ValueError("角色数量必须与玩家数量一致")

        for player in room["players"]:
            if player.get("character_id")is not None:
                raise ValueError("角色已经分配过了")

        shuffled_characters=list(characters)
        random.shuffle(shuffled_characters)

        for player,character in zip(
            room["players"],
            shuffled_characters,
        ):
            character_id=character.get("id")

            if not character_id:
                raise ValueError("角色缺少id")

            self.room_repository.assign_character(
                room_id=room_id,
                player_id=player["id"],
                character_id=character_id,
            )

        return room["players"]