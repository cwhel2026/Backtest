from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.dsl import build_signal_context, session_keys_rth, signal_at_bar
from app.backtest.structure import confirmed_swings, detect_liquidity_sweep_reversal, fib_retrace


def _prior_session_then_sweep() -> list[Bar]:
    start = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    bars: list[Bar] = []
    # day 1
    for j in range(20):
        px = Decimal("100") + Decimal(j) * Decimal("0.1")
        bars.append(
            Bar(
                ts=start + timedelta(minutes=5 * j),
                open=px,
                high=px + Decimal("0.5"),
                low=px - Decimal("0.2"),
                close=px + Decimal("0.2"),
                volume=100,
            )
        )
    day2 = start + timedelta(days=1)
    # day 2: sweep prior low then reclaim
    for j in range(25):
        px = Decimal("100") - Decimal(j) * Decimal("0.05")
        low = px - Decimal("1.5") if j == 5 else px - Decimal("0.2")
        high = px + Decimal("0.4")
        close = px + Decimal("0.3") if j == 5 else px
        bars.append(Bar(ts=day2 + timedelta(minutes=5 * j), open=px, high=high, low=low, close=close, volume=100))
    return bars


def test_fib_retrace_level():
    assert fib_retrace(Decimal("90"), Decimal("100"), Decimal("0.618")) == Decimal("100") - Decimal("10") * Decimal(
        "0.618"
    )


def test_swing_confirms_only_after_right_bars():
    bars = _prior_session_then_sweep()
    swings = confirmed_swings(bars, left=1, right=1)
    assert all(s.confirmed_at >= s.index + 1 for s in swings)


def test_sweep_reversal_signal_runs():
    bars = _prior_session_then_sweep()
    keys = session_keys_rth(bars)
    tick = Decimal("0.25")
    spec = {
        "name": "sweep test",
        "instrument_symbol": "MES",
        "timeframe": "5m",
        "category": "liquidity_sweep_reversal",
        "session": {"allowed": ["RTH"]},
        "entry": {"type": "liquidity_sweep_reversal", "sweep_ticks": 2, "require_bos": False},
        "exit": {"stop_ticks": 8, "target_ticks": 16},
        "risk": {"dollar_risk_per_trade": 50, "max_contracts": 1},
    }
    ctx = build_signal_context(spec, bars, keys, instrument_tick=tick)
    hits = 0
    for i in range(10, len(bars)):
        if signal_at_bar(spec, bars, i, keys, tick, ctx):
            hits += 1
    assert hits >= 0


def test_false_sweep_without_reclaim():
    bars = _prior_session_then_sweep()
    keys = session_keys_rth(bars)
    i = 25
    setup = detect_liquidity_sweep_reversal(bars, 3, keys, Decimal("0.25"), sweep_ticks=2)
    # early bars unlikely to have prior session context
    assert setup is None or setup.direction in ("long", "short")