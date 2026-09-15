from datetime import datetime, timezone
from uuid import uuid4

from app.services.script_loader import ScriptLoader
from app.config import get_storage_config
from app.persistence.mysql_store import MysqlRoomStore
from app.persistence.redis_store import RedisRoomStore

class RoomRepository:
    def __init__(self):
        self._rooms = {}
        self._script_loader = ScriptLoader()
        storage = get_storage_config()
        if not storage["mysql_url"]:
            raise RuntimeError("必须配置 MYSQL_URL")

        self._redis_store = RedisRoomStore(storage["redis_url"])
        self._mysql_store = MysqlRoomStore(storage["mysql_url"])

        # Redis 是实时首选；Redis 中没有的房间从 MySQL 恢复到 Redis。
        for room in self._mysql_store.list_all():
            if not self._redis_store.get(room["id"]):
                self._redis_store.save(room)

    def save(self, room_id: str) -> dict | None:
        room = self._rooms.get(room_id)
        if room is None:
            return None

        self._redis_store.save(room)
        self._mysql_store.save(room)
        return room


    def create(
            self,
            script_id:str,
            host_name:str,
    )->dict:
        manifest=self._script_loader.load_manifest(script_id)

        host={
            "id":uuid4().hex[:8].upper(),
            "name":host_name,
            "is_host":True,
            "character_id":None,
            "clue_ids":[],
        }

        room={
            "id":uuid4().hex[:8].upper(),
            "script_id":script_id,
            "script_version":manifest["version"],
            "status":"waiting",
            "required_players":manifest["player_count"],
            "player_count":1,
            "host_player_id":host["id"],
            "created_at":datetime.now(timezone.utc).isoformat(),
            "players":[host],
            "exited_player_ids": [],
            "dm_status":"ready"
        }

        self._rooms[room["id"]] = room
        self.save(room["id"])
        return room

    def get(self,room_id:str)->dict|None:
        room = self._redis_store.get(room_id)
        if room is not None:
            self._rooms[room_id] = room
            return room

        room = self._mysql_store.get(room_id)
        if room is not None:
            self._rooms[room_id] = room
            self._redis_store.save(room)
            return room

        return None

    def join(self,room_id:str,name:str)->dict|None:
        room=self.get(room_id)

        if room is None:
            return None
        if room["status"]!="waiting":
            raise ValueError("当前房间不能加入")
        if room["player_count"]>=room["required_players"]:
            raise ValueError("房间人数已满")
        player={
            "id":uuid4().hex[:8].upper(),
            "name":name,
            "is_host":False,
            "character_id":None,
            "clue_ids":[],
        }

        room["players"].append(player)
        room["player_count"]+=1
        self.save(room_id)

        return player

    def list_players(self,room_id:str)->list[dict]|None:
        room=self.get(room_id)

        if room is None:
            return None

        return room["players"]

    def assign_character(
            self,
            room_id:str,
            player_id:str,
            character_id:str,
    )->dict|None:
        room=self.get(room_id)

        if room is None:
            return None

        for player in room["players"]:
            if player["id"]==player_id:
                player["character_id"]=character_id
                self.save(room_id)
                return player

        return None
    
    def start(self,room_id:str)->dict|None:
        room=self.get(room_id)

        if room is None:
            return None

        if room["status"]!="waiting":
            raise ValueError("当前房间不是等待状态")

        if room["player_count"]!=room["required_players"]:
            raise ValueError(f"需要正好{room['required_players']}名玩家才能开始")

        room["status"]="playing"
        room["dm_status"]="running"
        self.save(room_id)

        return room

    def list_waiting(self)->list[dict]:
        rooms = [
            room
            for room in self._list_rooms()
            if room["status"] == "waiting"
            and room["player_count"] < room["required_players"]
        ]
        return sorted(
            rooms,
            key=lambda room: room.get("created_at", ""),
            reverse=True,
        )

    def _list_rooms(self) -> list[dict]:
        rooms = self._redis_store.list_all()
        redis_room_ids = {room.get("id") for room in rooms}
        for room in self._mysql_store.list_all():
            if room.get("id") not in redis_room_ids:
                self._redis_store.save(room)
                rooms.append(room)
        self._rooms.update({room["id"]: room for room in rooms})
        return rooms

    def mark_player_exited(self, room_id: str, player_id: str) -> dict:
        room = self.get(room_id)

        if room is None:
            raise FileNotFoundError("房间不存在")

        player_ids = {
            player.get("id")
            for player in room.get("players", [])
            if player.get("id")
        }
        if player_id not in player_ids:
            raise ValueError("玩家不在这个房间中")

        exited_player_ids = room.setdefault("exited_player_ids", [])
        if player_id not in exited_player_ids:
            exited_player_ids.append(player_id)

        remaining_players = len(player_ids.difference(exited_player_ids))
        self.save(room_id)
        return {
            "room_id": room_id,
            "player_id": player_id,
            "destroyed": remaining_players == 0,
            "remaining_players": remaining_players,
        }

    def destroy(self, room_id: str) -> dict | None:
        room = self._rooms.pop(room_id, None)
        self._redis_store.delete(room_id)
        self._mysql_store.delete(room_id)
        return room
