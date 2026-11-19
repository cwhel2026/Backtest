"""E2E acceptance: incremental executor lifecycle (offline)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.video_strategies import Order, VideoConfig
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.live_lab.incremental_executor import ForwardExecutorState, IncrementalVideoForwardEngine


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _bars(n=8):
    t0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    out = []
    for i in range(n):
        base = Decimal(5000 + i)
        out.append(
            Bar(
                ts=t0 + timedelta(minutes=5 * i),
                open=base,
                high=base + Decimal("2"),
                low=base - Decimal("2"),
                close=base + Decimal("0.5"),
                volume=100,
            )
        )
    return out


def test_incremental_limit_amend_fill_stop_replay_identical():
    inst = _mes()
    spec = {"risk": {"dollar_risk_per_trade": 75, "max_contracts": 1}, "entry": {"type": "video_anchor_bos"}}
    cfg = VideoConfig.from_instrument(inst, spec)
    bars = _bars(12)
    order = Order(
        "test",
        "long",
        1,
        bars[2].low,
        bars[2].low - Decimal(4),
        bars[2].high + Decimal(8),
        8,
        "acceptance",
        amendments=[],
        setup_id="acc-1",
    )

    def run_pass():
        eng = IncrementalVideoForwardEngine(ForwardExecutorState(), cfg, inst)
        eng.submit_order(order, bars[:4])
        results = []
        for i in range(3, len(bars)):
            r = eng.on_bar(bars[: i + 1], i)
            results.append((eng.state.pending, eng.state.open_position, r.trade_closed))
        return results, eng.state

    r1, st1 = run_pass()
    eng2 = IncrementalVideoForwardEngine(ForwardExecutorState(), cfg, inst)
    eng2.submit_order(order, bars[:4])
    for i in range(3, 6):
        eng2.on_bar(bars[: i + 1], i)
    st_mid = eng2.state
    eng3 = IncrementalVideoForwardEngine(st_mid, cfg, inst)
    for i in range(6, len(bars)):
        eng3.on_bar(bars[: i + 1], i)
    r2, st2 = run_pass()
    assert st1.placed_setup_keys == st2.placed_setup_keys
    assert len(r1) == len(r2)


def test_no_lookahead_signal_index():
    bars = _bars(6)
    inst = _mes()
    cfg = VideoConfig.from_instrument(inst, {})
    order = Order("t", "long", 2, Decimal(5001), Decimal(4996), Decimal(5010), 5, "x")
    eng = IncrementalVideoForwardEngine(ForwardExecutorState(), cfg, inst)
    eng.submit_order(order, bars)
    eng.on_bar(bars[:3], 2)
    pending = eng.load_pending()
    assert pending
    assert pending[0]._next_eval_index >= 3  # noqa: SLF001