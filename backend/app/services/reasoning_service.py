class ReasoningService:
    def __init__(self, room_repository, bundle_loader):
        self.room_repository = room_repository
        self.bundle_loader = bundle_loader

    def unlock_rule(
        self,
        room_id: str,
        player_id: str,
        rule_id: str,
        reasoning: str,
    ) -> dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("room not found")
        if room["status"] != "playing":
            raise ValueError("game has not started")

        player = next(
            (item for item in room.get("players", [])
             if item.get("id") == player_id),
            None,
        )
        if player is None:
            raise ValueError("player is not in this room")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        stage_id = room.get("game", {}).get("stage_id")
        rule = next(
            (item for item in bundle.get("unlock_rules", [])
             if item.get("id") == rule_id),
            None,
        )
        if rule is None:
            raise ValueError("reasoning rule not found")
        if stage_id not in rule.get("allowed_stages", []):
            raise ValueError("rule is not allowed in the current stage")

        reasoning_state = room.setdefault(
            "reasoning",
            {"triggered_rule_ids": []},
        )
        if (
            rule.get("once", False)
            and rule_id in reasoning_state["triggered_rule_ids"]
        ):
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": "This reasoning clue has already been triggered.",
                "rule_id": rule_id,
                "clue_ids": [],
                "delivery": "triggering_player",
            }

        clue_ids = list(rule.get("unlock_clues", []))
        player_clue_ids = player.setdefault("clue_ids", [])
        for clue_id in clue_ids:
            if clue_id not in player_clue_ids:
                player_clue_ids.append(clue_id)

        reasoning_state["triggered_rule_ids"].append(rule_id)

        self.room_repository.save(room_id)

        return {
            "channel": "PRIVATE_MESSAGE",
            "message": rule.get(
                "private_message",
                "Your reasoning revealed a private clue.",
            ),
            "rule_id": rule_id,
            "clue_ids": clue_ids,
            "delivery": "triggering_player",
        }
