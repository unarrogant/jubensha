from typing import Literal

from pydantic import BaseModel, Field


class DMAgentModelResult(BaseModel):
    content: str


class DMAgentResult(BaseModel):
    visibility: Literal["private", "public"]
    content: str
    clue_ids: list[str] = Field(default_factory=list)
