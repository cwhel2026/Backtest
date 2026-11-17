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

    model_config = {"from_attributes": True}