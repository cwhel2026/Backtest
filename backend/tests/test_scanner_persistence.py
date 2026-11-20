"""Scanner setup ID and risk/reward helpers."""

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.video_strategies import Order
from app.services.scanner.persistence import deterministic_setup_id, _risk_reward


def test_deterministic_setup_id_stable():
    a = deterministic_setup_id("berg", "MNQ", "sig1", "10")
    b = deterministic_setup_id("berg", "MNQ", "sig1", "10")
    assert a == b
    assert len(a) == 48


def test_risk_reward_long():
    rr = _risk_reward(Decimal("100"), Decimal("90"), Decimal("120"))
    assert rr is not None
    assert float(rr) == 2.0


def test_order_direction_buy_label():
    order = Order(
        strategy="liquidity",
        direction="long",
        signal_index=5,
        limit=Decimal("100"),
        stop=Decimal("90"),
        target=Decimal("120"),
        expiry_index=20,
        reason="sweep reclaim",
        setup_id="sweep-abc",
    )
    assert order.direction == "long"