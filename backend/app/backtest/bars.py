from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest import OhlcvBar
from app.services.market_data.ohlcv_parquet import has_store, read_bars as read_parquet_bars

TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def load_bars(session: Session, dataset_id, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
    if has_store(dataset_id):
        return [
            Bar(ts=ts, open=o, high=h, low=low, close=c, volume=v)
            for ts, o, h, low, c, v in read_parquet_bars(dataset_id, start=start, end=end)
        ]
    q = select(OhlcvBar).where(OhlcvBar.dataset_id == dataset_id).order_by(OhlcvBar.ts)
    if start:
        q = q.where(OhlcvBar.ts >= start)
    if end:
        q = q.where(OhlcvBar.ts <= end)
    rows = session.execute(q).scalars().all()
    return [
        Bar(
            ts=r.ts,
            open=Decimal(r.open),
            high=Decimal(r.high),
            low=Decimal(r.low),
            close=Decimal(r.close),
            volume=int(r.volume),
        )
        for r in rows
    ]


def aggregate_bars(bars: list[Bar], target_tf: str) -> list[Bar]:
    """Aggregate 1m (or finer) bars into target timeframe."""
    if not bars:
        return []
    mins = TIMEFRAME_MINUTES.get(target_tf)
    if not mins:
        raise ValueError(f"Unsupported timeframe {target_tf}")

    bucket: dict[datetime, list[Bar]] = {}
    for b in bars:
        # Floor to UTC bucket (dataset should already be UTC)
        epoch = int(b.ts.timestamp())
        floored = epoch - (epoch % (mins * 60))
        key = datetime.fromtimestamp(floored, tz=b.ts.tzinfo)
        bucket.setdefault(key, []).append(b)

    out: list[Bar] = []
    for ts in sorted(bucket):
        chunk = bucket[ts]
        out.append(
            Bar(
                ts=ts,
                open=chunk[0].open,
                high=max(x.high for x in chunk),
                low=min(x.low for x in chunk),
                close=chunk[-1].close,
                volume=sum(x.volume for x in chunk),
            )
        )
    return out


def resample_if_needed(bars: list[Bar], dataset_tf: str, strategy_tf: str) -> list[Bar]:
    if dataset_tf == strategy_tf:
        return bars
    ds_m = TIMEFRAME_MINUTES.get(dataset_tf, 1)
    st_m = TIMEFRAME_MINUTES.get(strategy_tf, 1)
    if ds_m < st_m:
        return aggregate_bars(bars, strategy_tf)
    if ds_m > st_m:
        return bars  # cannot upsample honestly
    return bars