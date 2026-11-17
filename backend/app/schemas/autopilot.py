from pydantic import BaseModel


class AutopilotStatus(BaseModel):
    hourly_enabled: bool
    ai_configured: bool
    message: str
    top_backtests: list[dict]
    recent_activity: list[dict]


class AutopilotRunResponse(BaseModel):
    job_id: str | None
    status: str
    mode: str