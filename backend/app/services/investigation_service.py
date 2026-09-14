from typing import Any

from app.repositories.room_repository import RoomRepository
from app.services.script_bundle import ScriptBundleLoader

class InvestigationService:
    def __init__(
        self,
        room_repository:RoomRepository,
        bundle_loader:ScriptBundleLoader,
    ):
        self.room_repository=room_repository
        self.bundle_loader=bundle_loader

    def _get_room(self,room_id:str)->dict:
        room=self.room_repository.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        if room["status"] != "playing":
            raise ValueError("游戏尚未开始")

        game = room.get("game", {})

        if game.get("stage_id") != "investigation":
            raise ValueError("当前不是搜证阶段")

        return room

    @staticmethod
    def _get_player(
        room:dict,
        player_id:str,
    )->dict:
        for player in room["players"]:
            if player["id"]==player_id:
                return player
        raise ValueError("玩家不在这个房间中")

    def _load_locations(self,room:dict)->dict:
        bundle=self.bundle_loader.load(
            room["script_id"],
            room["script_version"]
        )

        locations=bundle.get("locations")

        if not isinstance(locations,dict):
            raise ValueError("location.json必须是对象")

        return locations

    @staticmethod
    def _find_location(
        locations:dict,
        location_id:str,
    )->tuple[dict|None,bool]:
        """
        返回：
        location:找到的地点
        searchable:是否是可以搜查物品的地点
        """

        for location in locations.get("locations",[]):
            if location.get("id")==location_id:
                return location,True

        for location in locations.get("ambient_locations",[]):
            if location.get("id")==location_id:
                return location,False

        return None,False

    @staticmethod
    def _normalize_text(text:str)->str:
        return "".join(text.strip().lower().split())

    @classmethod
    def _find_object(
        cls,
        location:dict,
        object_text:str,
    )->dict|None:
        target=cls._normalize_text(object_text)

        for searchable_object in location.get(
            "searchable_objects",
            [],
        ):
            names=[
                searchable_object.get("name",""),
                *searchable_object.get("aliases",[]),
            ]

            for name in names:
                normalized_name=cls._normalize_text(name)

                if(
                    target==normalized_name or normalized_name in target or target in normalized_name
                ):
                    return searchable_object

        return None

    @staticmethod
    def _session_data(room:dict)->dict:
        return room.setdefault(
            "investigation",
            {
                "entered_locations":[],
                "discovered_clue_ids":[],
            },
        )

    def enter_location(
        self,
        room_id:str,
        player_id:str,
        location_id:str,
    )->dict[str,Any]:
        room =self._get_room(room_id)
        self._get_player(room,player_id)

        locations=self._load_locations(room)

        location,searchable=self._find_location(
            locations,
            location_id,
        )

        if location is None:
            raise ValueError("地点不存在")

        session=self._session_data(room)

        if location_id not in session["entered_locations"]:
            session["entered_locations"].append(location_id)

        if searchable:
            message = location.get(
                "entry_narration",
                "你进入了这个地点。",
            )
        else:
            message = location.get(
                "description",
                "这里没有更多发现。",
            )

        self.room_repository.save(room_id)

        return {
            "channel": "PRIVATE_MESSAGE",
            "message": message,
            "clue_id": None,
        }

    def inspect_object(
        self,
        room_id:str,
        player_id: str,
        location_id: str,
        object_text: str,
    )->dict[str,Any]:
        room=self._get_room(room_id)
        player=self._get_player(room,player_id)

        locations = self._load_locations(room)

        location, searchable = self._find_location(
            locations,
            location_id,
        )

        if location is None:
            raise ValueError("地点不存在")

        # ambient_locations 永远不发线索
        if not searchable:
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": "没有更多发现。",
                "clue_id": None,
            }

        searchable_object = self._find_object(
            location,
            object_text,
        )

        #玩家检查不存在或无关的，不提供提示
        if searchable_object is None:
            return {
                "channel":"PRIVATE_MESSAGE",
                "message":"没有更多发现",
                "clue_id":None,
            }

        result=searchable_object.get("result",{})
        result_type=result.get("type")

        #普通无关物品
        if result_type!="clue":
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": result.get(
                    "message",
                    "没有更多发现。",
                ),
                "clue_id": None,
            }

        clue_id = result.get("clue_id")

        if not clue_id:
            raise ValueError("线索物品缺少 clue_id")

        session = self._session_data(room)
        discovered_clue_ids = session["discovered_clue_ids"]

        #每条线索只找到一次
        if clue_id in discovered_clue_ids:
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": "这里已经被仔细检查过了，没有更多发现。",
                "clue_id": None,
            }

        discovered_clue_ids.append(clue_id)

        player_clue_ids=player.setdefault(
            "clue_ids",
            [],
        )
        
        if clue_id not in player_clue_ids:
            player_clue_ids.append(clue_id)

        self.room_repository.save(room_id)

        return {
            "channel": "PRIVATE_MESSAGE",
            "message": result.get(
                "message",
                "你发现了一些异常。",
            ),
            "clue_id": clue_id,
        }

