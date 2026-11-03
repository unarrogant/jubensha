from app.interfaces.ports import RoomRepositoryPort, ScriptBundlePort


class ContextAssembler:
    """Build the smallest trusted context needed by an Agent request."""

    def __init__(
        self,
        room_repository: RoomRepositoryPort,
        bundle_loader: ScriptBundlePort,
    ):
        self.room_repository = room_repository
        self.bundle_loader = bundle_loader

    def build_player_context(
        self,
        room_id: str,
        player_id: str,
        content: str,
    ) -> dict:
        room = self.room_repository.get(room_id)
        if room is None:
            raise FileNotFoundError("房间不存在")

        player = next(
            (item for item in room.get("players", []) if item.get("id") == player_id),
            None,
        )
        if player is None:
            raise ValueError("玩家不在这个房间")

        bundle = self.bundle_loader.load(room["script_id"], room["script_version"])
        game = room.get("game", {})
        stage_id = game.get("stage_id")
        current_stage = next(
            (stage for stage in bundle.get("stages", []) if stage.get("id") == stage_id),
            None,
        )

        character = next(
            (
                item
                for item in bundle.get("characters", [])
                if item.get("id") == player.get("character_id")
            ),
            None,
        )
        if character is None:
            raise ValueError("玩家角色尚未分配")

        character_map = {
            item.get("id"): item.get("name")
            for item in bundle.get("characters", [])
        }
        player_list = [
            {
                "name": item.get("name"),
                "character_name": character_map.get(item.get("character_id")),
            }
            for item in room.get("players", [])
        ]

        discovered_ids = room.get("investigation", {}).get(
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
        discovered_clue_refs = [
            {"id": clue.get("id"), "name": clue.get("name")}
            for clue in discovered_clues
        ]

        return {
            "DM_SYSTEM": bundle.get("dm_system", ""),
            "STATIC_CONTEXT": {
                "SCRIPT_MANIFEST": bundle.get("manifest", {}),
                "CHARACTER_CONTEXT": character,
                "LOCATION_CONTEXT": bundle.get("locations", {}),
                "UNLOCK_RULE_CONTEXT": bundle.get("unlock_rules", []),
                "PLAYER_LIST": player_list,
            },
            "CURRENT_STAGE": current_stage,
            "GAME_STATE": game,
            "CURRENT_PLAYER": {
                "id": player["id"],
                "name": player["name"],
            },
            "CLUE_CONTEXT": {
                "player_clues": player_clues,
                "discovered_clues": discovered_clue_refs,
            },
            "PLAYER_MESSAGE": content,
        }

    def build_public_context(
        self,
        room_id: str,
        event_type: str,
        event_payload: dict | None = None,
    ) -> dict:
        room = self.room_repository.get(room_id)
        if room is None:
            raise FileNotFoundError("房间不存在")

        bundle = self.bundle_loader.load(room["script_id"], room["script_version"])
        game = room.get("game", {})
        stage_id = game.get("stage_id")
        current_stage = next(
            (stage for stage in bundle.get("stages", []) if stage.get("id") == stage_id),
            None,
        )
        character_map = {
            character.get("id"): character.get("name")
            for character in bundle.get("characters", [])
        }
        player_list = [
            {
                "name": player.get("name"),
                "character_name": character_map.get(player.get("character_id")),
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
