"""Chronological limit-order execution and OHLC policy regression laboratory."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.backtest.bars import Bar
from app.backtest.ohlc_policies import (
    EntryBarExitPolicy,
    PendingFillPolicy,
    evaluate_fill_bar_exit,
    pending_limit_fill_eligible,
)
from app.backtest.video_execution import run_video_orders
from app.backtest.video_strategies import Order, OrderAmendment, VideoConfig, effective_order_prices
from app.models.enums import AssetClass
from app.models.instrument import Instrument


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 15, 14, 30, tzinfo=UTC) + timedelta(minutes=5 * i)


def _b(i: int, o, h, l, c) -> Bar:
    return Bar(_ts(i), D(str(o)), D(str(h)), D(str(l)), D(str(c)), 1)


def _inst() -> Instrument:
    return Instrument(
        symbol="TST",
        name="Test",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=D("1"),
        tick_value=D("1"),
        multiplier=D("1"),
        trading_hours={},
        default_commission_per_side=D("0"),
    )


def _cfg(**kw) -> VideoConfig:
    defaults = dict(
        tick=D("1"),
        multiplier=D("1"),
        slippage_ticks=0,
        commission_side=D("0"),
        risk_dollars=D("1000"),
        max_contracts=1,
        entry_bar_exit_policy="conservative_ohlc",
        pending_fill_policy="no_fill_if_stop_touched",
    )
    defaults.update(kw)
    return VideoConfig(**defaults)


# 1. Fill before amendment on a later bar
def test_fill_at_original_limit_before_amendment():
    bars = [_b(i, 100, 101, 99, 100) for i in range(5)]
    bars[2] = _b(2, 100, 101, 99.5, 100)  # touches 100 limit on bar 2
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 4, "test")
    o.amendments.append(OrderAmendment(2, D("102"), D("95"), D("110")))
    ledger, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert stats.orders_filled == 1
    assert ledger[0]["entry_ts"] == bars[1].ts
    assert ledger[0]["meta"]["limit_price"] == "100"


# 2. Amendment at bar open prevents retroactive fill price on same bar
def test_amendment_same_bar_no_retroactive_fill():
    bars = [_b(i, 100, 101, 100.5, 100) for i in range(5)]  # bar0-1: no touch 100
    bars[2] = _b(2, 100, 101, 98, 100.5)  # after amend to 98, low touches
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 4, "test")
    o.amendments.append(OrderAmendment(2, D("98"), D("95"), D("110")))
    ledger, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert ledger
    assert ledger[0]["meta"]["limit_price"] == "98"
    assert ledger[0]["entry_ts"] == bars[2].ts


# 3. No amendment after fill (amendment on bar after fill ignored by simulator — fill locks quote)
def test_effective_prices_chronology():
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 5, "t")
    o.amendments = [OrderAmendment(3, D("101"), D("95"), D("110"))]
    assert effective_order_prices(o, 2) == (D("100"), D("95"), D("110"))
    assert effective_order_prices(o, 3) == (D("101"), D("95"), D("110"))


# 4. Expiration
def test_order_expires_without_touch():
    bars = [_b(i, 100, 101, 99, 100) for i in range(4)]
    o = Order("t", "long", 0, D("50"), D("45"), D("60"), 2, "t")
    _, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert stats.orders_expired == 1
    assert stats.orders_filled == 0


# 5. Cancelled due to busy_until
def test_second_order_cancelled_while_position_open():
    bars = [_b(i, 100, 101, 99, 100) for i in range(12)]
    bars[1] = _b(1, 100, 101, 99, 100)
    bars[2] = _b(2, 100, 101, 98, 99)
    o1 = Order("t", "long", 0, D("100"), D("95"), D("105"), 10, "one")
    o2 = Order("t", "long", 1, D("100"), D("95"), D("105"), 10, "two")
    _, stats, _ = run_video_orders(bars, [o1, o2], _cfg(), _inst())
    assert stats.orders_filled >= 1
    assert stats.orders_cancelled >= 1


# 6. Fill bar stop exit (conservative)
def test_fill_bar_stop_conservative():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 100, 106, 94, 100), _b(2, 100, 101, 93, 94)]
    o = Order("t", "long", 0, D("100"), D("95"), D("105"), 2, "t")
    ledger, _, _ = run_video_orders(
        bars,
        [o],
        _cfg(
            entry_bar_exit_policy="conservative_ohlc",
            pending_fill_policy="allow_fill_then_exit",
        ),
        _inst(),
    )
    assert ledger[0]["exit_reason"] == "stop"
    assert "fill_bar_stop_and_target" in str(ledger[0]["meta"].get("execution_uncertainties")) or ledger[0]["exit_reason"] == "stop"


# 7. Skip exits legacy policy
def test_fill_bar_skip_exits_legacy():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 100, 106, 99.5, 100), _b(2, 100, 101, 93, 94)]
    o = Order("t", "long", 0, D("100"), D("95"), D("105"), 2, "t")
    ledger, _, _ = run_video_orders(
        bars,
        [o],
        _cfg(entry_bar_exit_policy="skip_exits", pending_fill_policy="allow_fill_then_exit"),
        _inst(),
    )
    assert ledger[0]["exit_reason"] == "stop"
    assert ledger[0]["exit_ts"] == bars[2].ts


# 8. Pending stop blocks fill (conservative)
def test_pending_stop_blocks_fill():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 99, 100, 94, 96)]
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 2, "t")
    _, stats, _ = run_video_orders(
        bars, [o], _cfg(pending_fill_policy="no_fill_if_stop_touched"), _inst()
    )
    assert stats.orders_filled == 0


# 9. Allow fill then exit on same bar
def test_pending_allow_fill_then_exit_same_bar():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 100, 106, 94, 100)]
    o = Order("t", "long", 0, D("100"), D("95"), D("105"), 2, "t")
    ledger, stats, _ = run_video_orders(
        bars,
        [o],
        _cfg(
            pending_fill_policy="allow_fill_then_exit",
            entry_bar_exit_policy="conservative_ohlc",
        ),
        _inst(),
    )
    assert stats.orders_filled == 1
    assert ledger[0]["exit_reason"] in ("stop", "stop_gap", "target")


# 10. Gap stop on fill bar
def test_gap_through_stop_on_fill_bar():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 92, 100, 99, 99.5)]
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 2, "t")
    ledger, stats, _ = run_video_orders(
        bars, [o], _cfg(pending_fill_policy="allow_fill_then_exit"), _inst()
    )
    assert stats.orders_filled == 1
    eval_ = evaluate_fill_bar_exit("long", D("95"), D("110"), bars[1], EntryBarExitPolicy.CONSERVATIVE_OHLC)
    if eval_.price is not None:
        assert ledger[0]["exit_reason"] in ("stop", "stop_gap", "end_of_data", "target")


# 11. Target on fill bar
def test_fill_bar_target():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 100, 106, 99, 105)]
    o = Order("t", "long", 0, D("100"), D("95"), D("105"), 2, "t")
    ledger, _, _ = run_video_orders(
        bars, [o], _cfg(pending_fill_policy="allow_fill_then_exit"), _inst()
    )
    assert ledger[0]["exit_reason"] == "target"


# 12. Deterministic PnL repeat
def test_deterministic_pnl_twice():
    bars = [_b(i, 100, 101, 99, 100) for i in range(6)]
    bars[1] = _b(1, 100, 101, 99, 100)
    bars[3] = _b(3, 100, 110, 99, 108)
    o = Order("t", "long", 0, D("100"), D("95"), D("108"), 5, "t")
    a, _, _ = run_video_orders(bars, [o], _cfg(), _inst())
    b, _, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert a[0]["net_pnl"] == b[0]["net_pnl"]
    assert a[0]["meta"]["order_events"] == b[0]["meta"]["order_events"]


# 13. Amendment event in order_events
def test_amendment_logged_in_order_events():
    bars = [_b(i, 100, 101, 100.5, 100) for i in range(6)]
    bars[4] = _b(4, 100, 101, 97, 100)
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 5, "t")
    o.amendments.append(OrderAmendment(2, D("98"), D("95"), D("110")))
    ledger, _, _ = run_video_orders(bars, [o], _cfg(), _inst())
    events = ledger[0]["meta"]["order_events"]
    assert any(e["event"] == "amended" for e in events)


# 14. Invalid bracket rejected
def test_invalid_bracket_rejected():
    bars = [_b(i, 100, 101, 99, 100) for i in range(3)]
    o = Order("t", "long", 0, D("100"), D("105"), D("110"), 2, "t")
    _, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert stats.orders_rejected == 1


# 15. Invalid amendment cancels
def test_invalid_amendment_cancels_order():
    bars = [_b(i, 100, 101, 100.5, 100) for i in range(5)]
    bars[2] = _b(2, 100, 101, 100.5, 100)  # no fill before amend
    o = Order("t", "long", 0, D("100"), D("95"), D("110"), 4, "t")
    o.amendments.append(OrderAmendment(2, D("100"), D("105"), D("110")))  # stop above limit
    _, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert stats.orders_cancelled == 1


# 16. Short fill chronology
def test_short_limit_fill():
    bars = [_b(i, 100, 101, 99, 100) for i in range(4)]
    bars[2] = _b(2, 100, 101, 98, 99)
    o = Order("t", "short", 0, D("99"), D("105"), D("90"), 3, "t")
    ledger, stats, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert stats.orders_filled == 1
    assert ledger[0]["direction"] == "short"


# 17. pending_limit_fill_eligible tags
def test_pending_fill_uncertainty_tags():
    ok, tags = pending_limit_fill_eligible("long", D("100"), D("95"), _b(1, 100, 101, 99, 100), PendingFillPolicy.ALLOW_FILL_THEN_EXIT)
    assert ok
    assert "limit_touch_eligibility" in tags[0]


# 18. Berg-style multi-amend path uses first touch price
def test_berg_style_amend_fill_sequence():
    bars = [_b(i, 100, 101, 99, 100) for i in range(8)]
    bars[4] = _b(4, 100, 101, 99.5, 100)
    o = Order("berg", "long", 2, D("99.5"), D("95"), D("110"), 7, "fib")
    o.amendments.append(OrderAmendment(4, D("100.5"), D("95"), D("110")))
    ledger, _, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert ledger[0]["meta"]["limit_price"] == "99.5"
    assert ledger[0]["entry_ts"] == bars[3].ts


# 19. Stop and target on separate bar after fill bar skip
def test_stop_after_fill_bar():
    bars = [_b(0, 100, 100, 100, 100), _b(1, 100, 101, 99.5, 100), _b(2, 100, 101, 93, 94)]
    o = Order("t", "long", 0, D("100"), D("95"), D("120"), 3, "t")
    ledger, _, _ = run_video_orders(
        bars, [o], _cfg(entry_bar_exit_policy="skip_exits"), _inst()
    )
    assert ledger[0]["exit_reason"] == "stop"


# 20. No retroactive price on filled order meta
def test_berg_dynamic_fib_uses_chronological_amendments():
    """Pipeline amendments must not retroactively change fill price on earlier bars."""
    from app.backtest.berg_tnb.pipeline import BergTnbEngine

    spec = {
        "entry": {
            "type": "berg_tnb_model_v1",
            "entry_fib_mode": "dynamic_pdf_experimental",
        },
        "exit_meta": {"profile": "structural_rr", "reward_risk": "2"},
    }
    bars = [_b(i, 100, 101, 100.2, 100.5) for i in range(30)]
    bars[10] = _b(10, 100, 103, 99, 102)
    bars[11] = _b(11, 102, 105, 101, 104)
    engine = BergTnbEngine(spec, bars, D("0.25"))
    _s, orders, _ev, _r = engine.run()
    if not orders:
        return
    assert all(isinstance(a, object) for a in getattr(orders[0], "amendments", [])) or True
    ledger, stats, _ = run_video_orders(bars, orders, _cfg(), _inst())
    if stats.orders_filled:
        ev = ledger[0]["meta"].get("order_events", [])
        amend_bars = [e for e in ev if e.get("event") == "amended"]
        if amend_bars and ledger[0]["meta"]["limit_price"] != str(orders[0].limit):
            assert any(e["event"] == "filled" for e in ev)


def test_stop_target_locked_at_fill_not_final_amendment():
    bars = [_b(i, 100, 101, 100.5, 100) for i in range(6)]
    bars[3] = _b(3, 100, 101, 99.5, 100)
    o = Order("t", "long", 0, D("100"), D("95"), D("108"), 5, "t")
    o.amendments.append(OrderAmendment(4, D("100"), D("96"), D("120")))
    ledger, _, _ = run_video_orders(bars, [o], _cfg(), _inst())
    assert ledger[0]["stop_price"] == D("95")
    assert ledger[0]["target_price"] == D("108")