from typing import Literal

from pydantic import BaseModel,Field

class RoomCreate(BaseModel):
    script_id:str=Field(min_length=1)
    host_name:str=Field(min_length=1,max_length=20)

class RoomPublic(BaseModel):
    id:str
    script_id:str
    script_version:int
    status:Literal["waiting","playing","ended"]
    required_players:int
    player_count:int
    dm_status:Literal["ready","running","stopped"]

class RoomListItem(RoomPublic):
    host_name:str
    created_at:str

class RoomCreateResponse(RoomPublic):
    host_player_id:str

class RoomStart(BaseModel):
    host_player_id:str=Field(min_length=1)

class RoomExit(BaseModel):
    player_id: str = Field(min_length=1)

class RoomExitResponse(BaseModel):
    room_id: str
    player_id: str
    destroyed: bool
    remaining_players: int

    
