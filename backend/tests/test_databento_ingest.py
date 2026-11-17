from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.services.market_data.databento_ingest import bars_for_timeframe, databento_continuous_symbol


def test_continuous_symbol_mapping():
    assert databento_continuous_symbol("mes") == "MES.c.0"
    assert databento_continuous_symbol(" NQ ") == "NQ.c.0"


def test_aggregate_five_minute_bars():
  ts0 = datetime(2024, 1, 2, 14, 0, tzinfo=UTC)
  bars_1m = [
      Bar(ts=ts0, open=Decimal("1"), high=Decimal("2"), low=Decimal("0.5"), close=Decimal("1.5"), volume=10),
      Bar(
          ts=datetime(2024, 1, 2, 14, 1, tzinfo=UTC),
          open=Decimal("1.5"),
          high=Decimal("3"),
          low=Decimal("1"),
          close=Decimal("2"),
          volume=5,
      ),
      Bar(
          ts=datetime(2024, 1, 2, 14, 5, tzinfo=UTC),
          open=Decimal("2"),
          high=Decimal("2.5"),
          low=Decimal("1.8"),
          close=Decimal("2.2"),
          volume=7,
      ),
  ]
  out = bars_for_timeframe(bars_1m, "5m")
  assert len(out) == 2
  assert out[0][0] == ts0
  assert out[0][2] == Decimal("3")
  assert out[0][5] == 15