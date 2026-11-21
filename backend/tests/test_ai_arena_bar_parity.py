"""Bar DSL parity — deterministic, no API, no database."""

from decimal import Decimal
from datetime import UTC, datetime, timedelta

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.instrument import Instrument
from app.services.ai_arena.bar_parity import incremental_fills_on_bars


def _mes() -> Instrument:
    from app.models.enums import AssetClass

    return Instrument(
        symbol="MES",
        name="Micro E-mini S&P",
        asset_class=AssetClass.EQUITY_INDEX,
        trading_hours={},
        exchange="CME",
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        default_commission_per_side=Decimal("0.62"),
    )


def _bars(n: int = 80):
    t0 = datetime(2024, 6, 3, 14, 0, tzinfo=UTC)
    out = []
    px = Decimal("5300")
    for i in range(n):
        ts = t0 + timedelta(minutes=5 * i)
        o = px + Decimal(i % 3) * Decimal("0.25")
        out.append(Bar(ts, o, o + Decimal("2"), o - Decimal("2"), o + Decimal("0.5"), 1000))
    return out


def test_incremental_path_smoke_and_backtest_runs():
    """Deterministic smoke — full parity enforced at paper promotion on genuine datasets."""
    spec = {
        "name": "parity smoke",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": {"type": "ema_crossover", "fast_period": 8, "slow_period": 21},
        "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    bars = _bars(100)
    inst = _mes()
    bt = run_backtest(spec, bars, inst, "5m", BacktestAssumptions(slippage_ticks_per_side=1))
    inc_fills = incremental_fills_on_bars(spec, bars, inst, slip_ticks=1)
    assert bt.metrics is not None
    assert isinstance(inc_fills, list)


def test_alembic_arena_revision_chain():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    chain = {}
    for p in root.glob("01*_*.py"):
        text = p.read_text()
        rev = down = None
        for line in text.splitlines():
            if line.startswith("revision = "):
                rev = line.split("=", 1)[1].strip().strip('"')
            if line.startswith("down_revision = "):
                down = line.split("=", 1)[1].strip().strip('"')
        if rev:
            chain[rev] = down
    assert chain.get("013") == "012"
    assert chain.get("014") == "013"
    assert chain.get("015") == "014"
    assert chain.get("016") == "015"