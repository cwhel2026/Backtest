from pydantic import BaseModel, Field

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


class StrategyVersionOut(BaseModel):
    id: str
    version_number: int
    specification: dict
    changelog: str
    created_at: str


class StrategyCreateRequest(BaseModel):
    specification: dict
    economic_rationale: str = Field(default="", max_length=4000)


class StrategyCloneRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)


class StrategyDetail(BaseModel):
    id: str
    name: str
    symbol: str
    category: str
    timeframe: str
    lifecycle: StrategyLifecycle
    created_at: str
    current_version: StrategyVersionOut | None
    latest_backtest: dict | None = None