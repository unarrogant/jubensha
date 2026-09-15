from collections import Counter
from datetime import datetime,timezone,timedelta
import random

from app.repositories.room_repository import RoomRepository
from app.services.script_bundle import ScriptBundleLoader

class GameService:
    def __init__(
            self,
            room_repository:RoomRepository,
            bundle_loader:ScriptBundleLoader,
    ):
        self.room_repository=room_repository
        self.bundle_loader=bundle_loader

    def initialize(self,room_id:str)->dict:
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        if room["status"]!="waiting":
            raise ValueError("房间已经开始或结束了")
        

        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        stages=bundle["stages"]

        intro_stage=None

        for stage in stages:
            if stage.get("id")=="intro":
                intro_stage=stage
                break


        if intro_stage is None:
            raise ValueError("stages.json缺少intro阶段")
        now = datetime.now(timezone.utc)
        duration_seconds = intro_stage.get("duration_seconds", 0)

        room["game"]={
            "stage_id":intro_stage["id"],
            "stage_status":"active",
            "stage_started_at":now.isoformat(),
            "stage_duration_seconds":duration_seconds,
            "stage_deadline": (
                now + timedelta(seconds=duration_seconds)
            ).isoformat(),
            "dm_status":"running",
            "vote_open": False,
        }
        room["votes"] = {}
        room.pop("ending", None)
        room["initial_clues_released"] = False
        room["public_clue_ids"] = []

        self.room_repository.save(room_id)

        return room["game"]

    def _find_stage(
            self,
            stages:list[dict],
            stage_id:str,
    )->dict|None:
        for stage in stages:
            if stage.get("id")==stage_id:
                return stage
        return None

    def get_public_state(self,room_id:str)->dict:
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        game=room.get("game",{})
        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        stage=self._find_stage(
            bundle.get("stages",[]),
            game.get("stage_id"),
        )
        stage_deadline=game.get("stage_deadline")
        remaining_seconds=None
        votes = room.get("votes", {})
        ending = room.get("ending") if game.get("stage_id") == "ending" else None

        if stage_deadline:
            deadline=datetime.fromisoformat(stage_deadline)
            remaining_seconds=max(
                0,
                int(
                    (
                        deadline-datetime.now(timezone.utc)
                    ).total_seconds()
                ),
            )

        return {
            "room_id":room["id"],
            "room_status":room["status"],
            "stage_id":game.get("stage_id"),
            "stage_name":stage.get("name") if stage else None,
            "stage_description":stage.get("description") if stage else None,
            "stage_status":game.get("stage_status"),
            "stage_started_at":game.get("stage_started_at"),
            "stage_duration_seconds":game.get("stage_duration_seconds"),
            "stage_deadline":stage_deadline,
            "remaining_seconds":remaining_seconds,
            "dm_status":game.get(
                "dm_status",
                room.get("dm_status","ready"),
            ),
            "vote_count": len(votes),
            "required_votes": room.get("required_players", 0),
            "ending": ending,
            "vote_open": bool(game.get("vote_open", False)),
        }

    def cast_vote(self, room_id: str, player_id: str, suspect_id: str) -> dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")
        if room.get("status") != "playing":
            raise ValueError("游戏尚未开始或已经结束")
        if room.get("game", {}).get("stage_id") != "voting":
            raise ValueError("当前阶段不允许投票")
        if not room.get("game", {}).get("vote_open", False):
            raise ValueError("主持人尚未宣布投票开始")

        player = next(
            (item for item in room.get("players", []) if item.get("id") == player_id),
            None,
        )
        if player is None:
            raise ValueError("玩家不在这个房间中")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        valid_suspect_ids = {
            character.get("id")
            for character in bundle.get("characters", [])
            if character.get("id")
        }
        if suspect_id not in valid_suspect_ids:
            raise ValueError("无效的指认对象")

        votes = room.setdefault("votes", {})
        if player_id in votes:
            raise ValueError("你已经投过票了，每名玩家只能投一票")

        votes[player_id] = suspect_id
        self.room_repository.save(room_id)
        return {
            "submitted": True,
            "vote_count": len(votes),
            "required_votes": room.get("required_players", 0),
        }

    def get_vote_status(self, room_id: str, player_id: str) -> dict:
        room = self.room_repository.get(room_id)
        if room is None:
            raise FileNotFoundError("房间不存在")

        player_exists = any(
            item.get("id") == player_id
            for item in room.get("players", [])
        )
        if not player_exists:
            raise ValueError("玩家不在这个房间中")
        if room.get("game", {}).get("stage_id") not in {"voting", "ending"}:
            raise ValueError("投票尚未开始")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        character_map = {
            character.get("id"): character
            for character in bundle.get("characters", [])
        }
        suspect_id = room.get("votes", {}).get(player_id)
        return {
            "has_voted": suspect_id is not None,
            "suspect_id": suspect_id,
            "vote_count": len(room.get("votes", {})),
            "required_votes": room.get("required_players", 0),
            "candidates": [
                {
                    "suspect_id": candidate.get("character_id"),
                    "character_name": character_map.get(
                        candidate.get("character_id"),
                        {},
                    ).get("name"),
                    "player_name": candidate.get("name"),
                    "avatar": character_map.get(
                        candidate.get("character_id"),
                        {},
                    ).get("avatar"),
                }
                for candidate in room.get("players", [])
                if candidate.get("character_id")
            ],
        }

    def resolve_ending(self, room_id: str) -> dict:
        room = self.room_repository.get(room_id)
        if room is None:
            raise FileNotFoundError("房间不存在")

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        votes = room.get("votes", {})
        tally = Counter(votes.values())
        highest_count = max(tally.values(), default=0)
        leaders = sorted(
            suspect_id
            for suspect_id, count in tally.items()
            if count == highest_count
        )
        top_suspect = leaders[0] if len(leaders) == 1 else None

        matched_ending = next(
            (
                ending
                for ending in bundle.get("endings", [])
                if ending.get("trigger", {}).get("suspect_id") == top_suspect
            ),
            None,
        )

        if len(leaders) > 1:
            result = {
                "id": "ending_tied_vote",
                "title": "王冠前的僵局",
                "narrative": "最高票出现平局，众人的指认无法汇成唯一结论。真正的弑君者借着争执藏回阴影，苏格兰的王冠仍被猜忌与鲜血笼罩。",
                "truth_reveal": [
                    "本局投票没有产生唯一最高票角色。",
                    "麦克白亲手以涂毒的匕首杀死邓肯，麦克白夫人协助策划并伪造现场。",
                    "班柯知情却保持沉默，其他人的政治秘密则干扰了众人的判断。",
                ],
                "character_fates": {},
                "winner": "macbeth",
                "suspect_id": None,
            }
        elif matched_ending is None:
            result = {
                "id": "ending_no_consensus",
                "title": "未形成有效指认",
                "narrative": "本局没有形成可以匹配剧本结局的有效投票，城堡里的疑云仍未散去。",
                "truth_reveal": [],
                "character_fates": {},
                "winner": None,
                "suspect_id": top_suspect,
            }
        else:
            result = {
                **matched_ending,
                "suspect_id": top_suspect,
            }

        result["vote_counts"] = dict(tally)
        result["total_votes"] = len(votes)
        room["ending"] = result
        room.setdefault("game", {})["ending_id"] = result["id"]
        self.room_repository.save(room_id)
        return result

    def _activate_stage(
            self,
            room:dict,
            stage:dict,
            now:datetime,
    )->None:
        duration_seconds=int(
            stage.get("duration_seconds")
        )

        room["game"]={
            **room.get("game",{}),
            "stage_id":stage["id"],
            "stage_status":"active",
            "stage_started_at":now.isoformat(),
            "stage_duration_seconds":duration_seconds,
            "stage_deadline":(
                (
                    now+timedelta(
                        seconds=duration_seconds
                    )
                ).isoformat()
                if duration_seconds>0
                else None

            ),
            "dm_status":"running",
            "vote_open": False,
        }
        room["dm_status"]="running"

    def refresh_stage(self,room_id:str):
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        game=room.get("game")

        if not game:
            return {}

        if room["status"]!="playing":
            return game

        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )

        current_stage=self._find_stage(
            bundle["stages"],
            game["stage_id"],
        )

        if current_stage is None:
            raise ValueError(
                f"找不到阶段{game['stage_id']}"
            )

        if current_stage.get("manual_transition",False):
            return game

        deadline_text=game.get("stage_deadline")

        if not deadline_text:
            return game

        deadline = datetime.fromisoformat(deadline_text)
        now = datetime.now(timezone.utc)

        if now <deadline:
            return game

        next_stage_id=current_stage.get("next_stage")

        if not next_stage_id:
            game["stage_status"] = "finished"
            game["dm_status"] = "stopped"
            room["status"] = "ended"
            room["dm_status"] = "stopped"
            self.room_repository.save(room_id)
            return game

        next_stage=self._find_stage(
            bundle["stages"],
            next_stage_id,
        )

        if next_stage is None:
            raise ValueError(
                f"找不到下一个阶段：{next_stage_id}"
            )

        self._activate_stage(
            room,
            next_stage,
            now,
        )

        self.room_repository.save(room_id)

        return room["game"]

    def finish(self, room_id: str) -> dict:
        room = self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        game = room.setdefault("game", {})
        game["stage_status"] = "finished"
        game["dm_status"] = "stopped"
        room["status"] = "ended"
        room["dm_status"] = "stopped"
        self.room_repository.save(room_id)
        return room

    def release_initial_clues(self, room_id: str) -> list[dict]:
        """进入搜证阶段前，给每位玩家随机发一张非搜证/非推理线索。"""
        room = self.room_repository.get(room_id)
        if room is None:
            raise FileNotFoundError("房间不存在")
        if room.get("status") != "playing":
            raise ValueError("游戏尚未开始")
        if room.get("initial_clues_released"):
            return []

        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        stages = bundle.get("stages", [])
        investigation_stage = next(
            (item for item in stages if item.get("id") == "investigation"),
            {},
        )
        release = investigation_stage.get("initial_clue_release") or {}
        if release.get("enabled", True) is False:
            room["initial_clues_released"] = True
            self.room_repository.save(room_id)
            return []

        # 从地点可搜出的 clue_id 和 unlock_rules 解锁的 clue_id 中排除，
        # 剩下的才是“搜证前随机发放”的独立线索。
        searchable_ids = set()
        locations = bundle.get("locations", {})
        location_items = locations.get("locations", []) if isinstance(locations, dict) else locations
        for location in location_items or []:
            for searchable in location.get("searchable_objects", []):
                result = searchable.get("result", {})
                if result.get("type") == "clue" and result.get("clue_id"):
                    searchable_ids.add(result["clue_id"])

        reasoning_ids = {
            clue_id
            for rule in bundle.get("unlock_rules", [])
            for clue_id in rule.get("unlock_clues", [])
        }
        configured_pool = set(release.get("pool") or [])
        candidates = [
            clue
            for clue in bundle.get("clues", [])
            if clue.get("id")
            and (not configured_pool or clue.get("id") in configured_pool)
            and clue.get("id") not in searchable_ids
            and clue.get("id") not in reasoning_ids
        ]
        if not candidates:
            room["initial_clues_released"] = True
            self.room_repository.save(room_id)
            return []

        clue = random.choice(candidates)
        target = release.get("target", "all")
        if target == "all":
            clue_id = clue["id"]
            for player in room.get("players", []):
                player_clues = player.setdefault("clue_ids", [])
                if clue_id not in player_clues:
                    player_clues.append(clue_id)
            public_clue_ids = room.setdefault("public_clue_ids", [])
            if clue_id not in public_clue_ids:
                public_clue_ids.append(clue_id)
            room["initial_clues_released"] = True
            self.room_repository.save(room_id)
            return [{
                "target": "all",
                "clue_id": clue_id,
                "clue": clue,
            }]

        # 私密模式下才按玩家分别发放；候选不足时允许重复。
        players = room.get("players", [])
        shuffled_candidates = random.sample(
            candidates,
            k=min(len(candidates), len(players)),
        )
        released = []
        for index, player in enumerate(players):
            clue = (
                shuffled_candidates[index]
                if index < len(shuffled_candidates)
                else random.choice(candidates)
            )
            clue_id = clue["id"]
            player_clues = player.setdefault("clue_ids", [])
            if clue_id not in player_clues:
                player_clues.append(clue_id)
            released.append({
                "player_id": player.get("id"),
                "clue_id": clue_id,
                "clue": clue,
            })

        room["initial_clues_released"] = True
        self.room_repository.save(room_id)
        return released
