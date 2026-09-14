from typing import Literal

from pydantic import BaseModel, Field


class PlayerPrivateMessageCreate(BaseModel):
    player_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=1000)


class PlayerPrivateMessagePublic(BaseModel):
    id: str
    type: Literal["PLAYER_PRIVATE_MESSAGE"]
    channel:Literal["PRIVATE_MESSAGE"]
    player_name: str
    content: str
    created_at: str