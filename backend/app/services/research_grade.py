"""Honest research grades — green P&L on a 7-day 1m window is a probe, not a keeper."""

from __future__ import annotations

import random
from typing import Any

from app.services.prop_screen import is_profitable_backtest, min_trades_for

GRADE_KEEPER = "keeper"
GRADE_CANDIDATE = "candidate"
GRADE_PROBE = "probe"
GRADE_MISS = "miss"

KEEPER_MIN_TRADES = 15
HOLDOUT_FRAC = 0.2
# Yahoo 1m is capped at ~7 calendar days; anything shorter is a probe scan.
THIN_1M_DAYS = 12


def bootstrap_mean_ci(
    values: list[float],
    *,
    n: int = 400,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for the mean (expectancy). None if the sample is too small."""
    if len(values) < 4:
        return None, None
    rng = random.Random(seed)
    k = len(values)
    means: list[float] = []
    for _ in range(n):
        total = 0.0
        for _i in range(k):
            total += values[rng.randrange(k)]
        means.append(total / k)
    means.sort()
    lo_i = max(0, int((alpha / 2) * n))
    hi_i = min(n - 1, int((1.0 - alpha / 2) * n))
    return float(means[lo_i]), float(means[hi_i])


def attach_expectancy_ci(metrics: dict[str, Any], trade_pnls: list[float], *, seed: int = 0) -> dict[str, Any]:
    out = dict(metrics)
    lo, hi = bootstrap_mean_ci(trade_pnls, seed=seed)
    if lo is None or hi is None:
        return out
    out["expectancy_ci_low"] = round(lo, 4)
    out["expectancy_ci_high"] = round(hi, 4)
    out["expectancy_ci_includes_zero"] = lo <= 0 <= hi
    return out


def source_slug(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if "finz" in text:
        return "finzdata"
    if "ibkr" in text or "interactive" in text:
        return "ibkr"
    if "databento" in text:
        return "databento"
    if "yahoo" in text:
        return "yahoo"
    if "csv" in text:
        return "csv"
    return text or "unknown"


def is_thin_1m_sample(
    timeframe: str | None,
    *,
    data_source: str | None = None,
    sample_days: float | None = None,
) -> bool:
    tf = (timeframe or "").strip().lower()
    if tf not in ("1m", "1min", "1"):
        return False
    slug = source_slug(data_source)
    if slug == "yahoo":
        return True
    if sample_days is not None and sample_days < THIN_1M_DAYS:
        return True
    return False


def research_grade(
    metrics: dict[str, Any] | None,
    *,
    oos: dict[str, Any] | None = None,
    holdout: dict[str, Any] | None = None,
    reverse: bool = False,
    timeframe: str | None = None,
    data_source: str | None = None,
    sample_days: float | None = None,
) -> str:
    if not metrics:
        return GRADE_MISS
    net = float(metrics.get("total_net_profit") or 0)
    trades = int(metrics.get("trade_count") or 0)
    if net <= 0:
        return GRADE_MISS
    green = is_profitable_backtest(metrics, reverse=reverse, timeframe=timeframe)
    thin_1m = is_thin_1m_sample(timeframe, data_source=data_source, sample_days=sample_days)
    if not green:
        return GRADE_PROBE if trades >= 4 else GRADE_MISS
    if thin_1m or trades < KEEPER_MIN_TRADES:
        return GRADE_PROBE

    if oos:
        oos_net = float(oos.get("total_net_profit") or 0)
        if oos_net <= 0:
            return GRADE_PROBE

    holdout_net = _holdout_net(metrics, holdout)
    ci_lo = metrics.get("expectancy_ci_low")
    ci_includes_zero = ci_lo is not None and float(ci_lo) <= 0
    if holdout_net is not None and holdout_net < 0:
        return GRADE_CANDIDATE
    if ci_includes_zero:
        return GRADE_CANDIDATE
    return GRADE_KEEPER


def effective_grade(
    metrics: dict[str, Any] | None,
    params: dict[str, Any] | None = None,
    *,
    reverse: bool = False,
    timeframe: str | None = None,
    data_source: str | None = None,
    sample_days: float | None = None,
) -> str:
    stored = None
    if isinstance(metrics, dict) and metrics.get("grade"):
        stored = str(metrics.get("grade"))
    elif isinstance(params, dict) and params.get("grade"):
        stored = str(params.get("grade"))
    if stored in {GRADE_KEEPER, GRADE_CANDIDATE, GRADE_PROBE, GRADE_MISS}:
        return stored
    oos = params.get("oos_metrics") if isinstance(params, dict) and isinstance(params.get("oos_metrics"), dict) else None
    holdout = None
    if isinstance(params, dict) and isinstance(params.get("holdout_metrics"), dict):
        holdout = params["holdout_metrics"]
    return research_grade(
        metrics,
        oos=oos,
        holdout=holdout,
        reverse=reverse,
        timeframe=timeframe,
        data_source=data_source,
        sample_days=sample_days,
    )


def is_keeper_grade(grade: str | None) -> bool:
    return grade == GRADE_KEEPER


def grade_reason(
    grade: str,
    metrics: dict[str, Any] | None,
    *,
    timeframe: str | None = None,
) -> str | None:
    if grade == GRADE_KEEPER:
        return None
    trades = int((metrics or {}).get("trade_count") or 0)
    tf = (timeframe or "5m").strip().lower()
    if grade == GRADE_CANDIDATE:
        holdout_net = _holdout_net(metrics, None)
        ci_lo = (metrics or {}).get("expectancy_ci_low")
        if holdout_net is not None and holdout_net < 0:
            return f"Holdout window lost ${abs(holdout_net):.0f} — candidate, not a keeper"
        if ci_lo is not None and float(ci_lo) <= 0:
            return "Expectancy 95% CI includes $0 — not statistically a keeper"
        return "Passed the green screen but not the keeper bar (holdout or CI)"
    if grade == GRADE_PROBE:
        extra = " — Yahoo 1m is only ~7 days, so four-trade ORBs are luck until a longer feed" if tf in (
            "1m",
            "1min",
            "1",
        ) else ""
        if trades < KEEPER_MIN_TRADES:
            return f"Probe: {trades} trades is too thin for a keeper (need ≥{KEEPER_MIN_TRADES}){extra}"
        return f"Probe: short 1m sample, not desk-ready{extra}"
    need = min_trades_for(timeframe)
    if trades < need:
        return f"Needs ≥{need} trades (has {trades})"
    return "Did not pass the prop screen"


def _holdout_net(metrics: dict[str, Any] | None, holdout: dict[str, Any] | None) -> float | None:
    if holdout is not None:
        if holdout.get("total_net_profit") is not None:
            return float(holdout.get("total_net_profit") or 0)
        if holdout.get("holdout_net") is not None:
            return float(holdout.get("holdout_net") or 0)
    if metrics is not None and metrics.get("holdout_net") is not None:
        return float(metrics.get("holdout_net") or 0)
    return None
