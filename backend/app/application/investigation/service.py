from typing import Any

from app.interfaces.ports import RoomRepositoryPort, ScriptBundlePort

class InvestigationService:
    def __init__(
        self,
        room_repository:RoomRepositoryPort,
        bundle_loader:ScriptBundlePort,
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
    def _public_object(searchable_object: dict) -> dict:
        return {
            "id": searchable_object.get("id"),
            "name": searchable_object.get("name", ""),
            "name_zh": (
                searchable_object.get("name_zh")
                or searchable_object.get("name", "")
            ),
        }

    @staticmethod
    def _public_location(
        location:dict,
        objects:list[dict]=(),
    )->dict:
        # 只暴露名称与氛围文字，绝不带出线索或答案。
        # 可搜查与否同样不外传，否则玩家能反推哪个地点藏有线索。
        return {
            "id":location.get("id"),
            "name":location.get("name",""),
            "name_zh":location.get("name_zh") or location.get("name",""),
            "summary":location.get("public_summary") or location.get("description",""),
            "summary_zh":(
                location.get("public_summary_zh")
                or location.get("description_zh")
                or location.get("public_summary")
                or location.get("description","")
            ),
            "objects":list(objects),
        }

    def list_visible_locations(
        self,
        room_id:str,
        player_id:str,
    )->dict[str,Any]:
        room=self._get_room(room_id)
        self._get_player(room,player_id)

        locations=self._load_locations(room)
        searchable_locations=locations.get("locations",[])
        ambient_locations=locations.get("ambient_locations",[])

        merged:list[tuple[dict,bool]]=[]
        for index in range(max(len(searchable_locations),len(ambient_locations))):
            if index < len(searchable_locations):
                merged.append((searchable_locations[index],True))
            if index < len(ambient_locations):
                merged.append((ambient_locations[index],False))

        session=self._session_data(room)
        entered_ids=self._player_list(session,"entered_locations",player_id)
        entered=set(entered_ids)

        # 物品名只在玩家进入过该地点之后下发，进门前后是同一条保密边界。
        public_locations=[]
        for location,searchable in merged:
            objects=[]
            if searchable and location.get("id") in entered:
                objects=[
                    self._public_object(searchable_object)
                    for searchable_object in location.get("searchable_objects",[])
                ]
            public_locations.append(self._public_location(location,objects))

        return {
            "entered_location_ids":list(entered_ids),
            "searched_object_ids":list(
                self._player_list(session,"inspected_object_ids",player_id)
            ),
            "locations":public_locations,
        }

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
        target=cls._normalize_text(object_text or "")

        if not target:
            return None

        for searchable_object in location.get(
            "searchable_objects",
            [],
        ):
            names=[
                searchable_object.get("name",""),
                searchable_object.get("name_zh",""),
                *searchable_object.get("aliases",[]),
            ]

            for name in names:
                normalized_name=cls._normalize_text(name or "")

                if not normalized_name:
                    continue

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
                "entered_locations":{},
                "discovered_clue_ids":[],
                "inspected_object_ids":{},
            },
        )

    @staticmethod
    def _player_list(session:dict,key:str,player_id:str)->list:
        #进入与翻查都是玩家自己的动作，所以按玩家分开记；
        #旧对局留下的共享列表直接丢弃，不影响进行中的对局。
        stored=session.get(key)

        if not isinstance(stored,dict):
            stored={}
            session[key]=stored

        return stored.setdefault(player_id,[])

    def enter_location(
        self,
        room_id:str,
        player_id:str,
        location_id:str,
        with_objects:bool=False,
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
        entered_ids=self._player_list(session,"entered_locations",player_id)

        if location_id not in entered_ids:
            entered_ids.append(location_id)

        if searchable:
            message = location.get(
                "entry_narration_zh",
                location.get("entry_narration", "你进入了这个地点。"),
            )
        else:
            message = location.get(
                "description_zh",
                location.get("description", "你在这里站了一会儿，只听见自己的呼吸。"),
            )

        self.room_repository.save(room_id)

        response = {
            "channel": "PRIVATE_MESSAGE",
            "message": message,
            "clue_id": None,
        }

        # 物品清单只给前端界面使用；DM 工具默认拿不到，避免主持人把答案念给玩家。
        if with_objects:
            response["objects"] = [
                self._public_object(searchable_object)
                for searchable_object in location.get("searchable_objects", [])
            ] if searchable else []

        return response

    def _find_clue(self, room: dict, clue_id: str) -> dict:
        bundle = self.bundle_loader.load(
            room["script_id"],
            room["script_version"],
        )
        for clue in bundle.get("clues", []):
            if clue.get("id") == clue_id:
                return clue
        return {}

    def _release_clue(self, room: dict, player: dict, clue_id: str) -> str:
        """记录线索归属；公开线索同时进入每个玩家的线索墙。"""
        session = self._session_data(room)
        session["discovered_clue_ids"].append(clue_id)

        clue = self._find_clue(room, clue_id)
        visibility = clue.get("visibility", "private")

        recipients = room["players"] if visibility == "public" else [player]
        for recipient in recipients:
            recipient_clue_ids = recipient.setdefault("clue_ids", [])
            if clue_id not in recipient_clue_ids:
                recipient_clue_ids.append(clue_id)

        if visibility == "public":
            public_clue_ids = room.setdefault("public_clue_ids", [])
            if clue_id not in public_clue_ids:
                public_clue_ids.append(clue_id)

        return visibility

    @staticmethod
    def _nothing_found()->dict[str,Any]:
        return {
            "channel": "PRIVATE_MESSAGE",
            "message": "你什么也没再找到。",
            "clue_id": None,
            "already_discovered": False,
        }

    @staticmethod
    def _result_message(result:dict)->str:
        return (
            result.get("message_zh")
            or result.get("message")
            or "你什么也没再找到。"
        )

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
            return self._nothing_found()

        searchable_object = self._find_object(
            location,
            object_text,
        )

        #玩家检查不存在或无关的，不提供提示
        if searchable_object is None:
            return self._nothing_found()

        result=searchable_object.get("result",{})
        result_type=result.get("type")

        session = self._session_data(room)

        #记下这件是本人翻过的，刷新后界面仍标成“已搜查”。
        #它只用于展示，不参与任何线索判定，也不会传给其他玩家。
        inspected = self._player_list(session, "inspected_object_ids", player_id)
        object_id = searchable_object.get("id")

        if object_id and object_id not in inspected:
            inspected.append(object_id)
            self.room_repository.save(room_id)

        #普通无关物品
        if result_type!="clue":
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": self._result_message(result),
                "clue_id": None,
                "already_discovered": False,
            }

        clue_id = result.get("clue_id")

        if not clue_id:
            raise ValueError("线索物品缺少 clue_id")

        discovered_clue_ids = session["discovered_clue_ids"]

        #每条线索只找到一次；对玩家只说“什么也没有”，
        #只在响应里保留机器可读标记，供前端把这一行标成已被翻过。
        if clue_id in discovered_clue_ids:
            return {
                "channel": "PRIVATE_MESSAGE",
                "message": "你什么也没再找到。",
                "clue_id": None,
                "already_discovered": True,
            }

        visibility = self._release_clue(room, player, clue_id)

        self.room_repository.save(room_id)

        return {
            "channel": "PRIVATE_MESSAGE",
            "message": self._result_message(result),
            "clue_id": clue_id,
            "visibility": visibility,
            "already_discovered": False,
        }

