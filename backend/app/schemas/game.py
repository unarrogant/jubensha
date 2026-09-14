from typing import Any

from pydantic import BaseModel, Field


class GameStatePublic(BaseModel):
    room_id: str
    room_status: str
    stage_id: str | None = None
    stage_name: str | None = None
    stage_description: str | None = None
    stage_status: str | None = None
    stage_started_at: str | None = None
    stage_duration_seconds: int | None = None
    stage_deadline: str | None = None
    remaining_seconds: int | None = None
    dm_status: str
    vote_count: int = 0
    required_votes: int = 0
    ending: dict[str, Any] | None = None
    vote_open: bool = False


class VoteCreate(BaseModel):
    player_id: str = Field(min_length=1)
    suspect_id: str = Field(min_length=1)


class VoteResponse(BaseModel):
    submitted: bool
    vote_count: int
    required_votes: int


class VoteStatus(BaseModel):
    has_voted: bool
    suspect_id: str | None = None
    vote_count: int
    required_votes: int
    candidates: list[dict[str, str | None]] = Field(default_factory=list)
