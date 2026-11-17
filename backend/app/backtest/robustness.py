"""Cost stress, session-shuffle Monte Carlo, and parameter-neighborhood checks."""

from __future__ import annotations

import random
from typing import Any

from app.backtest.bars import Bar
from app.backtest.dsl import session_keys_rth
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.models.instrument import Instrument


def group_session_bars(bars: list[Bar], session_keys: list[str] | None = None) -> list[list[Bar]]:
    keys = session_keys or session_keys_rth(bars)
    groups: list[list[Bar]] = []
    current: list[Bar] = []
    prev: str | None = None
    for bar, key in zip(bars, keys, strict=True):
        if prev is not None and key != prev:
            groups.append(current)
            current = []
        current.append(bar)
        prev = key
    if current:
        groups.append(current)
    return groups


def shuffle_session_order(bars: list[Bar], *, seed: int) -> list[Bar]:
    groups = group_session_bars(bars)
    if len(groups) <= 1:
        return list(bars)
    order = list(range(len(groups)))
    random.Random(seed).shuffle(order)
    out: list[Bar] = []
    for idx in order:
        out.extend(groups[idx])
    return out


def _safe_metrics(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    dataset_tf: str,
    assumptions: BacktestAssumptions,
) -> dict[str, Any] | None:
    try:
        return run_backtest(spec, bars, instrument, dataset_tf, assumptions).metrics
    except (ValueError, KeyError, ArithmeticError):
        return None


def _neighborhood_specs(spec: dict) -> list[dict]:
    exit_spec = spec.get("exit") or {}
    stop = int(exit_spec.get("stop_ticks", 16))
    target = int(exit_spec.get("target_ticks", 24))
    out: list[dict] = []
    for ds, dt in ((-2, 0), (0, 4), (2, 4), (-2, -4)):
        s2, t2 = max(4, stop + ds), max(6, target + dt)
        copy = {**spec, "exit": {**exit_spec, "stop_ticks": s2, "target_ticks": t2}}
        copy["name"] = f"{spec.get('name', 'spec')} nb {s2}/{t2}"
        out.append(copy)
    return out


def _profitable_enough(metrics: dict[str, Any] | None, *, min_pf: float = 1.0) -> bool:
    if not metrics:
        return False
    net = float(metrics.get("total_net_profit") or 0)
    pf = metrics.get("profit_factor")
    trades = int(metrics.get("trade_count") or 0)
    if net <= 0 or trades < 4:
        return False
    if pf is not None and float(pf) < min_pf:
        return False
    return True


def evaluate_robustness(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    dataset_tf: str,
    *,
    n_shuffles: int = 8,
    slip_ticks: int = 2,
    min_pass: float = 0.5,
    seed: int = 1,
) -> dict[str, Any]:
    """Run only on prop-screen survivors. Direct engine calls — not the search thread pool."""
    backtests = 0
    cost = _safe_metrics(
        spec,
        bars,
        instrument,
        dataset_tf,
        BacktestAssumptions(slippage_ticks_per_side=max(1, int(slip_ticks))),
    )
    backtests += 1
    cost_ok = _profitable_enough(cost, min_pf=1.0)

    sessions = group_session_bars(bars)
    mc_nets: list[float] = []
    mc_passes = 0
    shuffles = max(0, int(n_shuffles))
    if cost_ok and shuffles > 0 and len(sessions) >= 4:
        for i in range(shuffles):
            shuffled = shuffle_session_order(bars, seed=seed + 17 * (i + 1))
            m = _safe_metrics(spec, shuffled, instrument, dataset_tf, BacktestAssumptions(slippage_ticks_per_side=1))
            backtests += 1
            net = float((m or {}).get("total_net_profit") or 0)
            mc_nets.append(net)
            if _profitable_enough(m, min_pf=1.0):
                mc_passes += 1
        mc_rate = mc_passes / shuffles
    elif cost_ok:
        mc_rate = 1.0
    else:
        mc_rate = 0.0

    neighbors = _neighborhood_specs(spec)
    neigh_pass = 0
    if cost_ok and neighbors:
        for variant in neighbors:
            m = _safe_metrics(variant, bars, instrument, dataset_tf, BacktestAssumptions(slippage_ticks_per_side=1))
            backtests += 1
            if _profitable_enough(m, min_pf=1.0):
                neigh_pass += 1
        neigh_rate = neigh_pass / len(neighbors)
    elif cost_ok:
        neigh_rate = 1.0
    else:
        neigh_rate = 0.0

    mc_ok = mc_rate + 1e-9 >= float(min_pass)
    neigh_ok = neigh_rate + 1e-9 >= min(0.4, float(min_pass))
    passed = bool(cost_ok and mc_ok and neigh_ok)
    median_net = sorted(mc_nets)[len(mc_nets) // 2] if mc_nets else None
    score = int(round(40 * (1 if cost_ok else 0) + 40 * mc_rate + 20 * neigh_rate))
    return {
        "passed": passed,
        "backtests": backtests,
        "metrics": {
            "stress_slip_ticks": int(slip_ticks),
            "stress_slip_net": float(cost.get("total_net_profit") or 0) if cost else None,
            "stress_slip_pf": float(cost["profit_factor"]) if cost and cost.get("profit_factor") is not None else None,
            "mc_pass_rate": mc_rate,
            "mc_median_net": median_net,
            "mc_shuffles": shuffles if len(sessions) >= 4 else 0,
            "neighborhood_pass_rate": neigh_rate,
            "robustness_score": score,
        },
        "reason": (
            "ok"
            if passed
            else "cost_stress"
            if not cost_ok
            else "session_shuffle"
            if not mc_ok
            else "neighborhood"
        ),
    }
