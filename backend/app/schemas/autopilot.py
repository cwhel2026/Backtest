from pydantic import BaseModel, Field


class LeaderboardEntry(BaseModel):
    run_id: str
    strategy_id: str
    strategy_name: str
    symbol: str
    category: str
    timeframe: str
    entry_type: str | None = None
    completed_at: str | None = None
    prop_ready_score: int
    passes_prop_screen: bool
    metrics: dict
    rank_score: float = 0


class CycleStats(BaseModel):
    tests_run: int = 0
    profitable_count: int = 0
    last_cycle_detail: str | None = None


class AutopilotStatus(BaseModel):
    hourly_enabled: bool
    ai_configured: bool
    message: str
    profitable_candidates: list[LeaderboardEntry] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    cycle_stats: CycleStats = Field(default_factory=CycleStats)


class AutopilotRunResponse(BaseModel):
    job_id: str | None
    status: str
    mode: str