from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.video_strategies import Order, OrderAmendment, VideoConfig
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.live_lab.incremental_executor import ForwardExecutorState, IncrementalVideoForwardEngine


def _mes():
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


def test_pending_amendment_and_fill():
    bars = []
    t = datetime(2024, 1, 1, 15, 0, tzinfo=UTC)
    for i in range(8):
        bars.append(
            Bar(t + timedelta(minutes=5 * i), Decimal(100), Decimal(101), Decimal(99), Decimal(100), 50)
        )
    bars[3] = Bar(bars[3].ts, Decimal(100), Decimal(101), Decimal(98.5), Decimal(99), 50)
    cfg = VideoConfig.from_instrument(_mes(), {})
    order = Order(
        "video_test",
        "long",
        1,
        Decimal(100),
        Decimal(98),
        Decimal(104),
        6,
        "unit",
        amendments=[OrderAmendment(3, Decimal(99.5), Decimal(98), Decimal(104))],
    )
    eng = IncrementalVideoForwardEngine(ForwardExecutorState(), cfg, _mes())
    eng.submit_order(order, bars)
    for i in range(2, 7):
        eng.on_bar(bars[: i + 1], i)
    assert eng.state.open_position is not None or eng.state.pending == []