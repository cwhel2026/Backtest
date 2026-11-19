from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.backtest.indicators import atr_series
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.strategy_search_space import FAMILY_BUILDERS, all_search_specs


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="Micro E-mini S&P 500",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _synthetic_rth_bars() -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("5200")
    for i in range(80):
        ts = start + timedelta(minutes=5 * i)
        drift = Decimal(str(i * 0.1))
        o = price + drift
        c = o + Decimal("0.5")
        bars.append(
            Bar(
                ts=ts,
                open=o,
                high=c + Decimal("1"),
                low=o - Decimal("0.5"),
                close=c,
                volume=1000 + i,
            )
        )
    return bars


def _streak_spec(**extra):
    spec = {
        "name": "test streak",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "consecutive_closes",
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": {"type": "consecutive_closes", "count": 3},
        "exit": {"stop_ticks": 40, "target_ticks": 40, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    spec.update(extra)
    return spec


def test_session_window_filter_can_block_all_entries():
    bars = _synthetic_rth_bars()
    open_book = run_backtest(_streak_spec(), bars, _mes(), "5m", BacktestAssumptions())
    blocked = run_backtest(
        _streak_spec(filters={"start_hhmm": "16:00", "end_hhmm": "16:05"}),
        bars,
        _mes(),
        "5m",
        BacktestAssumptions(),
    )
    assert open_book.metrics["trade_count"] >= 1
    assert blocked.metrics["trade_count"] == 0


def test_time_stop_exits_after_max_bars():
    spec = _streak_spec()
    spec["risk"] = {"dollar_risk_per_trade": 500, "max_contracts": 1}
    spec["exit"] = {
        "stop_ticks": 40,
        "target_ticks": 40,
        "max_bars": 1,
        "session_end_flatten": True,
    }
    result = run_backtest(spec, _synthetic_rth_bars(), _mes(), "5m", BacktestAssumptions())
    assert result.trades
    assert any(t["exit_reason"] == "time_stop" for t in result.trades)


def test_atr_series_is_causal_and_positive():
    bars = _synthetic_rth_bars()
    atr = atr_series(bars, 14)
    assert all(v is None or v > 0 for v in atr)
    assert atr[12] is None
    assert atr[13] is not None


def test_confluence_families_are_in_search_space():
    assert {"orb_vwap", "killzone_fvg", "atr_pullback", "sweep_discount"} <= set(FAMILY_BUILDERS)
    types_or_cats = {(s["entry"]["type"], s.get("category")) for s in all_search_specs("MNQ")}
    assert any(cat == "orb_vwap" for _, cat in types_or_cats)
    specs = [s for s in all_search_specs("MNQ") if s.get("category") == "atr_pullback"]
    assert specs
    assert specs[0]["exit"].get("stop_atr")
    assert specs[0]["filters"].get("vwap_align") == "with"
