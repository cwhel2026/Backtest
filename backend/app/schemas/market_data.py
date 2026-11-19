from pydantic import BaseModel


class ProviderHealthOut(BaseModel):
    slug: str
    display_name: str
    state: str
    message: str
    capabilities: dict


class HistoricalDatasetOut(BaseModel):
    id: str
    instrument_id: str
    provider_id: str
    timeframe: str
    row_count: int
    validation_status: str
    coverage_start: str | None
    coverage_end: str | None
    version_tag: str
    content_checksum: str | None = None
    storage_uri: str | None = None
    quality_class: str | None = None
    meta: dict = {}

    model_config = {"from_attributes": True}


class IngestEstimateRequest(BaseModel):
    provider_slug: str
    instrument_symbol: str
    timeframe: str = "5m"
    start: str
    end: str

    model_config = {"extra": "forbid"}


class DatasetReadinessOut(BaseModel):
    dataset_id: str
    quality_class: str
    validation_status: str
    video_readiness: dict
    backtest_allowed: bool


class OhlcvBarOut(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int