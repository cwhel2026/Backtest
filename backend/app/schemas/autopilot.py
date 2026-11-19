from pydantic import BaseModel, Field


class LeaderboardEntry(BaseModel):
    run_id: str
    strategy_id: str
    strategy_name: str
    symbol: str
    category: str
    timeframe: str
    entry_type: str | None = None
    origin: str = "deep"
    completed_at: str | None = None
    tested_at: str | None = None
    prop_ready_score: int
    passes_prop_screen: bool
    grade: str = "miss"
    gate_miss: str | None = None
    metrics: dict
    sample: dict | None = None
    data: dict | None = None
    risk: dict | None = None
    tests: dict | None = None
    rank_score: float = 0


class CycleStats(BaseModel):
    tests_run: int = 0
    profitable_count: int = 0
    last_cycle_detail: str | None = None


class SearchPlan(BaseModel):
    """What the desk search tries on each cycle."""

    symbols: list[str] = Field(default_factory=list)
    combos_per_symbol: int = 0
    history_days: int = 0
    families: list[str] = Field(default_factory=list)
    walk_forward: str = "holdout 20% · train · multi-fold OOS · research screen · expectancy CI"
    reverse_fades: bool = True


class SearchLiveProgress(BaseModel):
    phase: str | None = None
    symbols: list[str] = Field(default_factory=list)
    symbol_index: int = 0
    current_symbol: str | None = None
    budget_per_symbol: int = 0
    history_days: int = 0
    combos_per_symbol: int = 0
    combos_completed: int = 0
    tests_completed: int = 0
    tests_target_estimate: int = 0
    current_setup: str | None = None
    setup_family: str | None = None
    scoring_subphase: str | None = None
    search_families: list[str] = Field(default_factory=list)
    walk_forward: str | None = None
    markets_loaded: list[str] = Field(default_factory=list)
    winners_saved: int = 0
    symbols_finished: list[str] = Field(default_factory=list)
    heartbeat_at: str | None = None
    experiments_recorded: int = 0
    ai_round: int = 0
    ai_specs_proposed: int = 0


class JobLogLine(BaseModel):
    headline: str
    detail: str
    created_at: str


class BackgroundSearchStatus(BaseModel):
    job_id: str
    status: str
    message: str
    progress_pct: int = 0
    started_at: str | None = None
    error: str | None = None
    live: SearchLiveProgress | None = None
    job_log: list[JobLogLine] = Field(default_factory=list)


class AutopilotStatus(BaseModel):
    hourly_enabled: bool
    ai_configured: bool
    search_symbols: list[str] = Field(default_factory=list)
    search_plan: SearchPlan | None = None
    background_search: BackgroundSearchStatus | None = None
    message: str
    profitable_candidates: list[LeaderboardEntry] = Field(default_factory=list)
    recent_tests: list[LeaderboardEntry] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    cycle_stats: CycleStats = Field(default_factory=CycleStats)


class AutopilotRunResponse(BaseModel):
    job_id: str | None
    status: str
    mode: str