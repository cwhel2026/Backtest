from pydantic import BaseModel


class ScannerSetupOut(BaseModel):
    id: str
    setup_id: str
    symbol: str
    contract: str | None
    strategy_key: str
    strategy_name: str
    strategy_version: str
    direction: str
    detected_at: str
    market_ts: str
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    risk_reward: float | None
    status: str
    explanation: str | None
    data_source: str | None
    feed_latency_mode: str | None
    forward_run_id: str | None
    diagnostics: dict


class ScannerSetupList(BaseModel):
    items: list[ScannerSetupOut]
    total: int
    limit: int
    offset: int