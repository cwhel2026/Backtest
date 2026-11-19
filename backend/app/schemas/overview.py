from pydantic import BaseModel

from app.schemas.market_data import ProviderHealthOut


class OverviewStats(BaseModel):
    instruments_count: int
    strategies_total: int
    strategies_validated: int
    strategies_paper: int
    strategies_rejected: int
    active_research_jobs: int
    queued_research_jobs: int
    datasets_count: int
    data_providers: list[ProviderHealthOut]
    ai_research_enabled: bool
    ai_configured: bool
    genuine_datasets_count: int = 0
    backtests_completed_count: int = 0