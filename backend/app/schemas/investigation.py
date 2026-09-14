from pydantic import BaseModel, Field


class EnterLocationRequest(BaseModel):
    player_id: str = Field(min_length=1)
    location_id: str = Field(min_length=1)


class InspectObjectRequest(BaseModel):
    player_id: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    object_text: str = Field(min_length=1, max_length=100)


class InvestigationMessage(BaseModel):
    channel: str
    message: str
    clue_id: str | None = None