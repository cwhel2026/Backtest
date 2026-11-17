"""Exhaustive + random combinatorial search space for prop-style DSL specs."""

from __future__ import annotations

import random
from itertools import product
from typing import Any, Iterator

SESSION = {"allowed": ["RTH"], "timezone": "America/Chicago"}

STOP_TARGETS = (
    (8, 16),
    (10, 20),
    (12, 24),
    (12, 28),
    (14, 28),
    (16, 32),
    (18, 36),
    (20, 40),
    (22, 44),
    (24, 48),
    (16, 24),
    (20, 30),
)

RISK_PROFILES = (
    {"dollar_risk_per_trade": 50, "max_contracts": 2},
    {"dollar_risk_per_trade": 75, "max_contracts": 3},
    {"dollar_risk_per_trade": 100, "max_contracts": 4},
    {"dollar_risk_per_trade": 125, "max_contracts": 5},
)


def _base(symbol: str, timeframe: str, category: str, entry: dict, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "instrument_symbol": symbol.upper(),
        "timeframe": timeframe,
        "category": category,
        "session": dict(SESSION),
        "entry": entry,
        "exit": {"stop_ticks": 16, "target_ticks": 32, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
    }


def _orb_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for minutes, side, (stop, target), risk in product(
        (10, 15, 20, 30),
        ("both", "long", "short"),
        STOP_TARGETS,
        RISK_PROFILES,
    ):
        yield {
            **_base(
                symbol,
                timeframe,
                "opening_range_breakout",
                {"type": "opening_range_breakout", "range_minutes": minutes, "side": side},
                f"{symbol} ORB {minutes}m {side} {stop}/{target}",
            ),
            "exit": {"stop_ticks": stop, "target_ticks": target, "session_end_flatten": True},
            "risk": dict(risk),
        }


def _ema_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    pairs = (
        (5, 13),
        (8, 21),
        (9, 26),
        (10, 30),
        (12, 26),
        (13, 34),
        (15, 40),
        (20, 50),
    )
    for fast, slow in pairs:
        if fast >= slow:
            continue
        for stop, target in STOP_TARGETS:
            for risk in RISK_PROFILES:
                yield {
                    **_base(
                        symbol,
                        timeframe,
                        "trend_continuation",
                        {"type": "ema_crossover", "fast_period": fast, "slow_period": slow},
                        f"{symbol} EMA {fast}/{slow} {stop}/{target}",
                    ),
                    "exit": {"stop_ticks": stop, "target_ticks": target, "session_end_flatten": True},
                    "risk": dict(risk),
                }


def _vwap_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for dev, (stop, target), risk in product((10, 12, 14, 16, 20, 24, 28), STOP_TARGETS, RISK_PROFILES):
        yield {
            **_base(
                symbol,
                timeframe,
                "vwap_mean_reversion",
                {"type": "vwap_reversion", "deviation_ticks": dev},
                f"{symbol} VWAP rev {dev}t {stop}/{target}",
            ),
            "exit": {"stop_ticks": stop, "target_ticks": target, "session_end_flatten": True},
            "risk": dict(risk),
        }


def all_search_specs(symbol: str, timeframe: str = "5m") -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    specs.extend(_orb_specs(symbol, timeframe))
    specs.extend(_ema_specs(symbol, timeframe))
    specs.extend(_vwap_specs(symbol, timeframe))
    return specs


def sample_search_specs(symbol: str, budget: int, *, seed: int | None = None) -> list[dict[str, Any]]:
    pool = all_search_specs(symbol)
    if budget >= len(pool):
        return pool
    rng = random.Random(seed)
    return rng.sample(pool, budget)


def refine_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Local mutations around a near-miss candidate."""
    stop = int(spec["exit"]["stop_ticks"])
    target = int(spec["exit"]["target_ticks"])
    out: list[dict[str, Any]] = []
    for ds, dt in ((-2, 0), (0, 4), (2, 4), (-2, -4), (2, 0)):
        s2, t2 = max(4, stop + ds), max(8, target + dt)
        if s2 >= t2:
            continue
        copy = {**spec, "exit": {**spec["exit"], "stop_ticks": s2, "target_ticks": t2}}
        copy["name"] = f"{spec['name']} refine {s2}/{t2}"
        out.append(copy)
    return out