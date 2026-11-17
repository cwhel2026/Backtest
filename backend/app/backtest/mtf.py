"""Map lower-timeframe bars to higher-timeframe context (no lookahead)."""

from __future__ import annotations

from app.backtest.bars import Bar, aggregate_bars


def htf_bars_from_ltf(bars_ltf: list[Bar], htf: str) -> list[Bar]:
    if not bars_ltf:
        return []
    return aggregate_bars(bars_ltf, htf)


def ltf_to_htf_index(bars_ltf: list[Bar], bars_htf: list[Bar]) -> list[int]:
    """For each LTF bar index, index of the HTF bar in effect (last HTF bar with ts <= ltf ts)."""
    if not bars_htf:
        return [0] * len(bars_ltf)
    out: list[int] = []
    h = 0
    for b in bars_ltf:
        while h + 1 < len(bars_htf) and bars_htf[h + 1].ts <= b.ts:
            h += 1
        out.append(min(h, len(bars_htf) - 1))
    return out


def series_on_ltf(htf_series: list, ltf_indices: list[int]) -> list:
    return [htf_series[j] if j < len(htf_series) else None for j in ltf_indices]