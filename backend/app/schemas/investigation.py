from pydantic import BaseModel, Field


class EnterLocationRequest(BaseModel):
    player_id: str = Field(min_length=1)
    location_id: str = Field(min_length=1)


class InspectObjectRequest(BaseModel):
    player_id: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    object_text: str = Field(min_length=1, max_length=100)


class InvestigationObjectPublic(BaseModel):
    id: str
    name: str = ""
    name_zh: str = ""


class InvestigationLocationPublic(BaseModel):
    id: str
    name: str = ""
    name_zh: str = ""
    summary: str = ""
    summary_zh: str = ""
    objects: list[InvestigationObjectPublic] = Field(default_factory=list)


class InvestigationLocationsPublic(BaseModel):
    entered_location_ids: list[str] = []
    searched_object_ids: list[str] = []
    locations: list[InvestigationLocationPublic] = []


class InvestigationMessage(BaseModel):
    channel: str
    message: str
    clue_id: str | None = None
    visibility: str | None = None
    already_discovered: bool = False
    objects: list[InvestigationObjectPublic] = []