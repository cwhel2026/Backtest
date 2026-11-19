"""Live Strategy Lab — replay determinism, no-lookahead, candles (unit-level)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from app.backtest.bars import Bar
from app.models.enums import AssetClass, PaperOrderState
from app.models.instrument import Instrument
from app.services.live_lab.market_data.replay import ReplayMarketDataAdapter
from app.services.live_lab.paper_broker import PaperBroker
from app.services.live_lab.promotion import evaluate_historical_validation
from app.services.live_lab.streaming_no_lookahead import assert_decision_not_before_bar_close
from app.services.market_data.streaming_aggregate import StreamingAggregator, floor_bucket_ts


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


class _Order:
    order_type = "limit"
    side = "buy"
    limit_price = Decimal("99.5")
    quantity = 1
    client_order_id = "x"
    state = PaperOrderState.ACKNOWLEDGED
    filled_qty = 0
    avg_fill_price = None
    uncertainty_tags: list = []


def test_candle_5m_boundary_from_1m_bars():
    t0 = datetime(2024, 6, 3, 14, 0, tzinfo=UTC)
    agg = StreamingAggregator("5m")
    closed = []
    for m in range(5):
        bar = Bar(
            ts=t0 + timedelta(minutes=m),
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100 + m * 0.1),
            volume=10,
        )
        closed.extend(agg.ingest_1m(bar))
    closed.extend(agg.flush())
    assert len(closed) == 1
    assert closed[0].volume == 50
    assert closed[0].ts == floor_bucket_ts(t0, 5)


def test_replay_deterministic_events():
    t0 = datetime(2024, 1, 2, 15, 0, tzinfo=UTC)
    bars = []
    for i in range(10):
        ts = t0 + timedelta(minutes=5 * i)
        bars.append((ts, Decimal(100), Decimal(101), Decimal(99), Decimal(100 + i * 0.05), 20))
    events = ReplayMarketDataAdapter.bars_to_trade_events("MES", bars)
    adapter = ReplayMarketDataAdapter(events)
    adapter.connect()
    batch1 = adapter.poll_events(1000)
    adapter.reset()
    adapter.connect()
    batch2 = adapter.poll_events(1000)
    assert len(batch1) == len(batch2)
    assert [e.idempotency_key for e in batch1] == [e.idempotency_key for e in batch2]


def test_no_lookahead_decision_ts():
    bar_close = datetime(2024, 1, 1, 14, 5, tzinfo=UTC)
    decision = datetime(2024, 1, 1, 14, 5, 1, tzinfo=UTC)
    assert_decision_not_before_bar_close(bar_close, decision)
    with pytest.raises(AssertionError):
        assert_decision_not_before_bar_close(bar_close, bar_close - timedelta(seconds=1))


def test_paper_broker_limit_touch_tags():
    broker = PaperBroker(MagicMock(), uuid4(), _mes())
    bar = Bar(
        ts=datetime(2024, 1, 1, 15, 0, tzinfo=UTC),
        open=Decimal(100),
        high=Decimal(100.5),
        low=Decimal(99.4),
        close=Decimal(100.25),
        volume=100,
    )
    o = _Order()
    result = broker._try_fill(o, bar, Decimal("0.25"), datetime.now(UTC))  # noqa: SLF001
    assert result is not None
    assert result.uncertainty_tags


def test_promotion_requires_strategy():
    session = MagicMock()
    session.get.return_value = None
    ok, reasons, _ = evaluate_historical_validation(session, uuid4())
    assert not ok
    assert reasons