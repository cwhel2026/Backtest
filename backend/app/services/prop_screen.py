"""Prop-firm style filters — only surface strategies that backtest profitably."""

from __future__ import annotations

from typing import Any


def is_profitable_backtest(metrics: dict[str, Any] | None) -> bool:
    if not metrics:
        return False
    net = float(metrics.get("total_net_profit") or 0)
    pf = metrics.get("profit_factor")
    trades = int(metrics.get("trade_count") or 0)
    if net <= 0:
        return False
    if pf is None or float(pf) < 1.1:
        return False
    if trades < 8:
        return False
    max_dd = float(metrics.get("max_drawdown") or 0)
    if max_dd > 3500:
        return False
    return True


def rank_score(metrics: dict[str, Any] | None) -> float:
    if not metrics:
        return -1e9
    net = float(metrics.get("total_net_profit") or 0)
    pf = float(metrics.get("profit_factor") or 0)
    trades = int(metrics.get("trade_count") or 0)
    dd = float(metrics.get("max_drawdown") or 1)
    if net <= 0:
        return -1e9
    # Higher PF and net, more trades (diminishing), penalize drawdown
    return pf * 1000 + net * 0.5 + min(trades, 80) * 2 - dd * 0.1


def prop_readiness_score(metrics: dict[str, Any] | None) -> int:
    """0–100 score for UI badge."""
    if not is_profitable_backtest(metrics):
        return 0
    pf = float(metrics.get("profit_factor") or 1)
    net = float(metrics.get("total_net_profit") or 0)
    wr = float(metrics.get("win_rate") or 0)
    dd = float(metrics.get("max_drawdown") or 0)
    score = 40
    score += min(30, (pf - 1) * 25)
    score += min(20, net / 500)
    score += min(15, wr * 20)
    score -= min(25, dd / 200)
    return max(0, min(100, int(round(score))))


def format_metric_display(metrics: dict[str, Any] | None) -> dict[str, str | int | None]:
    if not metrics:
        return {}
    pf = metrics.get("profit_factor")
    return {
        "net_profit_usd": round(float(metrics.get("total_net_profit") or 0), 2),
        "profit_factor": round(float(pf), 2) if pf is not None else None,
        "trade_count": int(metrics.get("trade_count") or 0),
        "win_rate_pct": round(float(metrics.get("win_rate") or 0) * 100, 1) if metrics.get("win_rate") is not None else None,
        "max_drawdown_usd": round(float(metrics.get("max_drawdown") or 0), 2),
        "expectancy_usd": round(float(metrics.get("expectancy_per_trade") or 0), 2)
        if metrics.get("expectancy_per_trade") is not None
        else None,
    }