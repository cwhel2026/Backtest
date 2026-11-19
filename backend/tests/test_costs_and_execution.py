from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.costs import apply_slippage, informational_slippage, settle_trade
from app.backtest.execution import OrderType, SimulatedOrder, limit_touched, process_order_bar
from app.backtest.exits import check_intrabar_exit
from app.models.enums import AssetClass
from app.models.instrument import Instrument


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


def test_slippage_not_subtracted_twice():
    tick = Decimal("0.25")
    ref_entry = Decimal("100")
    ref_exit = Decimal("101")
    exec_entry = apply_slippage(ref_entry, "long", "entry", tick, 1)
    exec_exit = apply_slippage(ref_exit, "long", "exit", tick, 1)
    settlement = settle_trade(
        direction="long",
        qty=1,
        instrument=_mes(),
        ref_entry=ref_entry,
        exec_entry=exec_entry,
        ref_exit=ref_exit,
        exec_exit=exec_exit,
        commission_per_side=Decimal("0.62"),
    )
    slip = informational_slippage(ref_entry, exec_entry, ref_exit, exec_exit, "long", 1, Decimal("5"))
    assert settlement.slippage == slip
    assert settlement.net_pnl == settlement.gross_pnl - settlement.commissions
    assert settlement.gross_pnl == Decimal("5") * (exec_exit - exec_entry)


def test_limit_fill_requires_touch():
    bar = Bar(
        ts=datetime(2024, 1, 1, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("100.5"),
        low=Decimal("99"),
        close=Decimal("99.5"),
        volume=10,
    )
    assert limit_touched("long", Decimal("99"), bar)
    assert not limit_touched("long", Decimal("98.5"), bar)


def test_limit_order_fill_event():
    bar = Bar(
        ts=datetime(2024, 1, 2, tzinfo=UTC),
        open=Decimal("99"),
        high=Decimal("100"),
        low=Decimal("98.5"),
        close=Decimal("99.5"),
        volume=10,
    )
    order = SimulatedOrder(
        1,
        "long",
        OrderType.LIMIT,
        Decimal("98.75"),
        1,
        bar.ts,
        None,
        Decimal("97"),
        Decimal("101"),
        "test",
    )
    px = process_order_bar(order, bar, Decimal("0.25"))
    assert px == Decimal("98.75")


def test_stop_before_target_same_bar():
    bar = Bar(
        ts=datetime(2024, 1, 3, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("99"),
        volume=10,
    )
    hit, reason = check_intrabar_exit("long", Decimal("98.5"), Decimal("101"), bar)
    assert reason == "stop_loss"
    assert hit == Decimal("98.5")


def test_gap_through_stop_long():
    bar = Bar(
        ts=datetime(2024, 1, 4, tzinfo=UTC),
        open=Decimal("97"),
        high=Decimal("98"),
        low=Decimal("96.5"),
        close=Decimal("97.5"),
        volume=10,
    )
    hit, reason = check_intrabar_exit("long", Decimal("98.5"), Decimal("103"), bar)
    assert reason == "stop_loss_gap"
    assert hit == Decimal("97")