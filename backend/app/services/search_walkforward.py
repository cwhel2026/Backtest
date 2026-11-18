"""Rolling walk-forward folds for deep search OOS gates."""

from __future__ import annotations

from typing import Any


def split_holdout(bars: list, holdout_frac: float = 0.2) -> tuple[list, list]:
    """Last holdout_frac of bars is never used for train / OOS / selection."""
    if len(bars) < 80 or holdout_frac <= 0:
        return bars, []
    cut = int(len(bars) * (1.0 - holdout_frac))
    cut = max(40, min(cut, len(bars) - 15))
    return bars[:cut], bars[cut:]


def walk_forward_folds(bars: list, n_folds: int = 3) -> list[tuple[list, list]]:
    """Expanding train windows with contiguous OOS slices (intraday bars in time order)."""
    if n_folds < 2 or len(bars) < 100:
        mid = int(len(bars) * 0.65)
        return [(bars[:mid], bars[mid:])]
    chunk = max(20, len(bars) // (n_folds + 1))
    folds: list[tuple[list, list]] = []
    for i in range(n_folds):
        train_end = chunk * (i + 1)
        test_start = train_end
        test_end = min(len(bars), chunk * (i + 2))
        if test_end - test_start < 15 or train_end < 40:
            continue
        folds.append((bars[:train_end], bars[test_start:test_end]))
    return folds or [(bars[: int(len(bars) * 0.65)], bars[int(len(bars) * 0.65) :])]


def aggregate_fold_metrics(fold_metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not fold_metrics:
        return None
    nets = [float(m.get("total_net_profit") or 0) for m in fold_metrics]
    wrs = [float(m.get("win_rate") or 0) for m in fold_metrics if m.get("win_rate") is not None]
    pfs = [float(m.get("profit_factor") or 0) for m in fold_metrics if m.get("profit_factor") is not None]
    trades = [int(m.get("trade_count") or 0) for m in fold_metrics]
    return {
        "total_net_profit": sum(nets) / len(nets),
        "win_rate": min(wrs) if wrs else None,
        "profit_factor": min(pfs) if pfs else None,
        "trade_count": sum(trades),
        "fold_count": len(fold_metrics),
        "fold_net_sum": sum(nets),
    }


def folds_pass_oos(
    fold_metrics: list[dict[str, Any]],
    *,
    min_folds: int,
    min_win_rate: float,
    per_fold_check,
) -> bool:
    if not fold_metrics:
        return False
    passed = sum(1 for m in fold_metrics if per_fold_check(m) and float(m.get("win_rate") or 0) >= min_win_rate)
    required = min_folds if len(fold_metrics) >= min_folds else 1
    return passed >= required