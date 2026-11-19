"""Fractal swings — Williams-style pivots (approximates TradingView Fractals by Rachel_T).

PDF step 2: only fractal highs/lows (arrow markers) qualify as BOS reference points.
Rachel_T source code not in repo — default 2+2 matches common TV Fractals preset (**interpretation**).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass(frozen=True)
class FractalConfig:
    left: int = 2
    right: int = 2
    definition_id: str = "williams_fractal_2_2_rachel_t_approx"

    def as_meta(self) -> dict:
        return {
            "definition": self.definition_id,
            "left": self.left,
            "right": self.right,
            "rachel_t_verified": False,
            "pdf_reference": "Berg PDF step 2 — fractal indicator by Rachel_T",
        }


@dataclass
class ConfirmedFractal:
    confirm_index: int
    pivot_index: int
    kind: str
    level: Decimal


def confirmed_fractals(bars: list[Bar], cfg: FractalConfig) -> list[ConfirmedFractal]:
    """Fractal known only after `right` bars (no lookahead)."""
    out: list[ConfirmedFractal] = []
    for j in range(cfg.left, len(bars) - cfg.right):
        window = bars[j - cfg.left : j + cfg.right + 1]
        if bars[j].high == max(x.high for x in window) and sum(x.high == bars[j].high for x in window) == 1:
            out.append(
                ConfirmedFractal(j + cfg.right, j, "high", bars[j].high)
            )
        if bars[j].low == min(x.low for x in window) and sum(x.low == bars[j].low for x in window) == 1:
            out.append(
                ConfirmedFractal(j + cfg.right, j, "low", bars[j].low)
            )
    return sorted(out, key=lambda f: f.confirm_index)


def fractals_visible_at(fractals: list[ConfirmedFractal], bar_index: int) -> list[ConfirmedFractal]:
    return [f for f in fractals if f.confirm_index <= bar_index]