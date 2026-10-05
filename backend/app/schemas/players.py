from pydantic import BaseModel,Field
class PlayerJoin(BaseModel):
    name:str=Field(min_length=1,max_length=20)

class PlayerJoinResponse(BaseModel):
    id:str
    name:str
    is_host:bool

class PlayerListItem(BaseModel):
    name:str
    character_name:str|None=None
    character_avatar:str|None=None

class VocabularyAnnotation(BaseModel):
    term: str
    forms: list[str] = Field(default_factory=list)
    pronunciation: str = ""
    part_of_speech: str = ""
    meaning: str
    example: str = ""

class CharacterPrivate(BaseModel):
    id: str
    name: str
    tagline: str | None = None
    avatar: str | None = None
    public_profile: str | None = None
    private_background: str | None = None
    case_background: str | None = None
    case_details: list[dict] = Field(default_factory=list)
    core_rules: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    story: list[str] = Field(default_factory=list)
    initial_information: list[str] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    vocabulary: list[VocabularyAnnotation] = Field(default_factory=list)
    
