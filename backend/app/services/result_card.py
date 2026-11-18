"""Sample window and risk copy for result cards."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def sample_window(
    *,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    row_count: int,
    timeframe: str,
) -> dict[str, Any]:
    days = None
    if coverage_start and coverage_end:
        delta = coverage_end - coverage_start
        days = round(max(delta.total_seconds(), 0) / 86400, 1)
    start = coverage_start.isoformat() if coverage_start else None
    end = coverage_end.isoformat() if coverage_end else None
    parts = []
    if days is not None:
        parts.append(f"{days:g} day" + ("s" if days != 1 else ""))
    parts.append(timeframe)
    if row_count:
        parts.append(f"{row_count:,} bars")
    return {
        "start": start,
        "end": end,
        "bars": int(row_count or 0),
        "days": days,
        "timeframe": timeframe,
        "summary": " · ".join(parts) if parts else timeframe,
    }


def risk_profile(
    spec: dict | None,
    metrics: dict | None,
    *,
    tick_value: float,
    starting_equity: float = 100_000,
) -> dict[str, Any]:
    spec = spec or {}
    metrics = metrics or {}
    exit_spec = spec.get("exit") or {}
    risk = spec.get("risk") or {}
    stop_ticks = _int(exit_spec.get("stop_ticks"))
    target_ticks = _int(exit_spec.get("target_ticks"))
    stop_atr = _float(exit_spec.get("stop_atr"))
    target_atr = _float(exit_spec.get("target_atr"))
    dollar_risk = _float(risk.get("dollar_risk_per_trade"))
    max_contracts = _int(risk.get("max_contracts")) or 1
    tv = float(tick_value or 0)
    stop_usd = round(stop_ticks * tv, 2) if stop_ticks and tv else None
    target_usd = round(target_ticks * tv, 2) if target_ticks and tv else None
    rr = None
    if stop_ticks and target_ticks:
        rr = round(target_ticks / stop_ticks, 2)
    elif stop_atr and target_atr:
        rr = round(target_atr / stop_atr, 2)
    max_dd = _float(metrics.get("max_drawdown"))
    avg_loss = _float(metrics.get("average_loss"))
    if avg_loss is not None:
        avg_loss = abs(avg_loss)
    dd_pct = round(max_dd / starting_equity * 100, 2) if max_dd is not None else None
    planned = dollar_risk if dollar_risk else stop_usd
    bits: list[str] = []
    if stop_atr:
        bits.append(f"Stop {stop_atr:g} ATR" + (f" (floor {stop_ticks} ticks ≈ ${stop_usd:.0f}/ct)" if stop_usd else ""))
    elif stop_ticks and stop_usd is not None:
        bits.append(f"Stop {stop_ticks} ticks ≈ ${stop_usd:.0f}/contract")
    elif stop_ticks:
        bits.append(f"Stop {stop_ticks} ticks")
    if target_atr:
        bits.append(f"target {target_atr:g} ATR")
    elif target_ticks:
        bits.append(f"target {target_ticks} ticks" + (f" (${target_usd:.0f})" if target_usd is not None else ""))
    if rr:
        bits.append(f"{rr:g}R")
    if planned:
        bits.append(f"sized to ${planned:.0f} risk, max {max_contracts} contract" + ("s" if max_contracts != 1 else ""))
    if max_dd is not None:
        bits.append(f"sample max DD ${max_dd:.0f}" + (f" ({dd_pct:g}% of ${starting_equity:,.0f})" if dd_pct is not None else ""))
    if avg_loss:
        bits.append(f"avg losing trade ${avg_loss:.0f}")
    return {
        "stop_ticks": stop_ticks,
        "target_ticks": target_ticks,
        "stop_atr": stop_atr,
        "target_atr": target_atr,
        "stop_usd": stop_usd,
        "target_usd": target_usd,
        "reward_risk": rr,
        "dollar_risk_per_trade": dollar_risk,
        "max_contracts": max_contracts,
        "tick_value": tv or None,
        "max_drawdown_usd": max_dd,
        "dd_pct_of_account": dd_pct,
        "avg_loss_usd": avg_loss,
        "starting_equity": starting_equity,
        "summary": " · ".join(b for b in bits if b) or "Risk not stored on this run",
    }


def build_test_meta(
    *,
    tested_at: datetime | None,
    params: dict | None,
    metrics: dict | None,
) -> dict[str, Any]:
    params = params or {}
    metrics = metrics or {}
    oos = params.get("oos_metrics") if isinstance(params.get("oos_metrics"), dict) else {}
    train = params.get("train_metrics") if isinstance(params.get("train_metrics"), dict) else {}
    origin = str(params.get("origin") or "deep")
    method = {
        "near_miss": "Closest full-sample test (did not pass every search gate)",
        "reverse": "Walk-forward reverse fade · train / OOS / full sample",
        "ai": "Walk-forward + AI mutation · train / OOS / full sample",
        "deep": "Walk-forward · train / OOS / full-sample prop screen",
    }.get(origin, "Walk-forward backtest")
    oos_trades = _int(oos.get("trade_count"))
    oos_wr = _float(oos.get("win_rate"))
    oos_net = _float(oos.get("total_net_profit"))
    train_trades = _int(train.get("trade_count"))
    full_trades = _int(metrics.get("trade_count"))
    bits = [method]
    if train_trades:
        bits.append(f"train {train_trades} trades")
    if oos_trades:
        wr_bit = f", {oos_wr:.0%} WR" if oos_wr is not None else ""
        net_bit = f", net ${oos_net:.0f}" if oos_net is not None else ""
        bits.append(f"OOS {oos_trades} trades{wr_bit}{net_bit}")
    if full_trades:
        bits.append(f"full sample {full_trades} trades")
    return {
        "tested_at": tested_at.isoformat() if tested_at else None,
        "origin": origin,
        "method": method,
        "oos_trades": oos_trades,
        "oos_win_rate_pct": round(oos_wr * 100, 1) if oos_wr is not None else None,
        "oos_net": oos_net,
        "train_trades": train_trades,
        "full_trades": full_trades,
        "summary": " · ".join(bits),
    }


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
