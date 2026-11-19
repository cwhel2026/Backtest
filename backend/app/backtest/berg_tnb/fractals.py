"""Configurable fractal swings — Rachel_T Fractals not in repo (fidelity unverified)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass(frozen=True)
class FractalConfig:
    left: int = 2
    right: int = 2
    definition_id: str = "configurable_pivot_approximation"

    def as_meta(self) -> dict:
        return {
            "definition": self.definition_id,
            "left": self.left,
            "right": self.right,
            "rachel_t_verified": False,
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