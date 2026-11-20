"""Symbol-wide incremental detection on each closed candle (no fabricated signals)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.bars import Bar
from app.core.config import get_settings
from app.models.enums import ScannerSetupStatus
from app.models.instrument import Instrument
from app.models.live_lab import LiveCompletedCandle, LiveFeedStatus
from app.models.scanner import ScannerWatchState
from app.services.live_lab.candle_engine import load_closed_bars
from app.services.live_lab.incremental_signals import discover_berg_orders, discover_video_orders
from app.services.scanner.persistence import upsert_order_setup, upsert_rejected_candidate
from app.services.scanner.templates import MARKET_SCANNER_TEMPLATES


def _bar_from_candle(c: LiveCompletedCandle) -> Bar:
    return Bar(ts=c.ts, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)


def _ensure_watch(session: Session, symbol: str, strategy_key: str) -> ScannerWatchState:
    row = session.execute(
        select(ScannerWatchState).where(
            ScannerWatchState.symbol == symbol.upper(),
            ScannerWatchState.strategy_key == strategy_key,
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row:
        return row
    row = ScannerWatchState(symbol=symbol.upper(), strategy_key=strategy_key, runner_state={}, last_bar_ts=None, updated_at=now)
    session.add(row)
    session.flush()
    return row


def run_scanner_on_candle(session: Session, candle: LiveCompletedCandle, *, decision_ts: datetime | None = None) -> int:
    if candle.timeframe != "5m":
        return 0
    symbol = candle.symbol.upper()
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        return 0
    feed = session.execute(select(LiveFeedStatus).order_by(LiveFeedStatus.updated_at.desc()).limit(1)).scalar_one_or_none()
    latency = feed.latency_mode.value if feed and feed.latency_mode else None
    provider = feed.provider if feed else None
    bar = _bar_from_candle(candle)
    written = 0

    for tpl in MARKET_SCANNER_TEMPLATES:
        watch = _ensure_watch(session, symbol, tpl["strategy_key"])
        if watch.last_bar_ts and watch.last_bar_ts >= candle.ts:
            continue
        spec = dict(tpl["spec"])
        entry = (spec.get("entry") or {}).get("type", "")
        state = dict(watch.runner_state or {})
        bars = load_closed_bars(session, symbol, "5m", limit=1200)
        if not bars or bars[-1].ts < bar.ts:
            bars.append(bar)
        bar_index = len(bars) - 1

        if entry == "berg_tnb_model_v1":
            bars_4h = load_closed_bars(session, symbol, "4h", limit=200)
            if len(bars_4h) < 3:
                upsert_rejected_candidate(
                    session,
                    symbol=symbol,
                    strategy_key=tpl["strategy_key"],
                    strategy_name=tpl["strategy_name"],
                    strategy_version=tpl["strategy_version"],
                    market_ts=bar.ts,
                    reason="Berg TNB requires confirmed closed 4H candles in store",
                    forward_run_id=None,
                    data_source=provider,
                    feed_latency_mode=latency,
                    diagnostics={"unresolved": "4h bias"},
                )
                written += 1
                watch.last_bar_ts = candle.ts
                watch.updated_at = datetime.now(UTC)
                continue
            berg_rt = state.get("berg_runtime")
            orders, berg_dict, _am = discover_berg_orders(
                spec, bars, inst, at_index=bar_index, bars_4h=bars_4h, runtime=berg_rt
            )
            state["berg_runtime"] = berg_dict
        else:
            orders, vrt = discover_video_orders(
                spec, bars, inst, at_index=bar_index, video_runtime=state.get("video_runtime")
            )
            state["video_runtime"] = vrt

        for order in orders:
            upsert_order_setup(
                session,
                order=order,
                symbol=symbol,
                strategy_key=tpl["strategy_key"],
                strategy_name=tpl["strategy_name"],
                strategy_version=tpl["strategy_version"],
                market_ts=bar.ts,
                status=ScannerSetupStatus.DETECTED,
                explanation=order.reason,
                forward_run_id=None,
                data_source=provider,
                feed_latency_mode=latency,
                diagnostics={"order_key": order.setup_id, "scanner_watch": True},
            )
            written += 1

        watch.runner_state = state
        watch.last_bar_ts = candle.ts
        watch.updated_at = datetime.now(UTC)

    return written


def run_scanner_cycle(session: Session) -> dict:
    settings = get_settings()
    symbols = [s.strip().upper() for s in settings.live_lab_symbols.split(",") if s.strip()]
    count = 0
    for sym in symbols:
        candle = session.execute(
            select(LiveCompletedCandle)
            .where(LiveCompletedCandle.symbol == sym, LiveCompletedCandle.timeframe == "5m")
            .order_by(LiveCompletedCandle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if candle:
            count += run_scanner_on_candle(session, candle)
    return {"symbols": symbols, "setups_written": count}