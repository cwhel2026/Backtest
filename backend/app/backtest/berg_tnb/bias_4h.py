"""4-hour directional bias from confirmed fractal BOS (body close)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.berg_tnb.fractals import ConfirmedFractal, FractalConfig, confirmed_fractals
from app.backtest.berg_tnb.types import Bias4hRecord, BiasDir


@dataclass
class Bias4hSnapshot:
    direction: BiasDir | None
    record: Bias4hRecord


def build_4h_bias_series(
    bars_4h: list[Bar],
    fractal: FractalConfig,
) -> list[Bias4hSnapshot]:
    """Per 4H bar index, bias from most recent valid close-based BOS (no wick-only breaks)."""
    fractals = confirmed_fractals(bars_4h, fractal)
    series: list[Bias4hSnapshot] = []
    last: Bias4hRecord | None = None
    direction: BiasDir | None = None
    for i, b in enumerate(bars_4h):
        visible = [f for f in fractals if f.confirm_index <= i]
        prev_close = bars_4h[i - 1].close if i > 0 else None
        for f in visible:
            if f.kind == "high" and b.close > f.level and (prev_close is None or prev_close <= f.level):
                direction = "bullish"
                last = Bias4hRecord(
                    "bullish",
                    f.level,
                    b.ts,
                    f.confirm_index,
                    i,
                    fractal.definition_id,
                )
            if f.kind == "low" and b.close < f.level and (prev_close is None or prev_close >= f.level):
                direction = "bearish"
                last = Bias4hRecord(
                    "bearish",
                    f.level,
                    b.ts,
                    f.confirm_index,
                    i,
                    fractal.definition_id,
                )
        record = last or Bias4hRecord(None, None, None, None, None, fractal.definition_id)
        series.append(Bias4hSnapshot(direction=direction, record=record))
    return series


def bias_for_5m_bar(
    bars_4h: list[Bar],
    bias_series: list[Bias4hSnapshot],
    ts: datetime,
) -> Bias4hSnapshot:
    """Map a 5m timestamp to the last completed 4H bar (no future 4H leak)."""
    idx = -1
    u = ts.astimezone(bars_4h[0].ts.tzinfo) if ts.tzinfo and bars_4h else ts
    for i, b in enumerate(bars_4h):
        if b.ts <= u:
            idx = i
        else:
            break
    if idx < 0:
        empty = Bias4hRecord(None, None, None, None, None, "unknown")
        return Bias4hSnapshot(None, empty)
    return bias_series[idx]