from pydantic import BaseModel


class ResearchActivityOut(BaseModel):
    id: str
    headline: str
    detail: str
    created_at: str

    model_config = {"from_attributes": True}


class ResearchJobOut(BaseModel):
    id: str
    kind: str
    status: str
    title: str
    message: str
    progress_pct: int
    created_at: str

    model_config = {"from_attributes": True}