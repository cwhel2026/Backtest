"""Prop-firm style filters — only surface strategies that backtest profitably."""

from __future__ import annotations

from typing import Any

# Intraday RTH strategies: wide R:R scalps with ~20% WR are not prop-desk ready.
INTRADAY_MIN_WIN_RATE = 0.42


def min_trades_for(timeframe: str | None, *, reverse: bool = False) -> int:
    """1m search windows are ~7 days, so a daily ORB cannot hit the 5m 8-trade floor."""
    tf = (timeframe or "5m").strip().lower()
    if tf in ("1m", "1min", "1"):
        return 3 if reverse else 4
    return 6 if reverse else 8


def is_profitable_backtest(
    metrics: dict[str, Any] | None,
    *,
    reverse: bool = False,
    timeframe: str | None = None,
) -> bool:
    if not metrics:
        return False
    net = float(metrics.get("total_net_profit") or 0)
    pf = metrics.get("profit_factor")
    trades = int(metrics.get("trade_count") or 0)
    if net <= 0:
        return False
    min_pf = 1.05 if reverse else 1.1
    min_trades = min_trades_for(timeframe, reverse=reverse)
    if pf is None or float(pf) < min_pf:
        return False
    if trades < min_trades:
        return False
    max_dd = float(metrics.get("max_drawdown") or 0)
    if max_dd > 3500:
        return False
    if not reverse:
        wr = metrics.get("win_rate")
        if wr is not None and float(wr) < INTRADAY_MIN_WIN_RATE:
            return False
    return True


def prop_gate_miss(
    metrics: dict[str, Any] | None,
    *,
    reverse: bool = False,
    timeframe: str | None = None,
) -> str | None:
    """Human reason a green-P&L run is not a keeper. None if it passes."""
    if is_profitable_backtest(metrics, reverse=reverse, timeframe=timeframe):
        return None
    if not metrics:
        return "No backtest metrics"
    net = float(metrics.get("total_net_profit") or 0)
    if net <= 0:
        return "Net P&L is not positive"
    trades = int(metrics.get("trade_count") or 0)
    need = min_trades_for(timeframe, reverse=reverse)
    if trades < need:
        tf = (timeframe or "5m").lower()
        extra = " — 1m history is only ~7 days" if tf in ("1m", "1min", "1") else ""
        return f"Needs ≥{need} trades (has {trades}){extra}"
    pf = metrics.get("profit_factor")
    min_pf = 1.05 if reverse else 1.1
    if pf is None or float(pf) < min_pf:
        return f"Profit factor below {min_pf}"
    max_dd = float(metrics.get("max_drawdown") or 0)
    if max_dd > 3500:
        return "Drawdown above $3,500"
    wr = metrics.get("win_rate")
    if not reverse and wr is not None and float(wr) < INTRADAY_MIN_WIN_RATE:
        return f"Win rate below {INTRADAY_MIN_WIN_RATE:.0%} (has {float(wr):.0%})"
    return "Did not pass the prop screen"


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
    wr = float(metrics.get("win_rate") or 0)
    robust = float(metrics.get("mc_pass_rate") or 0)
    return pf * 1000 + net * 0.5 + min(trades, 80) * 2 - dd * 0.1 + wr * 600 + robust * 250


def prop_readiness_score(metrics: dict[str, Any] | None, *, timeframe: str | None = None) -> int:
    """0–100 score for UI badge."""
    if not metrics:
        return 0
    wr = float(metrics.get("win_rate") or 0)
    if wr < INTRADAY_MIN_WIN_RATE:
        return 0
    if not is_profitable_backtest(metrics, timeframe=timeframe):
        return 0
    pf = float(metrics.get("profit_factor") or 1)
    net = float(metrics.get("total_net_profit") or 0)
    dd = float(metrics.get("max_drawdown") or 0)
    score = 25
    score += min(25, (pf - 1) * 22)
    score += min(15, net / 600)
    # Win rate is primary for intraday prop (not swing-style PF with tiny hit rate).
    score += min(40, max(0.0, (wr - INTRADAY_MIN_WIN_RATE) * 110))
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
        "avg_win_usd": round(float(metrics.get("average_win") or 0), 2)
        if metrics.get("average_win") is not None
        else None,
        "avg_loss_usd": round(float(metrics.get("average_loss") or 0), 2)
        if metrics.get("average_loss") is not None
        else None,
        "robustness_pct": round(float(metrics["mc_pass_rate"]) * 100, 0)
        if metrics.get("mc_pass_rate") is not None
        else None,
    }