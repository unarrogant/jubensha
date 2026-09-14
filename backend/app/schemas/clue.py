from pydantic import BaseModel, Field 


class CluePublic(BaseModel):
    id: str
    title: str
    content: str
    asset: str | None = None
    tags: list[str] = Field(default_factory=list)