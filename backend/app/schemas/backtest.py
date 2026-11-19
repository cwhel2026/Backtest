from pydantic import BaseModel, Field

from app.schemas.market_data import OhlcvBarOut


class BacktestCreateRequest(BaseModel):
    strategy_id: str
    strategy_version_id: str | None = None
    dataset_id: str
    assumptions: dict = Field(default_factory=lambda: {"slippage_ticks_per_side": 1})
    parameters: dict = Field(default_factory=dict)


class BacktestRunSummary(BaseModel):
    id: str
    strategy_id: str
    dataset_id: str
    status: str
    performance_category: str
    reproducibility_id: str
    engine_version: str
    metrics: dict | None
    assumptions: dict | None = None
    warnings: list | None = None
    equity_curve: list | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None
    has_simulation_log: bool = False


class SimulationLogOut(BaseModel):
    decision_events: list[dict] = []
    rejected_setups: list[dict] = []
    simulation_provenance: dict = {}
    engine_version: str | None = None


class DebuggerBarOut(OhlcvBarOut):
    bar_index: int


class BacktestTradeOut(BaseModel):
    id: str
    trade_number: int
    direction: str
    quantity: int
    signal_ts: str
    entry_ts: str
    entry_price: float
    exit_ts: str
    exit_price: float
    stop_price: float | None = None
    target_price: float | None = None
    exit_reason: str
    gross_pnl: float
    commissions: float
    slippage: float
    net_pnl: float
    mae: float | None
    mfe: float | None
    meta: dict | None = None