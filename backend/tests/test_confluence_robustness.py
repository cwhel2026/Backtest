from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import validate_spec
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.backtest.robustness import evaluate_robustness, group_session_bars, shuffle_session_order
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


def _synthetic_rth_bars(days: int = 1, bars_per_day: int = 80) -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("5200")
    n = 0
    for day in range(days):
        day_start = start + timedelta(days=day)
        for j in range(bars_per_day):
            ts = day_start + timedelta(minutes=5 * j)
            drift = Decimal(str(n * 0.1))
            o = price + drift
            c = o + Decimal("0.5")
            bars.append(
                Bar(ts=ts, open=o, high=c + Decimal("1"), low=o - Decimal("0.5"), close=c, volume=1000 + n)
            )
            n += 1
    return bars


def _streak_confluence(second: dict, **extra) -> dict:
    spec = {
        "name": "conf test",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "confluence",
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": {
            "type": "confluence",
            "window_bars": 1,
            "all": [
                {"type": "consecutive_closes", "count": 3},
                second,
            ],
        },
        "exit": {"stop_ticks": 40, "target_ticks": 40, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    spec.update(extra)
    return spec


def test_confluence_spec_validates():
    spec = _streak_confluence({"type": "consecutive_closes", "count": 2})
    assert validate_spec(spec) == []
    bad = _streak_confluence({"type": "confluence", "all": []})
    assert validate_spec(bad)


def test_confluence_requires_both_legs():
    bars = _synthetic_rth_bars()
    aligned = run_backtest(
        _streak_confluence({"type": "consecutive_closes", "count": 2}),
        bars,
        _mes(),
        "5m",
        BacktestAssumptions(),
    )
    blocked = run_backtest(
        _streak_confluence({"type": "rsi_reversion", "period": 5, "oversold": 5, "overbought": 10}),
        bars,
        _mes(),
        "5m",
        BacktestAssumptions(),
    )
    assert aligned.metrics["trade_count"] >= 1
    assert blocked.metrics["trade_count"] == 0


def test_session_shuffle_preserves_bar_count():
    bars = _synthetic_rth_bars(days=6)
    groups = group_session_bars(bars)
    assert len(groups) == 6
    shuffled = shuffle_session_order(bars, seed=3)
    assert len(shuffled) == len(bars)
    assert {b.ts for b in shuffled} == {b.ts for b in bars}


def test_robustness_report_structure():
    bars = _synthetic_rth_bars(days=5)
    spec = _streak_confluence({"type": "consecutive_closes", "count": 2})
    report = evaluate_robustness(spec, bars, _mes(), "5m", n_shuffles=3, slip_ticks=2, min_pass=0.5, seed=1)
    assert "passed" in report
    assert report["backtests"] >= 1
    assert "mc_pass_rate" in report["metrics"]


def test_search_includes_confluence_families():
    assert {"sweep_fvg", "sweep_ob", "orb_pull"} <= set(FAMILY_BUILDERS)
    conf = [s for s in all_search_specs("MNQ") if s["entry"]["type"] == "confluence"]
    assert conf
    assert all(validate_spec(s) == [] for s in conf[:5])
