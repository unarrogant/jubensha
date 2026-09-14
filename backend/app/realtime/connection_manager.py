from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.connections:dict[
            str,
            dict[str,list[WebSocket]],
        ]={}

    async def connect(
        self,
        room_id: str,
        player_id: str,
        websocket: WebSocket,
    )->None:
        await websocket.accept()

        room_connections=self.connections.setdefault(
            room_id,
            {},
        )

        player_connections=room_connections.setdefault(
            player_id,
            [],
        )

        player_connections.append(websocket)

    def disconnect(
        self,
        room_id:str,
        player_id: str,
        websocket: WebSocket,
    )->bool:
        room_connections = self.connections.get(room_id)

        if room_connections is None:
            return False

        player_connections = room_connections.get(player_id)

        if player_connections is None:
            return False

        if websocket in player_connections:
            player_connections.remove(websocket)

        if not player_connections:
            room_connections.pop(player_id)

        if not room_connections:
            self.connections.pop(room_id)

        return not player_connections

    def get_player_ids(self, room_id: str) -> list[str]:
        return list(self.connections.get(room_id, {}).keys())

    def remove_room(self, room_id: str) -> None:
        self.connections.pop(room_id, None)

    def is_connected(self, room_id: str, player_id: str) -> bool:
        return bool(
            self.connections.get(room_id, {}).get(player_id)
        )

    async def broadcast_room(
        self,
        room_id:str,
        event:dict,
        exclude_player_id: str | None = None,
    )->None:
        room_connections = self.connections.get(room_id, {})

        for player_id, player_connections in room_connections.items():
            if player_id == exclude_player_id:
                continue
            for websocket in list(player_connections):
                await websocket.send_json(event)

    async def send_to_player(
        self,
        room_id: str,
        player_id: str,
        event: dict,
    ) -> None:
        player_connections = self.connections.get(
            room_id,
            {},
        ).get(player_id, [])

        for websocket in list(player_connections):
            await websocket.send_json(event)

connection_manager = ConnectionManager()
