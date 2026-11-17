"""Reverse / fade engine.

If a setup wins ~8% of the time, taking the opposite side (and swapping stop with
target) is the same trade list with wins and losses flipped — theoretically ~92% WR.

Naive reverse (flip side, keep 1:4 R:R) does *not* invert win rate. The 92% of
trades that hit a 16-tick stop only become winners if the reverse *target* is 16
ticks. So we:

1. Invert the entry direction (fade the original signal)
2. Swap stop_ticks ↔ target_ticks
3. Re-backtest walk-forward — never claim the 92% without a real OOS pass
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def implied_reversed_win_rate(win_rate: float | None) -> float | None:
    if win_rate is None:
        return None
    return max(0.0, min(1.0, 1.0 - float(win_rate)))


def is_anti_edge(
    metrics: dict[str, Any] | None,
    *,
    winrate_max: float = 0.20,
    min_trades: int = 6,
) -> bool:
    """True when the original setup is a fade candidate, not a keeper."""
    if not metrics:
        return False
    wr = metrics.get("win_rate")
    trades = int(metrics.get("trade_count") or 0)
    if wr is None or trades < min_trades:
        return False
    wr_f = float(wr)
    if wr_f <= winrate_max:
        return True
    net = float(metrics.get("total_net_profit") or 0)
    pf = metrics.get("profit_factor")
    # Practical: clearly inverted expectancy with WR well below coin-flip
    if wr_f <= 0.40 and net < 0 and trades >= 8 and (pf is None or float(pf) < 0.95):
        return True
    return False


def reverse_spec(spec: dict[str, Any], *, original_metrics: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return inverted spec, or None if already reversed / not invertible."""
    entry = dict(spec.get("entry") or {})
    if entry.get("invert"):
        return None
    exit_spec = dict(spec.get("exit") or {})
    stop = int(exit_spec.get("stop_ticks", 16))
    target = int(exit_spec.get("target_ticks", 32))
    if stop < 1 or target < 1:
        return None

    entry["invert"] = True
    out = deepcopy(spec)
    out["entry"] = entry
    out["exit"] = {**exit_spec, "stop_ticks": target, "target_ticks": stop}
    base_name = str(spec.get("name") or "setup")
    out["name"] = base_name if base_name.startswith("REV ") else f"REV {base_name}"
    cat = str(spec.get("category") or "setup")
    out["category"] = cat if cat.startswith("reversed_") else f"reversed_{cat}"
    orig_wr = (original_metrics or {}).get("win_rate")
    out["origin"] = "reverse_anti_edge"
    out["reversed_from"] = spec.get("name")
    if orig_wr is not None:
        out["implied_win_rate"] = implied_reversed_win_rate(float(orig_wr))
        out["original_win_rate"] = float(orig_wr)
    return out


def reverse_passes_oos(test_metrics: dict[str, Any] | None, original_train_wr: float | None) -> bool:
    """Reversed candidate must actually invert — not just scrape a tiny net."""
    if not test_metrics:
        return False
    net = float(test_metrics.get("total_net_profit") or 0)
    pf = test_metrics.get("profit_factor")
    trades = int(test_metrics.get("trade_count") or 0)
    wr = test_metrics.get("win_rate")
    if net <= 0 or trades < 4 or pf is None or float(pf) < 1.05:
        return False
    if wr is None:
        return False
    wr_f = float(wr)
    if original_train_wr is not None and wr_f <= float(original_train_wr):
        return False
    return wr_f >= 0.45
