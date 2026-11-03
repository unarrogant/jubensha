from pydantic import BaseModel, Field 


class CluePublic(BaseModel):
    id: str
    title: str
    content: str
    title_zh: str | None = None
    content_zh: str | None = None
    asset: str | None = None
    visibility: str | None = None
    tags: list[str] = Field(default_factory=list)