from typing import Literal

from pydantic import BaseModel,Field


class DMMessagePublic(BaseModel):
    id: str
    type: Literal["DM_MESSAGE"]
    channel: Literal[
        "PUBLIC_MESSAGE",
        "PRIVATE_MESSAGE",
    ]
    content: str
    clue_ids: list[str] = Field(default_factory=list)
    created_at: str