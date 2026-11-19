"""Memory-bounded OHLCV aggregation with carry across chunk/day boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar, TIMEFRAME_MINUTES


def floor_bucket_ts(ts: datetime, minutes: int) -> datetime:
    ts = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    epoch = int(ts.timestamp())
    floored = epoch - (epoch % (minutes * 60))
    return datetime.fromtimestamp(floored, tz=UTC)


class StreamingAggregator:
    """Ingest sorted 1m bars; emit completed higher-timeframe bars."""

    def __init__(self, target_tf: str):
        if target_tf not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported timeframe {target_tf}")
        self.target_tf = target_tf
        self.minutes = TIMEFRAME_MINUTES[target_tf]
        self._bucket_key: datetime | None = None
        self._bucket: list[Bar] = []

    def ingest_1m(self, bar: Bar) -> list[Bar]:
        key = floor_bucket_ts(bar.ts, self.minutes)
        out: list[Bar] = []
        if self._bucket_key is not None and key != self._bucket_key:
            out.append(self._finalize_bucket())
        self._bucket_key = key
        self._bucket.append(bar)
        return out

    def _finalize_bucket(self) -> Bar:
        chunk = self._bucket
        self._bucket = []
        ts_key = self._bucket_key
        self._bucket_key = None
        return Bar(
            ts=ts_key or floor_bucket_ts(chunk[0].ts, self.minutes),
            open=chunk[0].open,
            high=max(b.high for b in chunk),
            low=min(b.low for b in chunk),
            close=chunk[-1].close,
            volume=sum(b.volume for b in chunk),
        )

    def flush(self) -> list[Bar]:
        if not self._bucket:
            return []
        return [self._finalize_bucket()]