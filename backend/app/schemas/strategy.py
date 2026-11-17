from pydantic import BaseModel

from app.models.enums import StrategyLifecycle


class StrategySummary(BaseModel):
    id: str
    name: str
    symbol: str | None
    category: str
    timeframe: str
    lifecycle: StrategyLifecycle
    created_at: str

    model_config = {"from_attributes": True}