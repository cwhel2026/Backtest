"""Chronological backtest vs incremental paper-path parity on historical tail bars."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.services.paper_engine import ClosedFill, SlotCursor, advance_slot


def incremental_fills_on_bars(spec: dict, bars, instrument: Instrument, *, slip_ticks: int = 1) -> list[ClosedFill]:
    """Replay bars through incremental slot engine (chronological, no live feed)."""
    if len(bars) < 3:
        return []
    cursor = SlotCursor(last_bar_ts=bars[1].ts, position=None)
    all_fills: list[ClosedFill] = []
    for end in range(2, len(bars)):
        chunk = bars[: end + 1]
        cursor, fills = advance_slot(spec, chunk, instrument, cursor, allow_entries=True, slip_ticks=slip_ticks)
        all_fills.extend(fills)
    return all_fills


def chronological_parity_check(
    session: Session,
    spec: dict,
    instrument: Instrument,
    dataset: HistoricalDataset,
    *,
    tail_bars: int = 120,
) -> tuple[bool, str]:
    bars = load_bars(session, dataset.id)
    tail = bars[-tail_bars:] if len(bars) > tail_bars else bars
    if len(tail) < 30:
        return False, "insufficient_tail_bars"
    tf = str(spec.get("timeframe") or dataset.timeframe or "5m")
    assumptions = BacktestAssumptions(slippage_ticks_per_side=1)
    bt = run_backtest(spec, tail, instrument, tf, assumptions)
    bt_trades = len(bt.trades or [])
    inc_fills = incremental_fills_on_bars(spec, tail, instrument, slip_ticks=1)
    inc_trades = len(inc_fills)
    if bt_trades == 0 and inc_trades == 0:
        return True, "both_zero_trades_tail"
    if abs(bt_trades - inc_trades) <= 1:
        return True, f"aligned bt={bt_trades} inc={inc_trades}"
    return False, f"trade_count_mismatch bt={bt_trades} inc={inc_trades}"