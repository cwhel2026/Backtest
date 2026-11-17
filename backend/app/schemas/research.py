from pydantic import BaseModel, Field


class ResearchActivityOut(BaseModel):
    id: str
    headline: str
    detail: str
    created_at: str

    model_config = {"from_attributes": True}


class AiGenerateRequest(BaseModel):
    instrument_symbol: str = Field(min_length=1, max_length=16)
    timeframe: str = Field(default="5m", pattern=r"^(1m|5m|15m|1h)$")
    prompt: str = Field(default="", max_length=2000)
    dataset_id: str | None = None


class AiGenerateResponse(BaseModel):
    job_id: str
    status: str
    mode: str


class ResearchJobOut(BaseModel):
    id: str
    kind: str
    status: str
    title: str
    message: str
    progress_pct: int
    created_at: str

    model_config = {"from_attributes": True}